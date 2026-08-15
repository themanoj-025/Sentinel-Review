# sentinel-review — System Architecture

sentinel-review is an **AI code-review automation platform**: a GitHub App
that reviews pull requests with an LLM, runs Semgrep analysis, posts review
comments, tracks feedback, and exposes a Django dashboard + REST API.

## High-level components

```
                ┌───────────────────────────────────────────────┐
                │        GitHub (webhooks + App tokens)         │
                └──────────────────────┬────────────────────────┘
                                       │ webhook payloads (signature-verified)
                ┌──────────────────────▼────────────────────────┐
                │        backend/  (Django + Celery)            │
                │  webhooks/views.py   →  workers/review_worker │
                │  workers/            →  pipeline → LLM/Semgrep│
                │  api/ (REST)         ·  dashboard/ (UI views) │
                │  models/ · services/ · celery_app.py          │
                └──────┬───────────────┬───────────────┬────────┘
                       │               │               │
                       ▼               ▼               ▼
                ┌────────────┐  ┌────────────┐  ┌────────────┐
                │ PostgreSQL │  │  Redis     │  │ GitHub API │
                │ (Django ORM)│ │ (Celery    │  │ (GH App    │
                │            │  │  broker)   │  │  client)   │
                └────────────┘  └────────────┘  └────────────┘
                ┌──────────────────────┬────────────────────────┐
                │ frontend/ (static)   │  docs/ (MkDocs site)   │
                │ vanilla JS + Tailwind│  architecture, design, │
                │ esbuild bundle       │  technical, reference   │
                └──────────────────────┴────────────────────────┘
```

## Component responsibilities

| Component | Responsibility |
|---|---|
| `backend/sentinel_review/webhooks/` | GitHub webhook intake (`views.py`), signature verification (`signature.py`), idempotent dispatch |
| `backend/sentinel_review/workers/` | Async review pipeline: `pipeline.py` orchestrates; `review_worker.py` consumes Celery tasks; `llm.py` (LLM client), `semgrep_integration.py`, `github_client.py`, `http_transport.py` (rate limits + retries), `token_manager.py` (GH App token rotation), `prompt_builder.py`, `ignore_rules.py`, `circuit_breaker.py`, `feature_flags.py`, `cache.py`, `gha_runner.py`, `feedback_worker.py`, `schemas.py` |
| `backend/sentinel_review/models/` | ORM models: repo, pull_request, review, comment, feedback, installation |
| `backend/sentinel_review/services/` | `stats_service.py` (metrics), `notification_service.py` |
| `backend/sentinel_review/api/` | REST API: `views.py`, `serializers.py`, `urls.py`, `health.py`, `metrics.py` |
| `backend/sentinel_review/dashboard/` | Server-rendered dashboard (Django templates + views) |
| `backend/sentinel_review/celery_app.py` | Celery app; workers on queues `reviews`, `feedback`, `default` |
| `backend/sentinel_review/settings.py` | Django settings (env-driven) |
| `frontend/` | Static assets built with Tailwind + esbuild (bundle served by Django) |
| `scripts/` | `gha_review.py` (GitHub Actions runner mode), `run_evaluation.py`, `build_eval_set.py`, `run_comparison.py`, `load_test.py` |
| `data/` | Evaluation sets (`eval_set.json`) |

## Key architectural decisions

- **Webhook-first ingestion** — GitHub App pushes events to the Django
  webhook endpoint; signatures verified; tasks dispatched to Celery.
- **Async review pipeline** — `workers/pipeline.py` sequences diff fetch →
  prompt build → LLM review → Semgrep scan → comment post → feedback
  capture, with per-call rate limiting and a circuit breaker on the GitHub client.
- **Django + Celery + Redis + Postgres** — Django ORM for state, Celery for
  background work (queues: reviews/feedback/default), Redis broker, Flower
  monitoring.
- **Evaluation harness** — `scripts/run_evaluation.py` + `data/eval_set.json`
  measure review quality offline.
- **Dual deployment targets** — Render (`render.yaml`, gunicorn) and Fly
  (`fly.toml`); both serve the Django app; MkDocs serves the docs site.
