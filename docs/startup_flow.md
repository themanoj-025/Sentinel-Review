# sentinel-review — Startup Flow

Deployed as a Docker Compose stack (web + worker + flower + postgres + redis)
or on Render/Fly. All commands run from `backend/` (Makefile convention).

## Container stack (`docker-compose.yml`)

1. **postgres** — `pg_isready` health check (db `sentinel_review`, user `sentinel`).
2. **redis** — broker for Celery (`redis://redis:6379/0`).
3. **web** —
   `python manage.py migrate --noinput && gunicorn sentinel_review.wsgi:application --bind 0.0.0.0:8000 --workers 4 --threads 2 --timeout 60`.
   Django startup: `settings.py` reads env (DB URL, Redis URL, GitHub App
   creds, LLM config, webhook secret) → URLconf wires `api/`, `dashboard/`,
   `webhooks/` → gunicorn serves.
4. **worker** — `celery -A sentinel_review worker -l info -Q reviews,feedback,default -c 2`.
   Consumes `workers/review_worker` (reviews queue), `workers/feedback_worker`
   (feedback queue); default queue for misc tasks.
5. **flower** — `celery --broker=redis://redis:6379/0 flower --port=5555` (basic-auth).

## Request flow: GitHub webhook → review comment

1. GitHub App sends a webhook → `webhooks/views.py` verifies the signature
   (`webhooks/signature.py`) and checks idempotency.
2. A Celery task is enqueued → `workers/review_worker` runs
   `workers/pipeline.py`.
3. Pipeline: fetch PR diff via `github_client` (token from `token_manager`,
   rate-limited via `http_transport`, guarded by `circuit_breaker`) →
   `prompt_builder` builds the review prompt → `llm` produces comments →
   `semgrep_integration` adds static-analysis findings → `ignore_rules`
   filters → comments posted back via `github_client`.
4. Feedback loop: `feedback_worker` captures user reactions
   (thumbs up/down) → `models/feedback` → `services/notification_service`
   alerts on low-quality reviews.

## Operational entry points

| Entry | Command |
|---|---|
| Dev server | `cd backend && python manage.py runserver` |
| Migrate | `cd backend && python manage.py migrate` (Makefile `make migrate`) |
| Celery worker | `celery -A sentinel_review worker -l info -Q reviews,feedback,default` |
| Tests | `cd backend && python -m pytest` (Makefile `make test`) |
| GHA mode | `python scripts/gha_review.py` (run reviews from GitHub Actions) |
| Evaluation | `python scripts/run_evaluation.py --data data/eval_set.json` |
| Docs site | `mkdocs serve` (site config `mkdocs.yml`) |

## What must exist at startup

- Env keys from `.env.example` (DJANGO_SECRET_KEY, DATABASE_URL, REDIS_URL,
  GITHUB_APP_*, LLM_* keys, WEBHOOK_SECRET)
- Postgres reachable + migrations applied (auto-run in container entry)
- Redis reachable (Celery broker)
