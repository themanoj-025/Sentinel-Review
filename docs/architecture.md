# Sentinel Review — Architecture

> *Last updated: 2026-07-27 (post-full-remediation, P0-P3 complete)*

## Overview

Sentinel Review is an autonomous GitHub PR-review agent. It monitors pull request events via webhooks, fetches diffs with full repo context, analyzes changes using a combination of LLM-based reasoning and static analysis (Semgrep), and posts severity-ranked, line-anchored inline review comments.

### Architecture at a Glance

```ascii
                GitHub (PR + reaction events)
                          │
                    webhook (HMAC-SHA256 signed)
                          │
               ┌──────────▼──────────┐
               │  Django Webhook View │
               │  POST /webhooks/github│
               │  • Verify HMAC        │
               │  • Idempotency check  │
               │  • Route by event     │
               │  • Enqueue Celery     │
               │  • Return 202 (<10s)  │
               └──────────┬───────────┘
                          │ review_pull_request.delay()
                          ▼
               ┌─────────────────────┐
               │       Redis         │
               │  • Celery broker    │
               │  • Result backend   │
               │  • LLM response     │
               │    cache            │
               │  • Delivery dedup   │
               └──────────┬──────────┘
                          │
               ┌──────────▼──────────┐
               │   Celery Worker      │
               │                      │
               │  ┌────────────────┐  │
               │  │ ReviewPipeline  │  │
               │  │                │  │
               │  │ 1. UpsertStage  │  │
               │  │ 2. FetchDiffStg │  │
               │  │ 3. FetchCtxStg  │  │
               │  │ 4. LLMReviewStg │  │
               │  │    ├─ cache hit │  │
               │  │    └─ cache miss│  │
               │  │ 5. SemgrepStg   │  │
               │  │ 6. DedupeStg    │  │
               │  │ 7. PostComments │  │
               │  └────────────────┘  │
               │                      │
               │  ReviewContext ctx    │
               │  (typed dataclass)    │
               └──────────┬───────────┘
                          │
        ┌─────────────────┼──────────────────┐
        │                 │                  │
        ▼                 ▼                  ▼
  ┌────────────┐  ┌──────────────┐  ┌──────────────┐
  │ GitHub API │  │ LLM Provider │  │ PostgreSQL   │
  │ (circuit   │  │ (circuit     │  │ • 6 models   │
  │  breaker)  │  │  breaker)    │  │ • composite  │
  └────────────┘  └──────────────┘  │   indexes    │
                                    └──────┬───────┘
                                           │
                                           ▼
                                 ┌──────────────────┐
                                 │  Django Dashboard│
                                 │  + HTMX + Alpine │
                                 │  + Chart.js      │
                                 │  + Tailwind CSS  │
                                 │  (compiled build)│
                                 └──────────────────┘
```

## Service Topology (Docker Compose)

| Service | Image | Purpose | Port | Healthcheck |
|---------|-------|---------|------|-------------|
| `web` | Custom (Django + gunicorn) | HTTP: webhooks, API, dashboard, health, metrics | `8000` | `GET /health/` |
| `worker` | Custom (Celery) | Background PR review + feedback processing | — | Celery ping |
| `redis` | `redis:7-alpine` | Celery broker + result backend + LLM cache | `6379` | `redis-cli ping` |
| `db` | `postgres:16-alpine` | Primary database | `5432` | `pg_isready` |
| `flower` | `mher/flower:2.0` | Celery monitoring (basic-auth required) | `5555` | — |

## Component Architecture

### 1. Webhook Layer (`sentinel_review/webhooks/`)

```
POST /webhooks/github
  → HMAC-SHA256 signature verification (constant-time, required)
  → Idempotency check — same delivery_id? → 200 OK (skip)
  → Route by X-GitHub-Event header
    ├── pull_request (opened|synchronize) → enqueue review_pull_request
    ├── pull_request_review_comment → enqueue process_reaction
    └── other → 200 OK (ignored)
```

**Key design decisions:**
- HMAC verification + idempotency check before any other processing
- Missing `WEBHOOK_SECRET` in production raises `ImproperlyConfigured` at startup
- Response returns immediately (202 / 200) — heavy work deferred to Celery

