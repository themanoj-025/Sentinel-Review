# Sentinel Review — Build Log

> *Chronological record of development, decisions, and blockers.*

---

## Phase 0 — Project Scaffolding

### 2026-07-27 — Repository Setup

- Initialized Django project `sentinel_review` with `django-admin startproject`
- Created sub-packages: `models/`, `webhooks/`, `workers/`, `dashboard/`, `api/`
- Set up `docker-compose.yml` with 5 services: `web`, `worker`, `redis`, `db`, `flower`
- Created `Dockerfile` (Python 3.12-slim) with gunicorn
- Created `.env.example` with all required environment variables documented
- Wrote `requirements.txt` with pinned dependency ranges

**Key decisions:**
- Django 5.x + DRF over FastAPI (batteries-included, admin panel, fewer moving parts)
- Celery + Redis over arq (mature ecosystem, monitoring with Flower)
- SQLite for dev, PostgreSQL for production/Ci

---

## Phase 1 — Data Models

### 2026-07-27 — Database Schema

Implemented all 6 Django models matching the spec:

- `Installation`: GitHub App installation (unique by `github_installation_id`)
- `Repo`: Repository with `config` JSONField (categories, opt-in, max_comments)
- `PullRequest`: Unique constraint on `(repo, github_pr_number)`
- `Review`: Status tracking (queued → processing → completed/failed), latency/token tracking
- `Comment`: Category + severity enum, file_path + line_number, nullable github_comment_id
- `Feedback`: Unique constraint on `(comment, reactor_login, reaction)`

**NOTES:**
- Used explicit `app_label = "models"` in Meta classes (later removed in favor of AppConfig)
- `db_table` names are lowercase without app prefix (cleaner)

---

## Phase 2 — Core Pipeline

### 2026-07-27 — GitHub Integration

- Implemented `GitHubClient` with JWT → installation token authentication
- Token caching with auto-refresh before expiry
- Methods: `get_diff`, `get_file_content`, `get_repo_context`, `post_review`, `get_comment_reactions`
- Context gathering: detects `CONTRIBUTING.md`, linter configs (`.eslintrc`, `pyproject.toml`, etc.)

### 2026-07-27 — Webhook Receiver

- `POST /webhooks/github` with HMAC-SHA256 verification
- Routes `pull_request` (opened/synchronize) → enqueue review
- Routes `pull_request_review_comment` → enqueue feedback processing
- Returns 202 within 10s GitHub timeout
- Constant-time comparison via `hmac.compare_digest()`

### 2026-07-27 — LLM Integration

- Abstract `LLMProvider` interface with `AnthropicProvider` and `OpenAIProvider`
- Pydantic schemas: `Finding` (file_path, line_number, category, severity, comment, suggested_fix) and `ReviewOutput`
- System prompt with senior-engineer persona, strict rules, few-shot examples
- Validation-first architecture: LLM output is validated by Pydantic before any use
- Retry-on-failure with error-correction prompt

### 2026-07-27 — Semgrep Integration

- `run_semgrep()` writes files to temp dir, runs Semgrep CLI, parses JSON output
- Severity mapping: ERROR → blocking, WARNING → warning, INFO → nit
- `merge_with_llm_findings()` cross-references LLM + Semgrep results
- Agreement = high confidence (source: "llm+semgrep")
- Non-fatal: if Semgrep is not installed, worker continues without it

### 2026-07-27 — Review Worker

- `review_pull_request` Celery task: the full pipeline
- Private repo opt-in check before any data processing
- Deduplication by `(file_path, line_number, category)`
- Config-driven filtering: only enabled categories are posted
- Max-comment limit from repo config
- Posts summary + inline comments via GitHub "create review" API

---

## Phase 3 — Dashboard & API

### 2026-07-27 — Django REST Framework API

- Read-only view sets for Installations, Repos, PullRequests, Reviews, Comments
- Config update endpoint (`PATCH /api/repos/{id}/config/`)
- Feedback write endpoint for manual feedback
- Stats endpoint exposing `compute_usefulness_rate()`

### 2026-07-27 — Server-Rendered Dashboard

