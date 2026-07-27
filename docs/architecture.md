# Sentinel Review — Architecture

> *Last updated: 2026-07-27 (updated to reflect Chart.js, log redaction, deployment configs)*

## Overview

Sentinel Review is an autonomous GitHub PR-review agent. It monitors pull request events via webhooks, fetches diffs with full repo context, analyzes changes using a combination of LLM-based reasoning and static analysis (Semgrep), and posts severity-ranked, line-anchored inline review comments.

```ascii
                GitHub (PR + reaction events)
                          │
                    webhook (HMAC-signed)
                          │
                          ▼
              ┌─────────────────────────┐
              │   Django Webhook View   │  returns 200 fast
              │   POST /webhooks/github │
              └────────┬────────────────┘
                       │  enqueue Celery task
                       ▼
              ┌─────────────────┐
              │     Redis       │  broker / result backend
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │  Celery Worker  │  review_pull_request / process_reaction
              │  (2 workers)    │
              └────────┬────────┘
                       │
        ┌──────────────┼──────────────────┐
        │              │                  │
        ▼              ▼                  ▼
  ┌──────────┐  ┌───────────┐  ┌──────────────────┐
  │ GitHub   │  │ Anthropic │  │   PostgreSQL     │
  │ REST API │  │ / OpenAI  │  │  (all models)    │
  └──────────┘  └───────────┘  └────────┬─────────┘
                                        │
                                        ▼
                              ┌──────────────────┐
                              │  Django Dashboard │
                              │  (Templates +     │
                              │   HTMX + Alpine)  │
                              └──────────────────┘
```

## Service Topology (Docker Compose)

| Service | Image | Purpose | Port |
|---------|-------|---------|------|
| `web` | Custom (Django + gunicorn) | HTTP server: webhooks, API, dashboard | `8000` |
| `worker` | Custom (Celery) | Background PR review + feedback processing | — |
| `redis` | `redis:7-alpine` | Celery broker + result backend | `6379` |
| `db` | `postgres:16-alpine` | Primary database | `5432` |
| `flower` | `mher/flower:2.0` | Celery monitoring UI | `5555` |

## Component Architecture

### 1. Webhook Layer (`sentinel_review/webhooks/`)

```
POST /webhooks/github
  → HMAC-SHA256 signature verification (required)
  → Route by X-GitHub-Event header
    ├── pull_request (opened|synchronize) → enqueue review_pull_request
    ├── pull_request_review_comment → enqueue process_reaction
    └── other → 200 OK (ignored)
```

**Key design decisions:**
- HMAC verification happens **before any other processing** — tampered payloads are rejected at the first gate
- Response returns immediately (202 Accepted) — all heavy work is deferred to Celery
- Uses Django's `@csrf_exempt` and `@require_POST` decorators

### 2. Celery Workers (`sentinel_review/workers/`)

#### `review_pull_request` (queue: `reviews`)
1. **Upsert records** — Installation, Repo, PullRequest, Review (status: PROCESSING)
2. **Check private-repo opt-in** — skip if private and not explicitly opted in
3. **Fetch diff** — GitHub API (`GET /repos/{owner}/{repo}/pulls/{pr}` with `Accept: application/vnd.github.v3.diff`)
4. **Fetch repo context** — `CONTRIBUTING.md`, linter configs (`.eslintrc`, `pyproject.toml`, etc.)
5. **Fetch file contents** — full source of changed files for context-aware review
6. **LLM analysis** — prompt with structured output schema → Pydantic validated
7. **Semgrep analysis** — independent static analysis signal (optional, non-fatal if unavailable)
8. **Merge & filter** — cross-reference findings, deduplicate, apply repo config filters
9. **Post inline review** — GitHub API (`POST /repos/{owner}/{repo}/pulls/{pr}/reviews`)
10. **Persist** — save Review + Comment records, update latencies and token costs

#### `process_reaction` (queue: `feedback`)
1. Look up Comment by `github_comment_id`
2. Fetch reactions from GitHub API
3. Store 👍/👎 as Feedback records (deduplicated by `(comment, reactor_login, reaction)`)

### 3. LLM Provider (`sentinel_review/workers/llm.py`)

Abstract interface with two implementations:

| Provider | Model | Auth | Structured Output |
|----------|-------|------|-------------------|
| `AnthropicProvider` | `claude-sonnet-4-20250514` (configurable) | `ANTHROPIC_API_KEY` | Tool-use mode (built-in JSON schema) |
| `OpenAIProvider` | `gpt-4o` (configurable) | `OPENAI_API_KEY` | `response_format: json_schema` |

Selection via `LLM_PROVIDER` env var (`"anthropic"` or `"openai"`).

### 4. GitHub Client (`sentinel_review/workers/github_client.py`)