### 2. Celery Workers (`sentinel_review/workers/`)

#### Staged Pipeline Architecture

The core `review_pull_request` task is a thin orchestrator that delegates to 7 named stages, each independently testable:

```python
class ReviewPipeline:
    stages = [
        UpsertStage(),         # DB records + private repo check
        FetchDiffStage(),      # GitHub diff + file contents
        FetchContextStage(),   # Repo metadata + .sentinel-ignore (non-fatal)
        LLMReviewStage(),      # Cache check → LLM call → cache store
        SemgrepStage(),        # Static analysis (non-fatal)
        DedupeStage(),         # Merge, .sentinel-ignore filtering, dedup, limit
        PostCommentsStage(),   # Post inline comments + save to DB + cache
    ]
```

Each stage receives and returns a typed `ReviewContext` dataclass containing:
- `installation_id`, `repo_id`, `repo_full_name`, `pr_number`
- `diff`, `repo_context`, `file_contents`
- `llm_findings`, `semgrep_findings`, `merged_findings`
- Latency tracking per stage

A safety net catches any `Exception` at the pipeline boundary to mark the review as `FAILED`.

#### `process_reaction` (queue: `feedback`)

1. Look up Comment by `github_comment_id`
2. Fetch reactions from GitHub API
3. Store 👍/👎 as Feedback records (deduplicated by `(comment, reactor_login, reaction)`)

### 3. LLM Provider (`sentinel_review/workers/llm.py`)

Abstract interface with two implementations:

| Provider | Model | Auth | Structured Output |
|----------|-------|------|-------------------|
| `AnthropicProvider` | `claude-sonnet-4-20250514` (configurable) | `ANTHROPIC_API_KEY` | Tool-use mode (built-in JSON schema) |
| `OpenAIProvider` | `gpt-4o` (configurable) | `OPENAI_API_KEY` | `response_format: json_schema` |

**Circuit breaker:** Both providers are wrapped in a `CircuitBreaker` (CLOSED/OPEN/HALF_OPEN states). After 3 failures in a 60s window, the circuit opens and all requests fail fast for 120s before attempting recovery.

**Corrective retry:** On Pydantic `ValidationError`, the model is called once more with the validation error shown, before giving up.

### 4. LLM Response Cache (`sentinel_review/workers/cache.py`)

- **Key:** `SHA256(diff_content + repo_context)` hex digest
- **Backend:** Redis (primary) + in-memory dict (fallback)
- **TTL:** 3600 seconds (configurable)
- **Hit/miss metrics:** Exported to Prometheus as `llm_cache_hits` / `llm_cache_misses`
- **Effect:** Repeated `synchronize` events on identical diff resolve in <1ms vs ~2s

### 5. GitHub Client (`sentinel_review/workers/github_client.py`)

Authentication flow:

```
GitHub App Private Key (PEM)
  → JWT (RS256, 10min expiry, 60s clock drift tolerance)
    → Installation Access Token (1hr, cached and auto-refreshed)
      → Authenticated GitHub API calls (circuit breaker protected)
```

**Performance:** Single long-lived `httpx.Client()` reused across all requests.

### 6. Circuit Breaker (`sentinel_review/workers/circuit_breaker.py`)

```python
class CircuitBreaker:
    states: CLOSED → OPEN → HALF_OPEN → CLOSED
    
    CLOSED:     Normal operation, requests pass through
    OPEN:       Failures > threshold (3), fail fast for cooldown (120s)
    HALF_OPEN:  After cooldown, allow probe request
                - Success → CLOSED
                - Failure → OPEN (reset cooldown)
```

Wired into `GitHubClient` and both LLM providers.

### 7. Django Dashboard (`sentinel_review/dashboard/`)

Python-rendered templates with HTMX + Alpine.js:

| Route | View | Description |
|-------|------|-------------|
| `/` | `dashboard_home` | Overview stats, recent reviews, status distribution |
| `/repos/` | `repo_list` | Searchable repository list with review/comment counts |
| `/repos/{id}/` | `repo_detail` | Config panel (HTMX), review history, per-repo stats |
| `/reviews/{id}/` | `review_detail` | All comments from a review run with upvote/downvote counts |
| `/stats/` | `stats_overview` | Usefulness rate, latency, category volume, per-repo breakdown — with Chart.js visualizations |

