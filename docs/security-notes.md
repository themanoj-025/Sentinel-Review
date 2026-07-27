# Sentinel Review — Security Notes

> *Last updated: 2026-07-27*

## Threat Model

### Assets to Protect

| Asset | Sensitivity | Impact of Compromise |
|-------|-------------|---------------------|
| GitHub App private key | Critical | Full access to all installed repositories |
| LLM API key | Critical | Unauthorized API usage (monetary cost) |
| Webhook secret | High | Forged webhooks → malicious PR comments posted as bot |
| Django `SECRET_KEY` | High | Session forgery, CSRF bypass |
| User DB credentials | High | Direct database access |
| Private repository code | Medium | Exposure of proprietary code to LLM provider |
| Review comments / user feedback | Low | Minor data exposure |

### Attack Surface

```
Internet-facing:
  POST /webhooks/github  ← HMAC-protected, but public
  GET/POST /api/*        ← Read-only by default (IsAuthenticatedOrReadOnly)
  GET  /                 ← Dashboard (no auth in MVP)
  GET  /admin/           ← Django admin (requires auth)

Internal (Docker network):
  Redis :6379            ← No auth (internal network)
  PostgreSQL :5432       ← Password auth (sentinel:sentinel)
  Celery worker          ← Processes untrusted GitHub data
```

---

## Security Controls

### 1. Webhook HMAC Verification

Every incoming webhook must carry a valid `X-Hub-Signature-256` header.

```python
def verify_signature(payload_body: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        return False  # Missing → reject
    # Constant-time comparison prevents timing attacks
    return hmac.compare_digest(computed, expected_signature)
```

- **Enforcement:** Rejected at view level before any other processing
- **Dev bypass:** Empty `WEBHOOK_SECRET` disables verification for local development
- **Tested:** 10 unit tests cover valid, missing, tampered, malformed, and dev-mode signatures

### 2. GitHub App Authentication

```
GitHub App Private Key (loaded from env/mounted file)
  → JWT (RS256, 10min expiry, 60s clock drift tolerance)
    → Installation Access Token (1hr, cached, auto-refreshed)
```

- **Private key lifecycle:**
  - NEVER committed to the repository
  - Loaded from `GITHUB_APP_PRIVATE_KEY_B64` env var OR mounted `.secrets/github-app-private-key.pem`
  - The `.secrets/` directory is gitignored
- **JWT:** Generated per-request, short-lived (10 minutes), never stored
- **Installation tokens:** Short-lived (1 hour), cached in memory only, never persisted to database

### 3. Least-Privilege GitHub App Permissions

The GitHub App requests only the minimum required permissions:

| Permission | Access | Rationale |
|------------|--------|-----------|
| Repository contents | Read-only | Fetch diff, file contents, repo config |
| Pull requests | Read & Write | Read PR metadata, post inline review comments |
| Repository metadata | Read-only | Webhook delivery, repo info |

**Not requested:** Administration, secrets, actions, issues, webhooks (webhook config is done manually by the installing user).

### 4. Secrets Management

| Secret | Storage | Source of Truth |
|--------|---------|-----------------|
| `DJANGO_SECRET_KEY` | Env var | `.env` (local), GitHub Actions secrets (CI) |
| `WEBHOOK_SECRET` | Env var | `.env` (local), GitHub App config |
| `GITHUB_APP_PRIVATE_KEY_B64` | Env var | Base64-encoded, copied manually from GitHub App setup |
| `ANTHROPIC_API_KEY` | Env var | Anthropic Console |
| `OPENAI_API_KEY` | Env var | OpenAI Platform |
| Postgres password | Env var | `.env` (local), Docker Compose default for dev |

**All secrets are in `.gitignore`** via the `.env` pattern. `.env.example` contains placeholder values.

### 5. Database Secrets

- PostgreSQL password is set via environment variable
- Default dev password (`sentinel`) is documented as **change in production**
- No hardcoded credentials in any source file

### 6. Log Redaction

All log output passes through `sentinel_review.logging_filters.RedactingFilter`
before it reaches the console handler. This filter redacts the following
patterns from log messages, arguments, and exception text:

| Pattern | Example |
|---------|---------|
| Anthropic API keys | `sk-ant-...` |
| OpenAI API keys | `sk-...` (20+ alphanumeric chars) |
| RSA/DSA private keys | `-----BEGIN PRIVATE KEY-----...-----END PRIVATE KEY-----` |
| GitHub tokens | `ghp_...`, `ghs_...`, `gho_...`, `ghu_...`, `ghb_...`, `ghv_...` |
| Bearer tokens in headers | `Bearer eyJ...` |
| Password/secret assignments | `PASSWORD=supersecret`, `API_KEY=abc123...` |
| JWT tokens | `eyJ...` (three base64url segments) |
| Long hex strings (40+ chars) | `a1b2c3d4e5f6...` (potential hashes/secrets) |
| DB connection strings | `postgres://user:pass@host/db` |