Authentication flow:
```
GitHub App Private Key (PEM)
  → JWT (RS256, 10min expiry, 60s clock drift tolerance)
    → Installation Access Token (1hr, cached and auto-refreshed)
      → Authenticated GitHub API calls
```

### 5. Django Dashboard (`sentinel_review/dashboard/`)

Python-rendered templates with HTMX + Alpine.js:

| Route | View | Description |
|-------|------|-------------|
| `/` | `dashboard_home` | Overview stats, recent reviews, status distribution |
| `/repos/` | `repo_list` | Searchable repository list with review/comment counts |
| `/repos/{id}/` | `repo_detail` | Config panel (HTMX), review history, per-repo stats |
| `/reviews/{id}/` | `review_detail` | All comments from a review run with upvote/downvote counts |
| `/stats/` | `stats_overview` | Usefulness rate, latency, category volume, per-repo breakdown — with Chart.js visualizations (bar, donut, line, and stacked bar charts) |

### 6. Database Schema (PostgreSQL)

```
Installation (1) ──→ (N) Repo (1) ──→ (N) PullRequest (1) ──→ (N) Review (1) ──→ (N) Comment (1) ──→ (N) Feedback
```

All foreign keys have `CASCADE` delete. Unique constraints on:
- `(installation, github_repo_id)` for Repo
- `(repo, github_pr_number)` for PullRequest
- `(comment, reactor_login, reaction)` for Feedback

## Data Flow for a PR Review

```
1. GitHub sends POST /webhooks/github with PR event
2. Django view verifies HMAC signature
3. View enqueues Celery task (review_pull_request.delay)
4. View returns 202 (within 10s GitHub timeout)
5. Worker pops task from Redis "reviews" queue
6. Worker upserts DB records (Installation → Repo → PR → Review)
7. Worker checks private-repo opt-in → skips if not allowed
8. Worker fetches diff, file contents, repo conventions via GitHub API
9. Worker sends diff + context to LLM with structured output schema
10. LLM returns JSON validated by Pydantic (Finding + ReviewOutput)
11. Optional: Semgrep runs on file contents, findings merged
12. Worker deduplicates, filters by repo config, enforces max-comment limit
13. Worker posts inline comments via GitHub "create review" API
14. Worker saves Comment records, updates Review with latency/token cost
15. Worker marks Review as COMPLETED
```

## Security Architecture

See `security-notes.md` for full details.

- **Webhook**: HMAC-SHA256 with constant-time comparison
- **GitHub App**: JWT → short-lived installation tokens, never persisted
- **Secrets**: Loaded from environment / mounted `.secrets/` directory, never in repo
- **Private repos**: Explicit opt-in per repo via `Repo.config.private_repo_opt_in`
- **Log redaction**: Token-like patterns redacted before structured logging via `sentinel_review/logging_filters.RedactingFilter` (9 regex patterns covering API keys, tokens, passwords, JWTs, DB URLs)
- **CI Semgrep**: Scans project codebase for security issues on every push
- **Deployment**: One-command deploy via `render.yaml` (Render.com) or `fly.toml` (Fly.io) with web + worker + PostgreSQL + Redis in each config

## Testing Strategy

| Layer | Tool | Scope |
|-------|------|-------|
| Unit | pytest + pytest-django | Models, schemas, helpers, HMAC |
| Integration | pytest + respx + unittest.mock | GitHub API, webhooks, Celery tasks |
| CI | GitHub Actions | Ruff lint, pytest coverage, Docker build, Semgrep |

**Test coverage areas:**
- HMAC verification (valid, invalid, tampered, dev-mode bypass)
- Pydantic schema validation (valid/invalid/malformed LLM output)
- GitHub client auth flow (JWT + installation token)
- LLM provider abstraction (Anthropic/OpenAI factory, prompt building)
- Semgrep parsing and merge logic (high-confidence agreement marking)
- Model schema round-trip (6 models, constraints, cascades)
- Full pipeline (mocked GitHub + LLM → DB persistence)
- Feedback loop (reaction capture, deduplication, usefulness rate)
- Planted-bug fixtures (6 categories: SQL injection, secrets, deserialization, etc.)

## Configuration

All configuration via environment variables (see `.env.example`):

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DJANGO_SECRET_KEY` | Yes | — | Django cryptographic signing |
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `CELERY_BROKER_URL` | Yes | — | Redis URL for Celery |
| `GITHUB_APP_ID` | Yes | — | GitHub App ID |
| `GITHUB_APP_PRIVATE_KEY_B64` | Yes* | — | Base64-encoded private key |
| `WEBHOOK_SECRET` | Yes | — | GitHub webhook secret |
| `LLM_PROVIDER` | No | `anthropic` | LLM backend selection |
| `ANTHROPIC_API_KEY` | Yes* | — | Anthropic API key |
| `OPENAI_API_KEY` | Yes* | — | OpenAI API key |

*\*At least one set of credentials is required (GitHub + LLM provider).*