**Frontend improvements (post-remediation):**
- Tailwind CSS via compiled build (no CDN)
- `hx-indicator` loading states on all HTMX triggers
- CDN fallback handlers for Alpine.js and Chart.js
- Fixed `TemplateSyntaxError` in stats page

### 8. Database Schema (PostgreSQL)

```
Installation (1) ──→ (N) Repo (1) ──→ (N) PullRequest (1) ──→ (N) Review (1) ──→ (N) Comment (1) ──→ (N) Feedback
```

**Composite indexes:**
- `Comment(review, category)` — fast category-filtered queries
- `Comment(review, severity)` — fast severity-filtered queries
- `Feedback(comment, reaction)` — fast reaction aggregation

**Unique constraints:**
- `(installation, github_repo_id)` for Repo
- `(repo, github_pr_number)` for PullRequest
- `(comment, reactor_login, reaction)` for Feedback

### 9. Health & Observability

| Endpoint | Type | Checks | Purpose |
|----------|------|--------|---------|
| `GET /health/` | Liveness | Always returns 200 | Load balancer / Docker healthcheck |
| `GET /health/ready/` | Readiness | DB connectivity + Redis ping | Orchestrator readiness gate |
| `GET /metrics` | Metrics | Prometheus text format | review_latency, llm_errors, queue_depth, cache_rate, token_cost |

### 10. API Layer (`sentinel_review/api/`)

| Endpoint | Method | Auth | Paginated | Filtered |
|----------|--------|------|:---------:|:--------:|
| `/api/v1/installations/` | GET | Read-only | ✅ | ✅ search |
| `/api/v1/repos/` | GET | Read-only | ✅ | ✅ search |
| `/api/v1/repos/{id}/config/` | PATCH | Authenticated | — | — |
| `/api/v1/pull-requests/` | GET | Read-only | ✅ | ✅ repo_id |
| `/api/v1/reviews/` | GET | Read-only | ✅ | ✅ pull_request_id, status |
| `/api/v1/comments/` | GET | Read-only | ✅ | ✅ review_id, category, severity |
| `/api/v1/feedback/` | POST | IsAuthenticated | — | — |
| `/api/v1/stats/` | GET | IsAuthenticatedOrReadOnly | — | ✅ repo |

**Rate limiting:** 100 req/hr (anon), 1000 req/hr (auth)
**Pagination:** 50 items/page (default)
**OpenAPI schema:** `/api/schema/` + Swagger UI at `/api/docs/`

### 11. GHA Execution Mode (Alternative Deployment)

In addition to the webhook-based model, Sentinel Review can run as a **GitHub Actions composite action**:

```yaml
steps:
  - uses: sentinel-review/sentinel-review/.github/actions/sentinel-review@main
    with:
      github-token: ${{ github.token }}
      anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

This mode bypasses Django/Celery/Redis entirely — it reads the PR event from `GITHUB_EVENT_PATH`, runs `git diff` directly, calls the LLM, and posts inline comments via `GITHUB_TOKEN`. See `.github/actions/sentinel-review/action.yml`.

### 12. .sentinel-ignore Support

Repositories can include a `.sentinel-ignore` file (glob patterns, one per line) to exclude files from review:

```
# Ignore generated files
*.generated.py
build/
vendor/
```

The ignore rules are parsed in `FetchContextStage` (webhook mode) or read from disk (GHA mode), then applied in `DedupeStage`.

## Data Flow — A Review in 14 Steps

```
 1.  🔔 GitHub sends POST /webhooks/github (pull_request opened/synchronize)
 2.  🔐 HMAC-SHA256 signature verified (constant-time)
 3.  🔁 Idempotency check — same delivery_id? → 200 OK (skip)
 4.  📤 Enqueue review_pull_request.delay() → Redis "reviews" queue
 5.  ✅ Return 202 Accepted (< 10s)
 6.  ⚙️ Worker pops task from Redis
 7.  💾 UpsertStage — DB records: Installation → Repo → PR → Review (status: PROCESSING)
 8.  🔒 Private repo check — skip if not opted in
 9.  📡 FetchDiffStage — diff + file contents via GitHub API (circuit breaker protected)
