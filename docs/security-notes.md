# Sentinel Review — Security Notes

> *Last updated: 2026-07-27 (post-remediation)*

---

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
  POST /webhooks/github  ← HMAC-protected, rate-limited (100/hr anon)
  GET/POST /api/*        ← Throttled (100/hr anon, 1000/hr auth)
  GET  /api/docs/        ← OpenAPI docs (read-only)
  GET  /metrics          ← Prometheus metrics (respects METRICS_ENABLED)
  GET  /health/          ← Liveness/readiness (no sensitive data)
  GET  /health/ready/
  GET  /                 ← Dashboard (no auth in MVP)
  GET  /admin/           ← Django admin (requires auth)

Internal (Docker network):
  Redis :6379            ← No auth (internal network)
  PostgreSQL :5432       ← Password auth
  Celery worker          ← Processes untrusted GitHub data
  Flower :5555           ← Basic-auth protected (FLOWER_USER/FLOWER_PASSWORD)
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
- **Production enforcement:** Empty `WEBHOOK_SECRET` raises `ImproperlyConfigured` at startup
- **Tested:** 10 unit tests + 1 E2E test cover valid, missing, tampered, malformed signatures

### 2. API Authentication

| Endpoint | Before Remediation | After Remediation |
|----------|-------------------|-------------------|
| `FeedbackViewSet` | `AllowAny` (unauthenticated writes) | `IsAuthenticated` |
| `StatsViewSet` | `AllowAny` (unauthenticated writes) | `IsAuthenticatedOrReadOnly` |

- **Rate limiting:** DRF throttle classes — 100 requests/hour for anonymous, 1000/hr for authenticated
- **Startup validation:** Missing `DJANGO_SECRET_KEY` or `WEBHOOK_SECRET` raises `ImproperlyConfigured`
- **OpenAPI schema:** Documented at `/api/schema/` + Swagger UI at `/api/docs/`

### 3. GitHub App Authentication

```
GitHub App Private Key (loaded from env/mounted file)
  → JWT (RS256, 10min expiry, 60s clock drift tolerance)
    → Installation Access Token (1hr, cached, auto-refreshed)
```

- **Private key lifecycle:**
  - NEVER committed to the repository
  - Loaded from `GITHUB_APP_PRIVATE_KEY_B64` env var OR mounted `.secrets/github-app-private-key.pem`
  - The `.secrets/` directory is gitignored
- **JWT:** Short-lived (10 minutes), never stored
- **Installation tokens:** Short-lived (1 hour), cached in memory only, never persisted to database

### 4. Least-Privilege GitHub App Permissions

| Permission | Access | Rationale |
|------------|--------|-----------|
| Repository contents | Read-only | Fetch diff, file contents, repo config |
| Pull requests | Read & Write | Read PR metadata, post inline review comments |
| Repository metadata | Read-only | Webhook delivery, repo info |

### 5. Secrets Management

| Secret | Storage | Source of Truth |
|--------|---------|-----------------|
| `DJANGO_SECRET_KEY` | Env var (required) | `.env` (local), CI secrets |
| `WEBHOOK_SECRET` | Env var (required) | `.env` (local), GitHub App config |
| `GITHUB_APP_PRIVATE_KEY_B64` | Env var | Base64-encoded, copied manually |
| `ANTHROPIC_API_KEY` | Env var | Anthropic Console |
| `OPENAI_API_KEY` | Env var | OpenAI Platform |
| Postgres password | Env var | `.env` (local), Docker Compose default |

**Startup enforcement:** If `DJANGO_SECRET_KEY` or `WEBHOOK_SECRET` are unset and
`DJANGO_DEBUG` is `False`, Django will raise `ImproperlyConfigured` and refuse to start.

### 6. Log Redaction

All log output passes through `sentinel_review.logging_filters.RedactingFilter`.
This filter redacts the following patterns:

| Pattern | Example | Status |
|---------|---------|--------|
| Anthropic API keys | `sk-ant-...` | ✅ |
| OpenAI API keys | `sk-...` (20+ chars) | ✅ |
| RSA/DSA private keys | `-----BEGIN PRIVATE KEY-----` | ✅ |
| GitHub tokens | `ghp_...`, `ghs_...`, `gho_...`, `ghu_...`, `ghb_...`, `ghv_...` | ✅ |
| Bearer tokens in headers | `Bearer eyJ...` | ✅ |
| Password/secret assignments | `PASSWORD=supersecret`, `API_KEY=abc123...` | ✅ |
| JWT tokens | `eyJ...` (three base64url segments) | ✅ |
| DB connection strings | `postgres://user:pass@host/db` | ✅ |

**Fixed in remediation:** The previous `[a-fA-F0-9]{40,}` pattern falsely matched
40-character git commit SHAs. This was removed to avoid false redactions.

### 7. Private Repository Opt-In

- **Default behavior:** Private repositories are **skipped** during review
- **Opt-in mechanism:** Dashboard toggle or API endpoint sets `repo.config.private_repo_opt_in = True`
- **Enforcement:** Check is in `UpsertStage` of the pipeline, not an LLM prompt instruction
- **Audit trail:** Each skipped review creates a Review record with `status=skipped`

### 8. Django Security Settings

| Setting | Value | Notes |
|---------|-------|-------|
| `SECURE_SSL_REDIRECT` | Unset | Enable in production behind reverse proxy |
| `SECURE_HSTS_SECONDS` | Unset | Enable in production |
| `CSRF_COOKIE_SECURE` | Unset | Enable over HTTPS |
| `SESSION_COOKIE_SECURE` | Unset | Enable over HTTPS |
| `SECURE_CONTENT_TYPE_NOSNIFF` | Default | Django security middleware |
| `SECURE_BROWSER_XSS_FILTER` | Default | Django security middleware |
| `X_FRAME_OPTIONS` | `DENY` | Default Django setting |

### 9. CI/CD Security

- **Ruff lint:** Run on every push — catches unsafe patterns before they reach production
- **Semgrep scan:** `.github/workflows/ci.yml` includes a pinned Semgrep job scanning the Python codebase
- **Dependency scanning:** Recommended: Dependabot or Snyk (not yet implemented)

---

## Remediation Audit: Security Fixes

| Issue | Severity | Fix |
|-------|:--------:|-----|
| `AllowAny` on FeedbackViewSet (open write) | Critical | Changed to `IsAuthenticated` |
| `AllowAny` on StatsViewSet (open write) | High | Changed to `IsAuthenticatedOrReadOnly` |
| Insecure fallback defaults | Critical | `ImproperlyConfigured` at startup |
| Webhook returns True when secret unset | High | Returns `False` (rejects) |
| No rate limiting | Medium | DRF throttle classes (100/1000/hr) |
| Log redaction matches git SHAs | Low | Removed false-positive hex pattern |
| No CSP | Low | Not implemented (CDN scripts need hashes) |
| No CSRF on webhook | Informational | WAI — `@csrf_exempt` by design (HMAC is the auth mechanism) |

---

## Secure Deployment Checklist

- [x] Log redaction for token/secret patterns
- [x] HMAC webhook verification (constant-time)
- [x] API authentication on write endpoints
- [x] Rate limiting on API/webhook endpoints
- [x] Startup validation of required secrets
- [x] Health check endpoints for load balancers
- [x] Basic auth on Flower dashboard
- [ ] Generate strong `DJANGO_SECRET_KEY` for production
- [ ] Set `DJANGO_DEBUG=False`
- [ ] Set `DJANGO_ALLOWED_HOSTS` to your domain(s)
- [ ] Use HTTPS (TLS termination at reverse proxy or platform-managed)
- [ ] Enable CSRF cookie secure flag
- [ ] Enable session cookie secure flag
- [ ] Set `SECURE_SSL_REDIRECT = True`
- [ ] Set `SECURE_HSTS_SECONDS = 31536000`
- [ ] Change PostgreSQL password from default
- [ ] Use a managed Redis or add Redis auth
- [ ] Set up database backups

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
