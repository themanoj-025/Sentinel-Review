# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Staged pipeline architecture with 7 independently testable stages (`UpsertStage`,
  `FetchDiffStage`, `FetchContextStage`, `LLMReviewStage`, `SemgrepStage`,
  `DedupeStage`, `PostCommentsStage`) and typed `ReviewContext` dataclass
- LLM response cache (SHA256 diff-hash keyed) with Redis backend + in-memory
  fallback, reducing re-review of unchanged diffs from ~2s to <1ms
- End-to-end integration test (`test_e2e.py`) — 6 tests covering the full
  webhook→Celery→mocked-GitHub→mocked-LLM→comment-creation pipeline
- DRF pagination (50/page), `SearchFilter`, and `OrderingFilter` on all list
  endpoints for standardized filtering
- Health check endpoints: `GET /health/` (liveness) and `GET /health/ready/`
  (readiness — verifies DB and Redis connectivity)
- DRF throttle classes: `AnonRateThrottle` (100/hr) and `UserRateThrottle` (1000/hr)
- Circuit breaker for GitHub API and LLM provider calls (CLOSED/OPEN/HALF_OPEN
  states with configurable thresholds and recovery timeouts)
- Structured JSON logging via `JSONFormatter` (controlled by `JSON_LOG` env var)
- Sentry integration (conditional on `SENTRY_DSN` env var)
- Prometheus `/metrics` endpoint with `review_latency`, `reviews_total`,
  `llm_errors`, `token_cost`, `llm_cache_hits`, `llm_cache_misses` metrics
- OpenAPI schema generation via `drf-spectacular` at `/api/schema/` with Swagger
  UI at `/api/docs/`
- `CHANGELOG.md` and `CODEOWNERS` files
- Composite indexes on `Comment(review, category)`, `Comment(review, severity)`,
  and `Feedback(comment, reaction)`
- `hx-indicator` loading states on all HTMX-triggering elements
- CDN script fallback handlers for Alpine.js and Chart.js

### Changed
- **Security**: `FeedbackViewSet` now requires `IsAuthenticated`; `StatsViewSet`
  uses `IsAuthenticatedOrReadOnly` (was `AllowAny` on both)
- **Security**: `SECRET_KEY`, `DEBUG`, and `WEBHOOK_SECRET` now raise
  `ImproperlyConfigured` at startup if unset in production (no more insecure fallbacks)
- **Security**: Webhook signature verification returns `False` (not `True`) when
  secret is unset
- **Pipeline**: `review_pull_request` refactored from 250-line monolith to thin
  orchestration delegating to 7 named pipeline stages
- **Exception handling**: All blanket `except Exception` replaced with specific
  exception types; single safety net only at outermost pipeline boundary
- **GitHub client**: Reuses a single `httpx.Client` instance instead of creating
  one per request
- **Logging**: Switched from f-string logging to lazy `%s` formatting throughout
- **LLM calls**: Added corrective retry on Pydantic `ValidationError` (one retry
  with error message shown to the model before giving up)
- **Webhook idempotency**: Duplicate deliveries deduplicated by
  `(repo_id, pr_number, github_delivery_id)` before enqueueing
- **Dependencies**: Cleaned `requirements.txt` (removed duplicates, unused packages);
  moved `ipython`/`django-extensions` to `requirements-dev.txt`
- **CI**: Pinned `semgrep/semgrep-action` to exact commit SHA
- **Migration**: Consolidated to single `0001_initial.py` with all indexes
- **Frontend**: Tailwind loaded via compiled CSS (no CDN); fixed `TemplateSyntaxError`
  in `stats.html`
- **Log redaction**: Removed `[a-fA-F0-9]{40,}` pattern that falsely matched git SHAs
- **Flower**: Added `--basic-auth` with `FLOWER_USER`/`FLOWER_PASSWORD` env vars
- **Metrics**: Wired previously-dead `METRICS_ENABLED` flag to real `/metrics` endpoint

### Fixed
- `AllowAny` permission on `FeedbackViewSet` and `StatsViewSet` (open forgery vector)
- `TemplateSyntaxError` in `stats.html` (`{% with ratio=...%}` invalid syntax)
- Missing composite indexes causing N+1 queries on `(review, category)` and `(comment, reaction)`
- Log redaction regex catching git SHAs (40-char hex pattern)
- Webhook returning `True` when secret is unset
- Duplicate `httpx` entry in requirements
- Unused `responses` and `python-dotenv` in requirements
- Celery result backend (Redis) growing unbounded
- Dashboard/API duplicated query logic (now centralized via pipeline stages)
- `httpx.Client()` instantiated per request instead of reused

### Removed
- `ipython` and `django-extensions` from production requirements
- Unused `responses` and `python-dotenv` from requirements
- Tailwind CDN script (replaced with compiled CSS build)
- `0002_update_indexes.py` migration (consolidated into `0001_initial.py`)

## [0.1.0] — 2026-07-27

### Added
- Initial release with core PR review pipeline
- GitHub App webhook integration with HMAC-SHA256 verification
- LLM provider abstraction (Anthropic Claude + OpenAI GPT-4o)
- Semgrep static analysis integration
- 6 Django models: Installation, Repo, PullRequest, Review, Comment, Feedback
- Django REST Framework API (7 endpoints)
- Django dashboard (5 pages with HTMX + Alpine.js)
- Feedback loop with 👍/👎 reaction capture
- Compilation dashboard with usefulness rate tracking
- Chart.js visualizations on `/stats/` page
- Self-review demo (`docs/demo/`)
- Docker Compose deployment (5 services)
- CI pipeline (Ruff lint → pytest → Docker build → Semgrep)
- 157 unit/integration tests
- Render.com and Fly.io deployment configs