10.  📚 FetchContextStage — repo conventions, .sentinel-ignore, linter configs (non-fatal)
11.  🧠 LLMReviewStage — cache check → hit (skip) / miss (call LLM with retry → store)
12.  🔬 SemgrepStage — static analysis, merged with LLM findings (non-fatal)
13.  🧹 DedupeStage — merge, .sentinel-ignore filter, dedup by (file, line, category), limit
14.  📝 PostCommentsStage — inline comments via GitHub API, save to DB, cache LLM result
```

## Security Architecture

See `security-notes.md` for full details.

- **Webhook**: HMAC-SHA256 with constant-time comparison; production fails to start if unset
- **API auth**: `IsAuthenticated` on writes, `IsAuthenticatedOrReadOnly` on sensitive reads
- **Rate limiting**: 100 req/hr anon, 1000 req/hr auth (DRF throttle classes)
- **GitHub App**: JWT → short-lived installation tokens, never persisted
- **Circuit breaker**: Prevents thundering-herd retries during outages
- **Log redaction**: 9 regex patterns, no false-positive SHA matching
- **Startup validation**: `ImproperlyConfigured` if required secrets are unset in production

## Testing Strategy

| Layer | Tool | Scope |
|-------|------|-------|
| Unit | pytest + pytest-django | Models, schemas, helpers, HMAC, cache, circuit breaker |
| Integration | pytest + respx + unittest.mock | GitHub API, webhooks, Celery tasks |
| E2E | pytest + mocked GitHub + mocked LLM | Full webhook→Celery→DB pipeline |
| CI | GitHub Actions | Ruff lint, pytest (PostgreSQL), Docker build, Semgrep |

### Test Coverage by Area

| Area | Tests | File |
|------|:-----:|------|
| HMAC verification | 10 | `test_signature.py` |
| Pydantic validation | 22 | `test_schemas.py` |
| GitHub client | 11 | `test_github_client.py` |
| LLM provider | 13 | `test_llm.py` |
| Semgrep integration | 12 | `test_semgrep.py` |
| Webhook views | 9 | `test_webhook.py` |
| Model schema + constraints | 27 | `test_models.py` |
| Pipeline stages | 21 | `test_review_worker.py` |
| Feedback loop | 5 | `test_feedback.py` |
| LLM response cache | 19 | `test_cache.py` |
| End-to-end pipeline | 6 | `test_e2e.py` |
| Startup validation | 4 | `test_startup.py` |
| Ignore rules | 26 | `test_ignore_rules.py` |
| Circuit breaker | 15 | `test_circuit_breaker.py` |
| JSON logging | 8 | `test_logging.py` |
| Health endpoints | 8 | `test_health.py` |
| GHA runner | 18 | `test_gha_review.py` |
| Metrics | 4 | `test_metrics.py` |
| **Total** | **237** | |

## Configuration

All configuration via environment variables (see `.env.example`):

| Variable | Required | Default | Purpose |
|----------|:--------:|---------|---------|
| `DJANGO_SECRET_KEY` | Yes | — | Django cryptographic signing (startup fails if unset) |
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `CELERY_BROKER_URL` | Yes | — | Redis URL for Celery |
| `GITHUB_APP_ID` | Yes | — | GitHub App ID |
| `GITHUB_APP_PRIVATE_KEY_B64` | Yes* | — | Base64-encoded private key |
| `WEBHOOK_SECRET` | Yes | — | GitHub webhook secret (startup fails if unset) |
| `LLM_PROVIDER` | No | `anthropic` | LLM backend selection |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `JSON_LOG` | No | `False` | Enable structured JSON logging |
| `SENTRY_DSN` | No | — | Sentry DSN for error tracking |
| `METRICS_ENABLED` | No | `False` | Enable Prometheus `/metrics` endpoint |
| `FLOWER_USER` | No | — | Flower dashboard username (basic auth) |
| `FLOWER_PASSWORD` | No | — | Flower dashboard password (basic auth) |

*\*At least one set of credentials is required (GitHub + LLM provider).*
