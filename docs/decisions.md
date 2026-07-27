# Sentinel Review — Architectural Decisions

> *Record of key architectural decisions, their rationale, and alternatives considered.*

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
- Mature, well-documented task queue with Django integration (`django-celery-results`)
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

**Context:** The frontend must be Python-based — no React/Next.js/Vue. Some interactivity (toggling panels, inline config editing, live status) is needed.

**Decision:** Use Django Templates + HTMX + Alpine.js.

**Rationale:**
- HTMX allows server-rendered HTML with partial page updates — no client-side state/data-fetching
- Alpine.js (~15KB, no build step) handles tiny UI affordances like toggling a config panel
- Tailwind CSS is NOT bundled — plain CSS with CSS variables keeps the Node dependency to zero

**What counts as "Python-based under the hood":**
- All state and data logic lives on the server (Django views)
- HTMX is purely a hypermedia exchange mechanism
- Alpine.js is used only for UI chrome (show/hide panels), never for data fetching

---

## ADR-4: Pydantic v2 for Structured LLM Output

**Status:** Accepted (2026-07-27)

**Context:** LLM output is unpredictable. Malformed JSON must never reach the GitHub API.

**Decision:** Define strict Pydantic v2 schemas (`Finding`, `ReviewOutput`) and validate every LLM response before use.

**Rationale:**
- Pydantic provides automatic type coercion and descriptive validation errors
- Failed validations trigger a retry with error-correction prompt before dropping the chunk
- Schema doubles as documentation for the LLM prompt
- Validation is deterministic code — LLM-untrusted

**Consequences:**
- LLM calls are wrapped in `try/except` with a retry mechanism
- On retry failure, the chunk's findings are dropped and logged (never partially posted)

---

## ADR-5: Semgrep as Secondary Signal

**Status:** Accepted (2026-07-27)

**Context:** LLM-only review can miss issues. A deterministic static analysis tool provides an independent signal.

**Decision:** Run Semgrep on changed file contents in parallel with the LLM, then merge results.

**Rationale:**
- Semgrep is language-aware, rule-based, and deterministic — no false positives from hallucination
- When LLM and Semgrep agree on a finding, it's marked as "high confidence"
- Semgrep is optional — if not installed, the worker continues without it
- Provides security-specific coverage (injection, hardcoded secrets, unsafe deserialization)

**Consequences:**
- Requires Semgrep CLI to be installed in the Docker image or worker environment
- Adds ~.5-2s analysis time per file
- Findings are merged via `merge_with_llm_findings()` which prevents duplicates

---

## ADR-6: HMAC-SHA256 for Webhook Verification

**Status:** Accepted (2026-07-27)

**Context:** GitHub sends webhooks to a public endpoint. Requests could be spoofed.

**Decision:** Verify every webhook using HMAC-SHA256 with constant-time comparison.

**Rationale:**
- GitHub signs every webhook with the shared secret using HMAC-SHA256
- `hmac.compare_digest()` prevents timing attacks
- Verification happens before any other processing (first gate)
- Development mode: empty secret disables verification for local testing

---

## ADR-7: GitHub App JWT + Installation Token Auth

**Status:** Accepted (2026-07-27)

**Context:** The system needs authenticated access to GitHub repositories without a user-bound token.

**Decision:** Use GitHub App authentication: JWT → installation access token.

**Rationale:**
- GitHub Apps authenticate as the app itself (JWT), then impersonate installations for repo access
- Installation tokens expire after 1 hour (short-lived, not persisted)
- Tokens are cached in-memory and auto-refreshed before expiry
- Private key never touches the repository — loaded from env/secrets manager

---

## ADR-8: SQLite for Development, PostgreSQL for Production

**Status:** Accepted (2026-07-27)

**Context:** Local development should not require a PostgreSQL server. Production needs full reliability.

**Decision:** Use `dj-database-url` with SQLite fallback; docker-compose provides PostgreSQL.

**Rationale:**
- Django's ORM abstracts the database layer — most dev work doesn't need PostgreSQL features
- `psycopg[binary]` is installed for production while `sqlite3` is used for quick local testing
- docker-compose always starts a PostgreSQL 16 container for the CI-matching environment
- Schema migrations are tested against Postgres in CI

---

## ADR-9: Private Repo Opt-In Flow

**Status:** Accepted (2026-07-27)

**Context:** Reviewing private repositories requires explicit human consent.

**Decision:** Add a `private_repo_opt_in` boolean field in `Repo.config`, defaulting to `false`.