- 5 pages: home, repo list, repo detail (with HTMX config), review detail, stats
- Django Templates + HTMX for partial updates (search results, config save)
- Alpine.js for UI chrome (toggle panels)
- Chart.js `<script>` tag for charts on stats page (only JS library)
- Django admin configured with custom list_display, search, filters

### 2026-07-27 — Feedback Loop

- `process_reaction` Celery task fetches 👍/👎 reactions from GitHub API
- `compute_usefulness_rate()` aggregates per repo and per category
- Dashboard displays overall rate and breakdown
- Feedback deduplication via `get_or_create`

---

## Phase 4 — Testing & CI

### 2026-07-27 — Test Infrastructure

- Set up `pytest.ini` with Django settings configuration
- Root `conftest.py` with environment setup
- Test conftest with shared fixtures (sample data, model fixtures)
- Lazy model imports to avoid `AppRegistryNotReady`

### 2026-07-27 — Unit Tests (157 tests)

| File | Tests | Purpose |
|------|-------|---------|
| `test_signature.py` | 10 | HMAC verification (valid, missing, tampered, dev mode, constant-time) |
| `test_schemas.py` | 22 | Pydantic validation, JSON parsing, few-shot examples, system prompt |
| `test_github_client.py` | 11 | JWT auth, diff fetching, file content, repo context, review posting |
| `test_llm.py` | 13 | Provider abstraction, prompt building, JSON validation |
| `test_semgrep.py` | 12 | Output parsing, severity mapping, merge logic |
| `test_webhook.py` | 9 | Signature rejection, event routing, Celery enqueueing |
| `test_models.py` | 27 | Schema round-trip, unique constraints, FK cascades, usefulness rate |
| `test_review_worker.py` | 21 | Diff parsing, dedup, pipeline with mocks, error handling |
| `test_feedback.py` | 5 | Reaction capture, dedup, error handling |

### 2026-07-27 — Planted-Bug Fixtures (6 fixtures, 9 known issues)

| Fixture | Description |
|---------|-------------|
| `sql_injection` | Two SQL injection vulnerabilities |
| `hardcoded_secret` | Three hardcoded secrets (API key, password, SECRET_KEY) |
| `unsafe_deserialization` | `pickle.loads` on untrusted data |
| `off_by_one` | IndexError + potential None access |
| `clean` | Variable rename — zero issues (false positive check) |
| `missing_test` | Missing zero-division guard |

### 2026-07-27 — CI Workflow

`.github/workflows/ci.yml` with 4 jobs:
1. **test:** Ruff lint + pytest with PostgreSQL + coverage
2. **docker-build:** Build Docker image and verify
3. **semgrep:** Scan codebase for vulnerabilities
4. **docker-compose:** Start all services and verify health

---

## Phase 5 — Documentation

### 2026-07-27 — Architecture & Decisions

- `docs/architecture.md`: System architecture, component diagram, data flow
- `docs/decisions.md`: 12 ADRs covering all major architectural choices
- `docs/security-notes.md`: Threat model, controls, deployment checklist
- `docs/evaluation-report.md`: Test results, fixture set, metric definitions
- `docs/build-log.md`: This file — chronological development record

### Infrastructure Fixes

- Created `sentinel_review/apps.py` with `SentinelReviewConfig` (resolved `AppRegistryNotReady` in tests)
- Changed `INSTALLED_APPS` from `"sentinel_review.models"` to `"sentinel_review.apps.SentinelReviewConfig"`
- Removed explicit `app_label` from all 6 model Meta classes

---

## Phase 6 — Polish & Production Readiness

### 2026-07-27 — Data Acquisition Pipeline

- Created `scripts/build_eval_set.py` — a comprehensive data-acquisition script with 3 sources:
  - Microsoft CodeReviewer dataset (Zenodo API auto-discovery, zip extraction, JSONL parsing)
  - Live GitHub PRs (Search API, diff fetching, review comment extraction, meaningful-review filtering)
  - Planted-bug fixtures (import from `backend/tests/fixtures/sample_prs/`)
