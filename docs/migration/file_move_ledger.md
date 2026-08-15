# sentinel-review — File Move Ledger

## This pass (2026-08-11)

| Old path | New path | Category | Reason | Risk | Verified |
|---|---|---|---|---|---|
| `docs/migration_summary.md` | `docs/migration/migration_summary.md` | Meta/docs | Consolidate migration records under `docs/migration/` per enterprise standard | Low (docs only) | ✅ `git mv` preserved history; no inbound refs found |
| `docs/architecture.md` (3-line stub) | `docs/architecture.md` (rewritten) | Meta/docs | Stub replaced with real architecture doc | Low | ✅ |
| `docs/folder_structure.md` (stub) | `docs/folder_structure.md` (rewritten) | Meta/docs | Stub listed non-existent `src/`; corrected to `backend/` layout | Low | ✅ |

## Prior pass (v5.0 modernization, commit `194ea6b`)

The v5.0 pass moved the application into the current `backend/`-first layout
and its `docs/project/analysis_report.md` + `docs/technical/*` document the
resulting structure. No per-file ledger was kept for that pass; the
representative moves are:

| Old path | New path | Reason |
|---|---|---|
| (flat root Python) | `backend/sentinel_review/**` | Django project package with per-concern apps |
| (flat tests) | `backend/tests/**` | Tests beside the project |
| (flat frontend assets) | `frontend/src` + `frontend/static` | Build-source vs built-output separation |
| (flat scripts) | `scripts/**` | Operational tooling |

## Non-moves (documented decisions)

| Path | Decision | Reason |
|---|---|---|
| `backend/` (Django) | keep | Launch contract: gunicorn `sentinel_review.wsgi`, `cd backend && …` in Makefile/CI/compose |
| `frontend/` | keep | Build pipeline (esbuild/Tailwind) referenced by package.json; output served by Django |
| `scripts/`, `data/`, `docs/`, `mkdocs.yml` | keep | Canonical locations |
| `backend/db.sqlite3`, `frontend/node_modules/`, `backend/.pytest_cache/`, `backend/.ruff_cache/`, `.coverage` | leave (untracked) | Runtime/build artifacts, correctly gitignored |
