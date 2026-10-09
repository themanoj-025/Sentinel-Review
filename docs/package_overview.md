# sentinel-review — Package & Module Inventory

## Django project: `backend/sentinel_review`

| Module | Responsibility |
|---|---|
| `settings.py` | Env-driven Django settings (DB, Redis, GH App, LLM, secrets) |
| `urls.py` / `wsgi.py` | URL routing + WSGI entry (`gunicorn sentinel_review.wsgi:application`) |
| `celery_app.py` | Celery app; queues `reviews`, `feedback`, `default` |
| `apps.py`, `admin.py`, `logging_filters.py` | Django app config, admin, log filters |
| `api/` | REST API: `views.py`, `serializers.py`, `urls.py`, `health.py`, `metrics.py` |
| `dashboard/` | Server-rendered dashboard: views + Django templates (repo list/detail, review detail, stats) |
| `webhooks/` | GitHub webhook intake: `views.py`, `signature.py`, `urls.py` |
| `workers/` | Async pipeline: `pipeline.py`, `review_worker.py`, `feedback_worker.py`, `llm.py`, `semgrep_integration.py`, `github_client.py`, `http_transport.py`, `token_manager.py`, `prompt_builder.py`, `ignore_rules.py`, `circuit_breaker.py`, `feature_flags.py`, `cache.py`, `gha_runner.py`, `schemas.py` |
| `services/` | `stats_service.py` (metrics), `notification_service.py` |
| `models/` | ORM: `repo`, `pull_request`, `review`, `comment`, `feedback`, `installation` |
| `migrations/` | `0001_initial` → `0003_feedback index` |

## Tests: `backend/tests/`

`test_api_views_coverage`, `test_cache`, `test_circuit_breaker_integration`,
`test_dashboard_views`, `test_e2e`, `test_feature_flags`, `test_feedback`,
`test_gha_review`, `test_github_client`, `test_ignore_rules`, `test_llm`,
`test_llm_coverage`, `test_models`, `test_notification_service`,
`test_rate_limiting`, `test_review_worker`, `test_schemas`, `test_semgrep`,
`test_signature`, `test_startup`, `test_webhook`, `test_webhook_idempotency`
+ `conftest.py`, `fixtures/sample_prs/`.

## Frontend: `frontend/`

| Path | Purpose |
|---|---|
| `src/app.js`, `src/chart-loader.js`, `src/input.css` | Sources (Tailwind + esbuild) |
| `static/js/bundle.js`, `static/css/output.css` | Built assets (esbuild) |
| `esbuild.config.mjs`, `tailwind.config.js`, `package.json` | Build config |

## Non-package trees

| Path | Purpose |
|---|---|
| `scripts/` | `gha_review.py`, `run_evaluation.py`, `build_eval_set.py`, `run_comparison.py`, `load_test.py` |
| `data/` | Evaluation set (`eval_set.json`) |
| `docs/` | MkDocs documentation site (architecture, design, product, project, reference, technical, migration) |
| `mkdocs.yml` | Docs site navigation/theme |
| `.github/workflows/` | CI, load-test, SBOM, security-scan pipelines |
