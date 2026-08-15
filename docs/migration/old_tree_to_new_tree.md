# sentinel-review — Old Tree → New Tree

## This pass (2026-08-11)

```
Before                                After
──────                                ─────
docs/migration_summary.md      →      docs/migration/migration_summary.md
docs/architecture.md (3-line stub)    docs/architecture.md (full architecture doc)
docs/folder_structure.md (stub)       docs/folder_structure.md (annotated tree)
—                                     docs/module_dependency.md        (new)
—                                     docs/startup_flow.md             (new)
—                                     docs/package_overview.md         (new)
—                                     docs/migration/old_tree_to_new_tree.md (new)
—                                     docs/migration/file_move_ledger.md     (new)
```

## Prior pass (v5.0 modernization, commit `194ea6b`)

sentinel-review was restructured by the v5.0 pass into the current layout:
all Python consolidated under `backend/` (Django project `sentinel_review/`
with api/dashboard/webhooks/workers/services/models apps), frontend under
`frontend/`, ops under `scripts/`, docs under `docs/`, plus `data/` and the
MkDocs site. The legacy v5.0 record was a stub template; this pass replaces
the stubs with real content.

## No-code-move rationale (this pass)

The layout already conforms (backend/frontend/scripts/data/docs + canonical
root metadata; Docker/Compose/Makefile/CI all reference `backend/…` paths).
This pass only consolidates the migration record and completes the Phase-6
doc suite — zero code changed.