- CLI options: `--sources`, `--max-github-prs`, `--max-codereviewer`, `--force`, `--dry-run`
- Rate-limit aware: aborts gracefully when unauthenticated instead of hanging 60 minutes
- Reproducible: `random.seed(42)` for consistent subsampling
- Created `data/.gitkeep` placeholder for the (gitignored) data cache directory

### 2026-07-27 — Self-Review Demo

- Planted a deliberately vulnerable function (`_load_cached_evaluation_results` with `pickle.load()`) in `scripts/build_eval_set.py` — CWE-502
- Created `docs/demo/README.md` documenting the full self-review pipeline (7 steps: webhook → worker → LLM → Semgrep → merge → post → persist)
- Created `docs/demo/sample_pr_diff.diff` standalone reference copy
- The self-review demo shows LLM + Semgrep agreement → high-confidence finding

### 2026-07-27 — Chart.js Integration on Stats Page

- Rewrote `dashboard/templates/dashboard/stats.html` with 4 real Chart.js charts:
  - **Usefulness Rate by Category** (bar chart with per-category colors)
  - **Comment Volume by Category** (doughnut chart with percentage tooltips)
  - **Reviews Over Time** (filled line chart, last 7 days)
  - **Upvotes vs Downvotes** (stacked bar chart per category)
- Server-side JSON serialization via `json.dumps()` (Django templates don't auto-serialize)
- Empty-state handling with `|| []` fallbacks in all 4 chart renderers
- Alpine.js `x-data`/`x-init` for chart lifecycle management

### 2026-07-27 — Log Redaction

- Created `sentinel_review/logging_filters.py` with `RedactingFilter` — a `logging.Filter` subclass
- 9 regex patterns covering: Anthropic keys, OpenAI keys, private key PEM blocks, GitHub tokens, Bearer tokens, password/secret assignments, JWT tokens, long hex strings, DB connection strings
- Integrated into `settings.py` LOGGING config as a handler-level filter on `console` handler
- Updated `docs/security-notes.md` to reflect implementation (removed "not yet implemented" note)

### 2026-07-27 — Deployment Configs

- Created `render.yaml` — Render.com Blueprint with:
  - `web` service (starter plan, gunicorn, auto-HTTPS)
  - `worker` service (Celery, 2 queues, 2 workers)
  - PostgreSQL 16 database (starter plan)
  - Redis instance (starter plan)
- Created `fly.toml` — Fly.io config with:
  - `[http_service]` for web (1 CPU, 512MB, auto-HTTPS)
  - `[[processes]]` for worker (1 CPU, 256MB)
  - `release_command` = `python manage.py migrate --noinput`
  - Secrets via `fly secrets set`

### 2026-07-27 — Dead Code Cleanup

- Removed 4 unused imports identified by `ruff check --select F401`:
  - `rest_framework.status` from `api/views.py`
  - `rest_framework.permissions.IsAuthenticated` from `api/views.py`
  - `sentinel_review.models.feedback.Feedback` from `dashboard/views.py`
  - `django.http.JsonResponse` from `webhooks/views.py`
- Removed empty `backend/sentinel_review/tests/` directory (duplicate of `backend/tests/`)
- All 157 tests continue to pass after cleanup

---

## Remaining Work

### Human Checkpoints (requires user action)

1. **GitHub App registration:** Needs a human in a browser to create the GitHub App, copy App ID/Client ID/secret and private key. A manifest JSON can be pre-generated for one-click setup.
2. **LLM API key:** Needs Anthropic (or OpenAI) API key supplied by the user.
3. **Deployment:** Docker Compose is ready. For public URL (needed for GitHub webhooks), deploy to Render/Fly.io or use `ngrok` for local testing. Deployment configs (`render.yaml`, `fly.toml`) are ready.

### Future Improvements

- [x] `scripts/build_eval_set.py` — automated data-acquisition pipeline
- [ ] `scripts/run_evaluation.py` — evaluation runner that produces precision/recall numbers
- [ ] Live evaluation report with real LLM calls
- [x] Self-review demo: planted bug and docs/demo/README.md created
- [x] Chart.js integration on `/stats/` page
- [ ] CI badge in README (after first CI run on default branch)
- [ ] Rate limiting on webhook endpoint
- [x] Log redaction for token-like patterns
