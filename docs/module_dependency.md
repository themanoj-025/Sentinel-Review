# sentinel-review — Module Dependency Map

## Django apps → layers (backend/sentinel_review)

```
settings.py          ← imported by everything (env config)
celery_app.py        ← imports settings; task modules import celery_app
urls.py / wsgi.py    ← routes to api, dashboard, webhooks, health urls

webhooks/views.py    → workers/review_worker, workers/feedback_worker (tasks),
                       services/notification_service, models
webhooks/signature.py → settings (secret) — leaf

workers/pipeline.py  → workers/llm, workers/semgrep_integration,
                       workers/github_client, workers/prompt_builder,
                       workers/ignore_rules, workers/schemas
workers/review_worker.py → workers/pipeline, workers/cache, models
workers/github_client.py → workers/http_transport, workers/token_manager,
                           workers/circuit_breaker
workers/llm.py       → workers/http_transport, workers/circuit_breaker,
                       workers/schemas, settings
workers/semgrep_integration.py → workers/http_transport, settings
workers/token_manager.py → models/installation (token store)
workers/gha_runner.py → workers/pipeline (Actions mode), workers/schemas
workers/feature_flags.py / cache.py → settings — leaf adapters

api/views.py         → api/serializers, models, workers/cache, services/stats
api/health.py        → settings, services (readiness)
api/metrics.py       → (Prometheus)

dashboard/views.py   → models, services/stats_service
services/stats_service.py → models
services/notification_service.py → models, settings
```

## Cross-boundary rules

- **Only `workers/*` talks to external services** (GitHub, LLM providers,
  Semgrep) — `api`, `dashboard`, and `webhooks` never call them directly;
  they enqueue tasks via `celery_app` or read state via `services`/`models`.
- **`webhooks` → `workers` is task-enqueue only** (`.delay()`), keeping the
  HTTP path fast and idempotent.
- **No circular imports** — pipeline/task modules import leaf workers
  (`http_transport`, `schemas`, `prompt_builder`) which never import back.
- **Models app is the shared contract** — all layers import
  `sentinel_review.models`; no layer defines its own persistence.

## Frontend → backend

```
frontend/src/app.js + chart-loader.js → fetch Django dashboard/API endpoints
frontend/static/*  (built)            → served via Django collectstatic
```

## External dependencies

Django 4/5 · Celery + Redis · Postgres · gunicorn · requests (http_transport)
· Semgrep CLI/API · an LLM provider (openai-compatible) · Prometheus client ·
MkDocs + Material theme (docs site)
