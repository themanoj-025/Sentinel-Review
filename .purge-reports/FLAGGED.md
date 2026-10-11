# FLAGGED CANDIDATES: sentinel-review

These items require human review before any destructive action would be permissible.

| ID | Path / Candidate | Tier | Score | Category | Human Review Question |
|---|---|---|---|---|---|
| CAND-0003 | `backend/sentinel_review/migrations/__init__.py` | T3 | 30 | Cat A | Retain due to Database Migration? |
| CAND-0007 | `data/.gitkeep` | T3 | 30 | Cat A | Retain due to Directory Preservation Marker? |
| CAND-0008 | `docs/assets/screenshots/.gitkeep` | T3 | 30 | Cat A | Retain due to Directory Preservation Marker? |
| CAND-0050 | `backend/logging_utils/structured_logging.py` | T2 | 68 | Cat D | Is `backend/logging_utils/structured_logging.py` loaded dynamically or needed externally? |
| CAND-0051 | `backend/manage.py` | T2 | 68 | Cat D | Is `backend/manage.py` loaded dynamically or needed externally? |
| CAND-0052 | `backend/sentinel_review/api/authentication.py` | T2 | 68 | Cat D | Is `backend/sentinel_review/api/authentication.py` loaded dynamically or needed externally? |
| CAND-0053 | `backend/sentinel_review/api/health_urls.py` | T2 | 68 | Cat D | Is `backend/sentinel_review/api/health_urls.py` loaded dynamically or needed externally? |
| CAND-0054 | `backend/sentinel_review/dashboard/templates/dashboard/partials/repo_config.html` | T2 | 68 | Cat D | Is `backend/sentinel_review/dashboard/templates/dashboard/partials/repo_config.html` loaded dynamically or needed externally? |
| CAND-0055 | `backend/sentinel_review/dashboard/templates/dashboard/partials/repo_table.html` | T2 | 68 | Cat D | Is `backend/sentinel_review/dashboard/templates/dashboard/partials/repo_table.html` loaded dynamically or needed externally? |
| CAND-0056 | `backend/sentinel_review/logging_filters.py` | T2 | 68 | Cat D | Is `backend/sentinel_review/logging_filters.py` loaded dynamically or needed externally? |
| CAND-0057 | `backend/sentinel_review/login/logout.py` | T2 | 68 | Cat D | Is `backend/sentinel_review/login/logout.py` loaded dynamically or needed externally? |
| CAND-0058 | `backend/sentinel_review/middleware.py` | T2 | 68 | Cat D | Is `backend/sentinel_review/middleware.py` loaded dynamically or needed externally? |
| CAND-0059 | `backend/sentinel_review/workers/_telemetry.py` | T2 | 68 | Cat D | Is `backend/sentinel_review/workers/_telemetry.py` loaded dynamically or needed externally? |
| CAND-0060 | `backend/sentinel_review/workers/context.py` | T2 | 68 | Cat D | Is `backend/sentinel_review/workers/context.py` loaded dynamically or needed externally? |
| CAND-0061 | `backend/sentinel_review/workers/feature_flags.py` | T2 | 68 | Cat D | Is `backend/sentinel_review/workers/feature_flags.py` loaded dynamically or needed externally? |
| CAND-0062 | `backend/sentinel_review/workers/helpers.py` | T2 | 68 | Cat D | Is `backend/sentinel_review/workers/helpers.py` loaded dynamically or needed externally? |
| CAND-0063 | `backend/sentinel_review/workers/pipeline_stages.py` | T2 | 68 | Cat D | Is `backend/sentinel_review/workers/pipeline_stages.py` loaded dynamically or needed externally? |
| CAND-0064 | `backend/sentinel_review/workers/telemetry.py` | T2 | 68 | Cat D | Is `backend/sentinel_review/workers/telemetry.py` loaded dynamically or needed externally? |
| CAND-0065 | `backend/sentinel_review/workers/telemetry_flush.py` | T2 | 68 | Cat D | Is `backend/sentinel_review/workers/telemetry_flush.py` loaded dynamically or needed externally? |
| CAND-0066 | `backend/sentinel_review/wsgi.py` | T2 | 68 | Cat D | Is `backend/sentinel_review/wsgi.py` loaded dynamically or needed externally? |
| CAND-0067 | `backend/tests/test_api_views_coverage.py` | T2 | 68 | Cat D | Is `backend/tests/test_api_views_coverage.py` loaded dynamically or needed externally? |
| CAND-0068 | `backend/tests/test_circuit_breaker_integration.py` | T2 | 68 | Cat D | Is `backend/tests/test_circuit_breaker_integration.py` loaded dynamically or needed externally? |
| CAND-0069 | `backend/tests/test_dashboard_views.py` | T2 | 68 | Cat D | Is `backend/tests/test_dashboard_views.py` loaded dynamically or needed externally? |
| CAND-0070 | `backend/tests/test_feature_flags.py` | T2 | 68 | Cat D | Is `backend/tests/test_feature_flags.py` loaded dynamically or needed externally? |
| CAND-0071 | `backend/tests/test_feedback.py` | T2 | 68 | Cat D | Is `backend/tests/test_feedback.py` loaded dynamically or needed externally? |
| CAND-0072 | `backend/tests/test_github_client.py` | T2 | 68 | Cat D | Is `backend/tests/test_github_client.py` loaded dynamically or needed externally? |
| CAND-0073 | `backend/tests/test_llm_coverage.py` | T2 | 68 | Cat D | Is `backend/tests/test_llm_coverage.py` loaded dynamically or needed externally? |
| CAND-0074 | `backend/tests/test_models.py` | T2 | 68 | Cat D | Is `backend/tests/test_models.py` loaded dynamically or needed externally? |
| CAND-0075 | `backend/tests/test_notification_service.py` | T2 | 68 | Cat D | Is `backend/tests/test_notification_service.py` loaded dynamically or needed externally? |
| CAND-0076 | `backend/tests/test_rate_limiting.py` | T2 | 68 | Cat D | Is `backend/tests/test_rate_limiting.py` loaded dynamically or needed externally? |
| CAND-0077 | `backend/tests/test_review_worker.py` | T2 | 68 | Cat D | Is `backend/tests/test_review_worker.py` loaded dynamically or needed externally? |
| CAND-0078 | `backend/tests/test_semgrep.py` | T2 | 68 | Cat D | Is `backend/tests/test_semgrep.py` loaded dynamically or needed externally? |
| CAND-0079 | `frontend/tailwind.config.js` | T2 | 68 | Cat D | Is `frontend/tailwind.config.js` loaded dynamically or needed externally? |
| CAND-0080 | `scripts/eval_pkg/analyzers.py` | T2 | 68 | Cat D | Is `scripts/eval_pkg/analyzers.py` loaded dynamically or needed externally? |
| CAND-0081 | `scripts/eval_pkg/runners.py` | T2 | 68 | Cat D | Is `scripts/eval_pkg/runners.py` loaded dynamically or needed externally? |
| CAND-0082 | `scripts/eval_pkg/writers.py` | T2 | 68 | Cat D | Is `scripts/eval_pkg/writers.py` loaded dynamically or needed externally? |