**Rationale:**
- The worker checks this flag BEFORE sending any data to the LLM or Semgrep
- GitHub App permissions request only `contents: read` and `pull_requests: read/write`
- The flag is toggleable via the dashboard or API — no code changes needed
- This is a deterministic code check, not a prompt-level instruction

---

## ADR-10: Single Django App Layout

**Status:** Accepted (2026-07-27)

**Context:** The project has clear functional boundaries (webhooks, workers, API, dashboard, models).

**Decision:** Use a single Django project with logical sub-packages rather than multiple Django apps.

**Rationale:**
- All components share the same database and settings — no need for app isolation
- Sub-packages (`models/`, `webhooks/`, `workers/`, `dashboard/`, `api/`) provide clear separation
- Reduces migration complexity (single set of migrations)
- Follows Django's "reusable app" conventions while keeping everything in one deployable unit

**Sub-package structure:**
```
sentinel_review/
├── models/          # Database models (installation, repo, pr, review, comment, feedback)
├── webhooks/        # GitHub webhook receiver (views, signature verification)
├── workers/         # Celery tasks (review, feedback, LLM provider, GitHub client, Semgrep)
├── dashboard/       # Server-rendered dashboard (views, templates, urls)
└── api/             # DRF API endpoints (views, serializers, urls)
```

---

## ADR-11: Project Name — Sentinel Review

**Status:** Accepted (2026-07-27)

**Context:** The project needs a name that signals its purpose without colliding with existing tools.

**Decision:** Use `sentinel-review` as the repo/package slug.

**Rationale:**
- "Sentinel" = "always-watching, trustworthy guardian" — fits the PR-review agent concept
- No collision with CodeRabbit, Greptile, or Copilot for PRs
- Reads well as a GitHub App display name
- Double-s as good CLI/binary naming (`sentinelctl`)

**Fallback order (if slug is taken):** `sentinelreview-ai` → `patchsentry` → `diffsage`

---

## ADR-12: No JavaScript Frontend Framework

**Status:** Accepted (2026-07-27)

**Context:** The dashboard must be Python-rendered. A React/Vue/Svelte build step is explicitly disallowed.

**Decision:** Zero Node.js dependencies in the project. No `package.json`, no webpack/vite, no JS framework.

**Rationale:**
- The requirement explicitly states "Python-based frontend"
- All HTML is rendered server-side via Django Templates
- HTMX handles dynamic updates (partial page replacements via `HX-Request` headers)
- Alpine.js handles local UI state (toggle panels, form interactions)
- Tailwind CSS is loaded via CDN `<script>` tag — no build step, no PostCSS, no `tailwind.config.js` file
- The only JS library is Chart.js (via `<script>` tag) for dashboard charts — documented as the sole exception

---

## ADR-13: Log Redaction for Secrets in Logs

**Status:** Accepted (2026-07-27)

**Context:** Logger statements in the codebase may accidentally include API keys, tokens, passwords, or other secrets in log output. This is a compliance and security risk.

**Decision:** Implement a server-side `logging.Filter` subclass that redacts sensitive patterns before log records reach the console handler.

**Rationale:**
- `logging.Filter` is the idiomatic Django/Python approach — no monkey-patching, no middleware
- Runs on every log record regardless of logger, including third-party libraries
- Patterns are regex-based, ordered by specificity to minimize false positives
- Covers: Anthropic keys (`sk-ant-...`), OpenAI keys, private key PEM blocks, GitHub tokens, Bearer tokens, password assignments, JWT tokens, DB connection strings
- Registered in `settings.py` as a handler-level filter on the `console` handler

**Alternatives considered:**
- **Custom logging formatter:** Would require subclassing every formatter
- **Middleware-level redaction:** Too broad — would redact responses, not just logs
- **Manual redaction in each logger call:** Error-prone, easy to miss

---

## ADR-14: Deployment Configuration — Render.com + Fly.io

**Status:** Accepted (2026-07-27)

**Context:** The project needs to be deployable to a public URL for GitHub webhooks to reach it (webhooks cannot hit `localhost`). Production deployment requires PostgreSQL, Redis, a web process, and a background worker process.

**Decision:** Provide platform-agnostic deployment configs for Render.com (`render.yaml`) and Fly.io (`fly.toml`).

**Rationale:**
- Both platforms offer free/cheap tiers suitable for a portfolio project
- `render.yaml` is Render's Blueprint format — auto-detected when pushing to GitHub
- `fly.toml` supports separate `[processes]` for web worker processes on the same app
- Both configs use the existing Dockerfile for consistent build behavior
- Secrets are passed via platform-managed environment variables (no `fly secrets` / Render dashboard)
- Both support PostgreSQL 16 and Redis as managed resources
