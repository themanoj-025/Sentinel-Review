# Sentinel Review — Architectural Decisions

> *Record of key architectural decisions, their rationale, and alternatives considered.*
> *Last updated: 2026-07-27 (6 new ADRs added during remediation)*

---

## ADR-1: Django + DRF over FastAPI

**Status:** Accepted (2026-07-27)

**Context:** The frontend/dashboard must be Python-based. Two mature Python web frameworks were considered.

**Decision:** Use Django 5.x + Django REST Framework.

**Rationale:**
- Django provides batteries-included auth/sessions, ORM+migrations, and admin panel — one framework instead of stitching FastAPI + Jinja2 + Alembic + a separate admin tool
- DRF gives clean API endpoints for programmatic access
- Django admin provides an instant ops view without additional development
- For a solo-built portfolio project, fewer moving parts = higher chance of completion

**Alternatives considered:**
- **FastAPI + Jinja2 + HTMX:** Would require separate admin tool (django-sql-explorer?), separate ORM (SQLAlchemy), separate migration tool (Alembic) — more integration surface
- **Flask:** Too minimal — would need to compose too many third-party libraries

**Consequences:**
- Async webhook handling requires Celery (Django's sync request-response cycle)
- Project template rendering is straightforward

---

## ADR-2: Celery + Redis for Background Jobs

**Status:** Accepted (2026-07-27)

**Context:** Webhook responses must return within 10 seconds (GitHub timeout). LLM calls can take 30+ seconds.

**Decision:** Use Celery with Redis as both broker and result backend.

**Rationale:**
- Mature, well-documented task queue with Django integration
- Redis-as-broker is fast (sub-millisecond enqueue), matching the "fast receiver, slow worker" pattern
- Task routing allows dedicated queues: `reviews` for LLM work, `feedback` for reaction polling
- Flower provides a web-based monitoring UI out of the box

**Alternatives considered:**
- **arq + Redis:** Lighter weight but less ecosystem support
- **Django Q:** Mature but less community adoption than Celery
- **Huey:** Too minimal for task routing and monitoring needs

---

## ADR-3: HTMX + Alpine.js over a JavaScript Framework

**Status:** Accepted (2026-07-27)

**Context:** The frontend must be Python-based — no React/Next.js/Vue. Some interactivity is needed.

**Decision:** Use Django Templates + HTMX + Alpine.js.

**Rationale:**
- HTMX allows server-rendered HTML with partial page updates — no client-side state/data-fetching
- Alpine.js (~15KB, no build step) handles tiny UI affordances like toggling a config panel
- Tailwind CSS via compiled build (no CDN, no Node runtime at container runtime)

---

## ADR-4: Pydantic v2 for Structured LLM Output

**Status:** Accepted (2026-07-27)

**Context:** LLM output is unpredictable. Malformed JSON must never reach the GitHub API.

**Decision:** Define strict Pydantic v2 schemas (`Finding`, `ReviewOutput`) and validate every LLM response before use.

**Rationale:**
- Pydantic provides automatic type coercion and descriptive validation errors
- Failed validations trigger a corrective retry before dropping the chunk
- Schema doubles as documentation for the LLM prompt

---

## ADR-5: Semgrep as Secondary Signal

**Status:** Accepted (2026-07-27)

**Context:** LLM-only review can miss issues. A deterministic static analysis tool provides an independent signal.

**Decision:** Run Semgrep on changed file contents in parallel with the LLM, then merge results.

**Rationale:**
- Semgrep is language-aware, rule-based, and deterministic — no false positives from hallucination
- When LLM and Semgrep agree on a finding, it's marked as "high confidence"
- Semgrep is optional — if not installed, the worker continues without it

---

## ADR-6: HMAC-SHA256 for Webhook Verification

**Status:** Accepted (2026-07-27, updated 2026-07-27)

**Context:** GitHub sends webhooks to a public endpoint. Requests could be spoofed.

**Decision:** Verify every webhook using HMAC-SHA256 with constant-time comparison. Production fails to start if `WEBHOOK_SECRET` is unset.

**Rationale:**
- GitHub signs every webhook with the shared secret using HMAC-SHA256
- `hmac.compare_digest()` prevents timing attacks
- **Updated:** Missing secret in production now raises `ImproperlyConfigured` (previously returned `True` — a security hole)

---

## ADR-7: GitHub App JWT + Installation Token Auth

**Status:** Accepted (2026-07-27)

**Context:** The system needs authenticated access to GitHub repositories without a user-bound token.

**Decision:** Use GitHub App authentication: JWT → installation access token.

**Rationale:**
- Installation tokens expire after 1 hour (short-lived, not persisted)
- Tokens are cached in-memory and auto-refreshed before expiry

---

## ADR-8: SQLite for Development, PostgreSQL for Production

**Status:** Accepted (2026-07-27)

**Context:** Local development should not require a PostgreSQL server.

**Decision:** Use `dj-database-url` with SQLite fallback; docker-compose provides PostgreSQL.

---

## ADR-9: Private Repo Opt-In Flow

**Status:** Accepted (2026-07-27)

**Context:** Reviewing private repositories requires explicit human consent.

**Decision:** Add a `private_repo_opt_in` boolean field in `Repo.config`, defaulting to `false`.

---

## ADR-10: Single Django App Layout

**Status:** Accepted (2026-07-27)

**Context:** The project has clear functional boundaries.

**Decision:** Use a single Django project with logical sub-packages rather than multiple Django apps.

```
sentinel_review/
├── models/          # Database models
├── webhooks/        # GitHub webhook receiver
├── workers/         # Celery tasks, pipeline, LLM, GitHub client
├── dashboard/       # Server-rendered dashboard
└── api/             # DRF REST API (v1 endpoints)
```

---

## ADR-11: Project Name — Sentinel Review

**Status:** Accepted (2026-07-27)

**Context:** The project needs a name that signals its purpose without colliding with existing tools.

**Decision:** Use `sentinel-review` as the repo/package slug.

---

## ADR-12: No JavaScript Frontend Framework

**Status:** Accepted (2026-07-27)

**Context:** The dashboard must be Python-rendered.

**Decision:** Zero Node.js dependencies. Tailwind via compiled build step in Docker.

---

## ADR-13: Log Redaction for Secrets in Logs

**Status:** Accepted (2026-07-27, updated 2026-07-27)

**Context:** Logger statements may accidentally include API keys, tokens, or passwords in log output.

**Decision:** Implement a server-side `logging.Filter` subclass that redacts sensitive patterns.

**Updated:** Removed `[a-fA-F0-9]{40,}` pattern that falsely matched git commit SHAs.

---

## ADR-14: Deployment Configuration — Render.com + Fly.io

**Status:** Accepted (2026-07-27)

**Context:** The project needs to be deployable to a public URL for GitHub webhooks.

**Decision:** Provide platform-agnostic deployment configs for Render.com and Fly.io.

---

## ADR-15: Staged Pipeline Architecture (Post-Remediation)

**Status:** Accepted (2026-07-27)

**Context:** The original `review_pull_request` was a ~250-line monolith doing 7 sequential responsibilities. This made the function hard to test, hard to debug, and hard to extend.

**Decision:** Extract each responsibility into a named **pipeline stage** with clear I/O via a typed `ReviewContext` dataclass.

**Pipeline stages:**
1. `UpsertStage` — DB records + private repo check
2. `FetchDiffStage` — GitHub diff + file contents
3. `FetchContextStage` — Repo metadata + `.sentinel-ignore` (non-fatal)
4. `LLMReviewStage` — Cache check → LLM call → cache store
5. `SemgrepStage` — Static analysis (non-fatal)
6. `DedupeStage` — Merge, .sentinel-ignore filter, dedup, limit
7. `PostCommentsStage` — Post inline comments + save to DB

**Rationale:**
- Each stage is independently unit-testable
- A failure in one stage doesn't crash the entire pipeline
- Stages can be reordered, removed, or added without touching other stages
- The pipeline orchestrator is ~50 lines of glue code

**Alternatives considered:**
- **Decorator-based pipeline:** More clever but harder to debug
- **Chain-of-Responsibility pattern:** Over-engineered for 7 stages
- **Single function with helper calls:** The original approach — led to the 250-line monolith

---

## ADR-16: LLM Response Cache

**Status:** Accepted (2026-07-27)

**Context:** A PR with multiple `synchronize` events (e.g., force-push with no diff change) triggers a new LLM call for an identical diff. This wastes time and money.

**Decision:** Cache LLM responses keyed by `SHA256(diff_content + repo_context)` hex digest.

**Rationale:**
- SHA256 guarantees collision resistance for cache keys
- Redis is already running as the Celery broker — no new infrastructure
- In-memory dict fallback works when Redis is unavailable
- Cache TTL (3600s) is long enough to cover repeated `synchronize` events
- Cache-hit/miss metrics exported to Prometheus

**Cache invalidation:** Keyed by diff hash + context — any change to the diff or repo context produces a new key. No explicit invalidation needed.

---

## ADR-17: .sentinel-ignore File Support

**Status:** Accepted (2026-07-27)

**Context:** Repositories have generated files, vendor directories, and test artifacts that should never receive review comments. Currently, the only way to exclude files is per-repo config category filters.

**Decision:** Support a `.sentinel-ignore` file in the repository root using `fnmatch` glob patterns (one per line, `#` comments).

**Rationale:**
- Industry-standard pattern: `.gitignore`, `.eslintignore`, `.dockerignore` all use similar formats
- `fnmatch` is in the Python standard library — zero new dependencies
- Patterns can target directories (`build/`), extensions (`*.generated.py`), or specific paths (`docs/*.md`)
- In webhook mode, fetched from the repo's default branch via GitHub API
- In GHA mode, read from the working directory

---

## ADR-18: GitHub Actions Execution Mode

**Status:** Accepted (2026-07-27)

**Context:** Not all teams want to host a Django/Celery/PostgreSQL/Redis stack for PR review. An alternative deployment model that runs as a CI step lowers the adoption barrier.

**Decision:** Provide a composite GitHub Action (`action.yml`) that runs the same review pipeline directly in CI.

**Rationale:**
- Composite actions are self-contained — no Docker image to build or publish
- Bypasses the entire Django/Celery/Redis stack
- Reads `GITHUB_EVENT_PATH` for PR data, runs `git diff` for the diff (no GitHub API calls needed)
- Reuses `SYSTEM_PROMPT`, `ReviewOutput` schema, and LLM callers from the webhook code
- Demonstrates two integration patterns: webhook (server) + CI action (agentless)

---

## ADR-19: Multi-Model Comparison Framework

**Status:** Accepted (2026-07-27)

**Context:** Evaluation results depend heavily on which LLM provider is used. Anthropic Claude and OpenAI GPT-4o have different strengths for code review.

**Decision:** Add a comparison script (`scripts/run_comparison.py`) that runs both providers against the same evaluation fixtures and produces a side-by-side table.

**Rationale:**
- Shares evaluation logic with `run_evaluation.py` (no code duplication)
- Mock mode requires no API keys for quick testing
- Live mode runs real LLM calls for accurate cost/latency/quality comparison
- Output updates `docs/evaluation-report.md` with the comparison table

---

## ADR-20: Circuit Breaker for External Dependencies

**Status:** Accepted (2026-07-27)

**Context:** The GitHub API and LLM providers are external dependencies that can fail or become slow. Without protection, a cascading failure can exhaust Celery workers with retries.

**Decision:** Implement a lightweight circuit breaker (CLOSED/OPEN/HALF_OPEN states) for GitHub API and LLM provider calls.

**Rationale:**
- Prevents thundering-herd retries during an outage
- Three-state design follows Michael Nygard's "Release It!" pattern
- No heavyweight library needed — ~100 lines of Python with configurable thresholds and cooldowns
- Wired into both `GitHubClient` and the LLM provider layer

**Configuration:**
- Failure threshold: 3 failures in 60s window → OPEN
- Cooldown: 120s before HALF_OPEN probe
- Probe: single request allowed — success returns to CLOSED, failure resets cooldown

---

## ADR-21: Observability Stack — JSON Logs + Sentry + Prometheus

**Status:** Accepted (2026-07-27)

**Context:** The original project had no structured logging, no error tracking, and no metrics. Debugging production issues required ad-hoc log reading.

**Decision:** Implement a three-layer observability stack:
1. **Structured JSON logging** (controlled by `JSON_LOG` env var)
2. **Sentry integration** (conditional on `SENTRY_DSN` env var)
3. **Prometheus metrics** (controlled by `METRICS_ENABLED` env var)

**Metrics exported:**
- `review_latency` — histogram of pipeline execution time
- `reviews_total` — counter of completed reviews (by status)
- `llm_errors` — counter of LLM failures
- `llm_cache_hits` / `llm_cache_misses` — cache effectiveness
- `token_cost` — cumulative token usage and estimated cost

---

## Manual Step: Live LLM Evaluation

**Context:** The evaluation harness (`scripts/run_evaluation.py`) defaults to a rule-based mock provider. It must be run with real API keys to produce accurate precision/recall/F1 numbers in `docs/evaluation-report.md`.

**How to run:**
```bash
# Requires real Anthropic + OpenAI API keys (set in .env or environment)
python scripts/run_evaluation.py --mode live --provider anthropic --output docs/evaluation-report.md
python scripts/run_evaluation.py --mode live --provider openai --output docs/evaluation-report.md

# For side-by-side comparison:
python scripts/run_comparison.py --mode live --output docs/evaluation-report.md
```

**Note:** This step incurs API usage costs (~$2-5 per full run depending on model and eval set size). The mock mode results in the current report are illustrative only and should be replaced with live numbers before publishing evaluation claims.
