# sentinel-review — Folder Structure

```
sentinel-review/
├── backend/                      # Django project (all backend code)
│   ├── manage.py                 # Django management entry
│   ├── sentinel_review/          # Project package
│   │   ├── settings.py           #   env-driven settings
│   │   ├── urls.py / wsgi.py     #   URL config + WSGI app
│   │   ├── celery_app.py         #   Celery app (queues: reviews, feedback, default)
│   │   ├── api/                  #   REST API (views, serializers, health, metrics)
│   │   ├── dashboard/            #   Server-rendered dashboard (templates + views)
│   │   ├── webhooks/             #   GitHub webhook intake + signature verification
│   │   ├── workers/              #   Async review pipeline (LLM, Semgrep, GH client, …)
│   │   ├── services/             #   stats + notification services
│   │   ├── models/               #   ORM models (repo, PR, review, comment, feedback)
│   │   ├── migrations/           #   DB migrations (0001–0003)
│   │   └── apps.py, admin.py, logging_filters.py
│   ├── tests/                    # pytest suite (20+ modules, fixtures/)
│   ├── conftest.py               # root pytest config (backend/)
│   └── pytest.ini
├── frontend/                     # Static assets (vanilla JS + Tailwind + esbuild)
│   ├── src/                      #   JS sources + input.css
│   ├── static/                   #   Built output (bundle.js, output.css)
│   ├── esbuild.config.mjs
│   └── tailwind.config.js
├── scripts/                      # Ops: gha_review, run_evaluation, build_eval_set, …
├── data/                         # Evaluation sets (eval_set.json)
├── docs/                         # Documentation suite (MkDocs site)
│   ├── migration/                # Migration records
│   └── architecture · design · product · project · reference · technical · community
├── .github/                      # CI (ci, load-test, sbom, security-scan) + templates
├── mkdocs.yml                    # MkDocs site config
├── Dockerfile                    # Multi-stage; CMD → gunicorn sentinel_review.wsgi
├── docker-compose.yml            # web + worker + flower + postgres + redis
├── render.yaml / fly.toml        # Deployment configs
├── Makefile                      # test / migrate / collectstatic targets
├── pyproject.toml / requirements*.txt
└── README.md · LICENSE · AGENTS.md · CODEOWNERS · .env.example
```

## Layout rules

- **Everything Python lives under `backend/`** — Django project package
  `sentinel_review/`, tests, pytest config; Makefile/CI `cd backend && …`.
- **Feature cohesion** — webhooks, workers, api, dashboard are separate Django
  apps under the project package; models are their own app for single import
  graph.
- **Frontend is build-output only** — sources in `frontend/src`, bundles in
  `frontend/static`, served by Django (`collectstatic`).
- **Runtime state never tracked** — `backend/db.sqlite3`, `node_modules/`,
  `.coverage`, caches are gitignored.
