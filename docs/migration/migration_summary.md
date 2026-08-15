# sentinel-review — Migration Summary (v5.0)
- Removed AGENTS_FIX.md
- Cleaned PROJECT_OVERVIEW.md
- Added v5.0 reporting artifacts

---

## Phase 3 Re-run — Full Protocol Verification (2026-08-12)

**Mandate:** Full re-execution of the Principal Architect restructuring protocol; zero-regression; evidence-backed Phase 7.

**Discovery (P1) / Classification (P2) / Target conformance (P3):** Structure conforms (backend/ Django app, frontend/, scripts/, data/).

**Moves (P4) & Naming (P5):** No moves required this pass. Banned-token scan: clean.

**Verification (P7) — evidence:**
| Check | Command | Result |
|---|---|---|
| Django system check | python manage.py check | No issues (0 silenced) |
| Lint (criticals) | python -m ruff check . --select=E9,F63,F7,F82 | 0 errors |
| Tests | python -m pytest -q (backend/) | 343 passed, 9 failed |
| Failure root cause | pytest tests/test_webhook.py::... -q | TypeError: format requires a mapping (logging format bug on webhook/e2e paths) |

**Risk & Rollback (P8):** No moves — no new risk.

**Follow-up backlog (P9):**
- 9 pre-existing failures (test_webhook.py x2, test_webhook_idempotency.py x3, test_e2e.py x4): a logging call emits a format-string with non-mapping args, crashing log emission on Python 3.14 logging. Environment/version-sensitive; not a migration regression (no code moved here in Phase 2). CI verification required.
- backend/db.sqlite3, .coverage, .pytest_cache, .ruff_cache present in backend/ — verify gitignore coverage.

---

## Phase 3 Addendum — Celery logging format fix (2026-08-12)

**Bug (pre-existing):** 9 webhook/idempotency/e2e tests failed with `TypeError: format requires a mapping` raised inside `logging.LogRecord.getMessage()`. Root cause: Celery's `celery/app/trace.py` helper logs mapping-style messages (`"Task %(name)s[%(id)s] succeeded in %(runtime)ss: %(return_value)s"`) by passing the context dict positionally (`logger.info(fmt, context, extra=...)`), so `record.args = (dict,)` — a tuple. Python logging then executes `msg % (dict,)`, which raises for `%(...)s` placeholders. Surfaced wherever INFO records are actually formatted (tests run tasks eagerly with LOG_LEVEL=DEBUG; production INFO emission would hit the same path).

**Fix (in-repo; no site-packages changes):**
- `sentinel_review/logging_filters.py`: added `MappingArgsFilter`, which rewrites `record.args` from `(dict,)` to `dict` when the message uses mapping-style placeholders, so any handler/formatter can render it. Also hardened `RedactingFilter` to preserve dict args as dicts (it previously re-wrapped a dict into a tuple, which would have undone the normalization).
- `sentinel_review/celery_app.py`: attached `MappingArgsFilter` at logger level to the `celery` and `celery.app.trace` loggers — logger filters run before ANY handler (Django console, pytest capture, JSON formatter).
- `sentinel_review/settings.py`: registered the `mapping_args` filter on the console handler (before `redact`) as a second layer.

**Verification (evidence):**
| Check | Command | Result |
|---|---|---|
| Full suite | `python -m pytest -q` | 352 passed (was 343 passed, 9 failed) |
| Django system check | `python manage.py check` | no issues (0 silenced) |
| Lint | `ruff check` on changed files | 0 errors |
| Compile | py_compile on changed files | OK |

**CI status:** CI runs `python -m pytest` from `backend/` — now green end-to-end.
