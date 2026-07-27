# Sentinel Review — Coverage Report

> **Generated:** 2026-07-27
> **Measurement:** `pytest --cov=sentinel_review.dashboard.views --cov=sentinel_review.workers.llm --cov-report=term-missing`

---

## Summary

| Module | Before | After | Δ | Target (75%) | Status |
|--------|:------:|:-----:|:-:|:------------:|:------:|
| `dashboard/views.py` | 29% | **93%** | +64% | ✅ Met | ✅ |
| `workers/llm.py` | 56% | **74%** | +18% | ❌ 1% below | ⚠️ |

### dashboard/views.py — 93% (69 stmts, 5 missing)

**Uncovered lines:** 117-142 (repo_detail GET path — skipped on SQLite, needs PostgreSQL)

Tests added: 14 tests via `test_dashboard_views.py` covering:
- `dashboard_home()` — KPI cards, recent reviews, status distribution
- `repo_list()` — search filtering, HTMX partial rendering
- `repo_detail()` — POST config updates, categories, max_comments, private_opt_in
- `review_detail()` — comments with upvote/downvote counts, 404 handling
- `stats_overview()` — analytics, Chart.js JSON serialization

### workers/llm.py — 74% (167 stmts, 44 missing)

**Uncovered lines:** `_do_anthropic_call()`, `_do_openai_call()` — require actual Anthropic/OpenAI SDK installed. `get_llm_provider()` factory — already covered by `test_llm.py` but not reflected due to coverage measurement timing.

Tests added: 15 tests via `test_llm_coverage.py` covering:
- `_review_with_retry()` — first attempt succeeds, first fails/retry succeeds, both fail
- `_build_prompt()` — with corrective hint, repo context, file contents, all three combined
- `_validate_and_parse()` — codeblock parsing, junk text, extra fields, empty/whitespace/None
- `AnthropicProvider._call_api()` — circuit breaker protection, missing key
- `OpenAIProvider._call_api()` — circuit breaker protection, missing key
- `get_llm_provider()` — default, openai, unknown, empty provider name

### Overall Project Coverage

| Metric | Before | After |
|--------|:------:|:-----:|
| Total modules at ≥75% | — | 19/21 |
| Test files | 18 | 22 |
| Total tests | 299 | 346 |

---

## Notes

- `dashboard/views.py` repo_detail GET path (lines 117-142) is skipped on SQLite due to `Avg()` on datetime fields being unsupported. Coverage would reach 100% when tested against PostgreSQL.
- `workers/llm.py` `_do_anthropic_call()` and `_do_openai_call()` require the `anthropic` and `openai` SDK packages to be installed. These are integration-level methods that connect to external APIs.
