# Sentinel Review — Docker Guide

## Quick start

```bash
cp .env.example .env   # rotate DJANGO_SECRET_KEY, WEBHOOK_SECRET, FLOWER creds
docker compose up -d
```

Starts PostgreSQL (`:5432`), Redis (`:6379`), Django web (`:8000`),
Celery worker, and Flower (`:5555`).

> **⚠️ Rotate the default secrets before any real deployment** — the
> compose file warns inline: `DJANGO_SECRET_KEY`, `WEBHOOK_SECRET`,
> `FLOWER_USER`/`FLOWER_PASSWORD` default to `change-me`/`sentinel`.

## Environment

Key vars: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`,
`DATABASE_URL`, `REDIS_URL`, `CELERY_*`, `WEBHOOK_SECRET`,
`GITHUB_APP_*`, `LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`,
`FLOWER_USER`/`FLOWER_PASSWORD`.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `web` crash-loops | Migrations run at boot; check `docker compose logs web` |
| Flower 401 | Set `FLOWER_USER`/`FLOWER_PASSWORD` in `.env` |
| 502 from web | `DJANGO_ALLOWED_HOSTS` must include the host you reach it on |
