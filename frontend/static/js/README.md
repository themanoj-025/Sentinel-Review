# `bundle.js` — provenance & integrity

`bundle.js` is a **committed build artifact** (deliberately checked in so a
fresh clone serves the frontend without a Node build step). It is **not**
hand-written or AI-generated code — it is the minified esbuild output of the
project's own frontend sources plus its two runtime dependencies.

## What's inside

| Component | Version | Source |
|---|---|---|
| htmx | 2.0.10 | `htmx.org` npm package (declared in `frontend/package.json`) |
| Alpine.js | 3.15.12 | `alpinejs` npm package (declared in `frontend/package.json`) |
| App glue code | — | `frontend/src/app.js`, `frontend/src/chart-loader.js` (repo-owned) |

The file is one IIFE bundle produced by `esbuild` (`format: iife`,
`minify: true`, `target: es2020`) — see `frontend/esbuild.config.mjs`.

## How to rebuild

```bash
cd frontend
npm ci
npm run build:js
```

Rebuilding from a clean checkout is **reproducible**: the generated file is
byte-for-byte identical to the committed one (the CI job below enforces this).

## Integrity checksum

Current SHA-256 (of the committed file):

```
8b440509b6d2d7b0d88d4620ce582899a9f66d779f7a248c2462ecffd02e223f  bundle.js
```

Verify:

```bash
sha256sum frontend/static/js/bundle.js
```

The same digest is baked into the page as an SRI `integrity` attribute
(`sha256-8b4405…`) in
`backend/sentinel_review/dashboard/templates/dashboard/base.html`, so any
drift between this file and what the browser loads is rejected at runtime.

## When to update

1. Change `frontend/src/` or the dependency versions in `frontend/package.json`.
2. Run `npm run build:js`.
3. Commit the regenerated `bundle.js` **and** update the SHA-256 above and the
   SRI `integrity` attribute in `base.html`.

CI (`verify-frontend-build` job in `.github/workflows/ci.yml`) rebuilds the
bundle and fails if the committed file is out of sync with the sources.