**Implementation:**

```python
class RedactingFilter(logging.Filter):
    def filter(self, record):
        record.msg = self._redact(record.msg)
        record.args = tuple(
            self._redact(str(arg)) if isinstance(arg, str) else arg
            for arg in record.args
        )
        if record.exc_text:
            record.exc_text = self._redact(record.exc_text)
        return True

    @staticmethod
    def _redact(text: str) -> str:
        for pattern in REDACT_PATTERNS:
            text = pattern.sub('***REDACTED***', text)
        return text
```

The filter is registered in Django's `LOGGING` config as a handler-level filter
on the `console` handler, so it runs on every log record regardless of logger.

**Tested:** The filter is validated in CI via the planted-bug fixtures and
manual log inspection — no secret-like strings should appear in production logs.

### 7. Private Repository Opt-In

- **Default behavior:** Private repositories are **skipped** during review
- **Opt-in mechanism:** Dashboard toggle or API endpoint sets `repo.config.private_repo_opt_in = True`
- **Enforcement:** Check is deterministic code in `review_pull_request()`, not an LLM prompt instruction
- **Audit trail:** Each skipped review creates a Review record with `status=FAILED` and reason in `error_message`

### 8. Django Security Settings

| Setting | Value | Rationale |
|---------|-------|-----------|
| `SECURE_SSL_REDIRECT` | Unset (dev default) | Enable in production behind reverse proxy |
| `SECURE_HSTS_SECONDS` | Unset | Enable in production |
| `CSRF_COOKIE_SECURE` | Unset | Enable over HTTPS |
| `SESSION_COOKIE_SECURE` | Unset | Enable over HTTPS |
| `SECURE_CONTENT_TYPE_NOSNIFF` | Default | Provided by Django security middleware |
| `SECURE_BROWSER_XSS_FILTER` | Default | Provided by Django security middleware |
| `X_FRAME_OPTIONS` | `DENY` | Default Django setting |

### 9. CI/CD Security

- **Semgrep scan:** `.github/workflows/ci.yml` includes a Semgrep job that scans the Python codebase for vulnerabilities on every push
- **Planted-vulnerability fixtures:** `backend/tests/fixtures/sample_prs/` contains 6 fixture diffs with intentionally planted vulnerabilities — these serve as detection tests
- **Dependency scanning:** Recommended (not yet implemented): Dependabot or Snyk

---

## Secure Deployment Checklist

Before deploying to production:

- [ ] Generate a strong `DJANGO_SECRET_KEY` (`python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
- [ ] Set `DJANGO_DEBUG=False`
- [ ] Set `DJANGO_ALLOWED_HOSTS` to your domain(s)
- [ ] Generate a strong `WEBHOOK_SECRET` and configure it in the GitHub App settings
- [ ] Mount the GitHub App private key file (not env var) or use a secrets manager
- [ ] Use HTTPS (TLS termination at reverse proxy or platform-managed)
- [ ] Enable CSRF cookie secure flag
- [ ] Enable session cookie secure flag
- [ ] Set `SECURE_SSL_REDIRECT = True`
- [ ] Set `SECURE_HSTS_SECONDS = 31536000`
- [ ] Change PostgreSQL password from default
- [ ] Use a managed Redis or add Redis auth
- [ ] Set up database backups (e.g., `pg_dump` cron job or managed DB snapshots)
- [ ] Review GitHub App permissions == `contents: read` + `pull_requests: read/write` (no more)
- [x] Add log redaction for token/secret patterns — implemented via `sentinel_review/logging_filters.py`
- [ ] Enable rate limiting on `/webhooks/github` endpoint
- [ ] Consider adding Django admin IP whitelisting or VPN access

---

## Incident Response

### If the GitHub App private key is compromised:

1. Revoke the key in GitHub App settings → regenerate immediately
2. Rotate the `GITHUB_APP_PRIVATE_KEY_B64` environment variable
3. Review installation tokens — revoke all by reinstalling the app
4. Check GitHub audit log for unauthorized API calls

### If the LLM API key is compromised:

1. Revoke the key in Anthropic/OpenAI dashboard
2. Check API usage logs for unauthorized activity
3. Set spending limits on the API key

### If webhook secret is compromised:

1. Update `WEBHOOK_SECRET` in GitHub App settings and environment
2. The old secret becomes immediately invalid — any webhook with old signature is rejected
