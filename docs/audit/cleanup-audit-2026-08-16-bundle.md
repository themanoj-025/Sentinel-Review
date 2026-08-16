# sentinel-review — Session Audit (2026-08-16): Vendored Bundle Provenance

## What was done
The committed `frontend/static/js/bundle.js` (107 KB, minified) had no
provenance record and was loaded without any integrity check.

- **Provenance documented** — `frontend/static/js/README.md` now records
  what's inside (htmx 2.0.10 + Alpine.js 3.15.12 + repo glue in
  `frontend/src/app.js`), the esbuild build process
  (`frontend/esbuild.config.mjs`, `npm run build:js`), that a clean rebuild
  is byte-for-byte reproducible, and the current SHA-256.
- **Integrity enforced** — the digest is pinned as an SRI `integrity`
  attribute on the `<script>` tag in
  `backend/sentinel_review/dashboard/templates/dashboard/base.html`, so a
  drifted artifact is rejected at runtime.
- **CI guard** — new `verify-frontend-build` job in
  `.github/workflows/ci.yml` rebuilds the bundle and fails if the committed
  file diverges from sources.

## Validation
- Clean rebuild produces identical hash
  `8b440509b6d2d7b0d88d4620ce582899a9f66d779f7a248c2462ecffd02e223f`;
  `git diff` on the rebuilt bundle is empty.
- 17 dashboard/template tests pass.
- Commit: `9056895`.

## Note
Whenever `frontend/src/` or the dependency versions change, the bundle must
be regenerated and the SHA-256 in both `README.md` and `base.html` updated
(CI will fail otherwise).
