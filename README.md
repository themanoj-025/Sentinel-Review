<div align="center">
  <br/>
  <h1>🛡️ Sentinel Review</h1>
  <p>
    <em>"The senior engineer who never gets tired."</em>
  </p>
  <p>
    An autonomous GitHub PR-review agent that reads diffs in full repo context,
    produces severity-ranked, line-anchored review comments, and proves its own
    usefulness with real feedback metrics.
  </p>
  <br/>

  <!-- Badges -->
  <p>
    <a href="https://github.com/sentinel-review/sentinel-review/actions/workflows/ci.yml">
      <img src="https://img.shields.io/github/actions/workflow/status/sentinel-review/sentinel-review/ci.yml?branch=main&label=CI&logo=github&style=flat-square" alt="CI Status"/>
    </a><a href="#">
      <img src="https://img.shields.io/badge/tests-352%20passing-brightgreen?style=flat-square&logo=pytest" alt="Tests"/></a>
    <a href="#">
      <img src="https://img.shields.io/badge/python-3.12-blue?style=flat-square&logo=python" alt="Python"/>
    </a>
    <a href="#">
      <img src="https://img.shields.io/badge/django-5.1-success?style=flat-square&logo=django" alt="Django"/>
    </a>
    <a href="#">
      <img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="License"/>
    </a>
    <a href="https://www.docker.com/">
      <img src="https://img.shields.io/badge/docker-compose-2496ED?style=flat-square&logo=docker" alt="Docker"/>
    </a><a href="#">
      <img src="https://img.shields.io/badge/audit-5.7%E2%9E%A19.0-blue?style=flat-square" alt="Audit Score"/></a>
  </p>

  <!-- Links -->
  <p>
    <a href="#-features">Features</a> •
    <a href="#️-architecture">Architecture</a> •
    <a href="#-quick-start">Quick Start</a> •
    <a href="#-case-study-the-audit--beforeafter-story">The Audit Story</a> •
    <a href="https://github.com/sentinel-review/sentinel-review/issues">Report Bug</a>
  </p>
  <br/>
</div>

---

## 📋 Table of Contents

- [Why Sentinel Review?](#-why-sentinel-review)
- [Features](#-features)
- [Architecture](#️-architecture)
- [Quick Start](#-quick-start)
- [Configuration](#-configuration)
- [Dashboard & API](#️-dashboard--api)
- [Tech Stack](#️-tech-stack)
- [Project Structure](#-project-structure)
- [Case Study: The Audit → Before/After Story](#-case-study-the-audit--beforeafter-story)
- [Demo: Self-Review](#-demo-self-review)
- [Development](#-development)
- [Testing & CI](#-testing--ci)
- [Deployment](#-deployment)
- [Roadmap](#️-roadmap)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🎯 Why Sentinel Review?

Code review is the highest-leverage quality practice in software engineering — and the hardest to scale.

**The problem with existing tools:**

| Tool Type | Strengths | Weaknesses |
|-----------|-----------|------------|
| **Linters / Static analyzers** | Fast, deterministic, no false positives | Miss logic bugs, security context, design issues |
| **LLM-based reviewers** | Catch semantic issues | Generic summaries, high noise, not line-anchored |
| **Human reviewers** | Deep understanding | Expensive, slow, bottleneck in delivery |

**Sentinel Review bridges this gap** by combining:
- 🧠 **LLM-based reasoning** (Claude / GPT-4o) for semantic understanding
- 🔒 **Deterministic static analysis** (Semgrep) for high-confidence security signals
- 📍 **Line-anchored comments** posted directly on the PR diff, not summary blobs
- 📊 **Feedback-driven improvement** — every comment can be 👍/👎'd, usefulness tracked

---

## ✨ Features

### 🏆 Tier 1 — Core

| Feature | Implementation | Why It Matters |
|---------|---------------|----------------|
| **Line-anchored comments** | Posted via GitHub's Create Review API | Developers see the issue in context |
| **Severity-ranked** | `blocking` / `warning` / `nit` | Prioritize fixes — don't waste time on nits |
| **Categorized** | `bug` / `style` / `security` / `suggestion` | Filter by category per repo |
| **Pydantic-validated output** | Strict JSON schema with corrective retry | Malformed LLM output never reaches your PR |
| **HMAC webhook verification** | Constant-time `hmac.compare_digest()` | Tampered payloads rejected at the first gate |
| **Async processing** | Celery + Redis — returns 202 in <10s | Never hits GitHub's webhook timeout |
| **Staged pipeline** | 7 named stages with typed context object | Each stage independently testable |

### 🚀 Tier 2 — Production Ready

| Feature | Implementation | Why It Matters |
|---------|---------------|----------------|
| **Circuit breaker** | CLOSED/OPEN/HALF_OPEN for GitHub + LLM | Survives provider outages without thundering herd |
| **LLM response cache** | SHA256 diff-hash → Redis/in-memory | Re-review unchanged diffs in <1ms instead of ~2s |
| **Webhook idempotency** | Delivery-ID dedup via Redis + in-memory | Duplicate GitHub deliveries don't create duplicate reviews |
| **Health endpoints** | `/health/` (liveness) + `/health/ready/` (readiness) | Load balancer aware, Docker healthchecks |
| **Rate limiting** | DRF throttle classes (100/hr anon, 1000/hr auth) | Prevents abuse of API and webhook endpoints |
| **Auth controls** | `IsAuthenticated` on write endpoints | No open forgery vectors |
| **Startup validation** | `ImproperlyConfigured` on missing secrets | Never runs with insecure defaults |
| **OpenAPI docs** | `drf-spectacular` at `/api/schema/` | Auto-generated, interactive API documentation |
| **Prometheus metrics** | Latency, error rate, queue depth, cache hit rate | Real-time observability into pipeline health |
| **Structured logging** | JSON output with `task_id`, `module`, `latency` | Machine-parseable logs for log aggregation |
| **Sentry integration** | Django + Celery + LLM boundary | Error tracking with full context |

### 🧠 Tier 3 — AI Differentiators

| Feature | Implementation | Why It Matters |
|---------|---------------|----------------|
| **Semgrep integration** | Runs independently, merges with LLM findings | Catches what LLMs miss |
| **High-confidence marking** | LLM + Semgrep agreement = `high_confidence` | Trust findings backed by two signals |
| **Corrective retry** | Shows validation error to model, retries once | Recovers from malformed JSON without losing the review |
| **LLM cache** | SHA256(diff+context) key, Redis + in-memory | Avoids paying for redundant API calls |
| **Feedback loop** | 👍/👎 reactions via webhook | Proves its own usefulness with real metrics |
| **Multi-model support** | Anthropic + OpenAI, switch via env var | Choose your provider without code changes |
| **.sentinel-ignore** | Glob patterns for excluded files/directories | Skip generated files, vendor code, test artifacts |
| **GHA execution mode** | Composite GitHub Action (no server needed) | Run reviews as a CI step — zero infrastructure |
| **Self-review demo** | Bot catches `pickle.load()` in its own code | "The bot reviewed its own code" — end-to-end proof |

---

## 🏗️ Architecture

### Pipeline Architecture (Post-Remediation)

The core review pipeline is a **staged, modular** design. Each stage is independently testable, receives and returns a typed `ReviewContext` object, and can fail without crashing the entire pipeline:

```
                    ┌─────────────────────────────┐
                    │           GitHub             │
                    │  (PR events + reactions)     │
                    └──────────────┬──────────────┘
                                   │ POST /webhooks/github
                                   │ HMAC-SHA256 signed
                                   ▼
                    ┌─────────────────────────────┐
                    │     Django Webhook View      │
                    │   • Verify HMAC signature    │
                    │   • Idempotency check        │
                    │   • Route by event type      │
                    │   • Enqueue Celery task      │
                    │   • Return 202 (< 10s)       │
                    └──────────────┬──────────────┘
                                   │ review_pull_request.delay()
                                   ▼
                    ┌─────────────────────────────┐
                    │         Redis                │
                    │   Celery broker + backend    │
                    │   + LLM response cache       │
                    │   + Delivery dedup           │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │       Celery Worker          │
                    │  ┌─────────────────────┐     │  Staged Pipeline:
                    │  │ 1. UpsertStage      │     │  ──────────────
                    │  │ 2. FetchDiffStage   │     │  Each stage has
                    │  │ 3. FetchContextStage │    │  clear I/O via
                    │  │ 4. LLMReviewStage   │     │  ReviewContext
                    │  │    ├─ cache_get()   │     │  dataclass
                    │  │    ├─ hit → skip    │     │
                    │  │    └─ miss → API    │     │
                    │  │ 5. SemgrepStage     │     │
                    │  │ 6. DedupeStage      │     │
                    │  │ 7. PostCommentsStage│     │
                    │  └─────────────────────┘     │
                    └──────────────┬──────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────────┐
│   GitHub REST API │   │   LLM Provider   │   │     PostgreSQL       │
│   (circuit        │   │   (circuit       │   │  • 6 models          │
│    breaker)       │   │    breaker)      │   │  • composite indexes │
└──────────────────┘   └──────────────────┘   └──────────┬───────────┘
                                                          │
                                                          ▼
                                              ┌──────────────────────┐
                                              │  Django Dashboard    │
                                              │  + HTMX + Alpine.js  │
                                              │  + Chart.js charts   │
                                              │  + Tailwind (compiled)│
                                              └──────────────────────┘
```

**Also available as a GitHub Action (no server needed):**
```
  PR event → actions/checkout@v4 → setup-python@v5 → scripts/gha_review.py
  → git diff → LLM call → inline review comments → JSON report artifact
```

### Data Flow — A Review in 14 Steps

```
 1.  🔔 GitHub sends POST /webhooks/github (pull_request opened/synchronize)
 2.  🔐 HMAC-SHA256 signature verified (constant-time)
 3.  🔁 Idempotency check — same delivery_id? → 200 OK (skip)
 4.  📤 Enqueue review_pull_request.delay() → Redis "reviews" queue
 5.  ✅ Return 202 Accepted (< 10s)
 6.  ⚙️ Worker pops task from Redis
 7.  💾 UpsertStage — DB records: Installation → Repo → PR → Review (status: PROCESSING)
 8.  🔒 Private repo check — skip if not opted in
 9.  📡 FetchDiffStage — diff + file contents via GitHub API (circuit breaker protected)
10.  📚 FetchContextStage — repo conventions, .sentinel-ignore, linter configs (non-fatal)
11.  🧠 LLMReviewStage — cache check → hit (skip) / miss (call LLM with retry → store)
12.  🔬 SemgrepStage — static analysis, merged with LLM findings (non-fatal)
13.  🧹 DedupeStage — merge, .sentinel-ignore filter, dedup by (file, line, category), limit
14.  📝 PostCommentsStage — inline comments via GitHub API, save to DB, cache LLM result
```

### Service Topology

| Service | Base Image | Purpose | Port | Healthcheck |
|---------|-----------|---------|------|-------------|
| `web` | Custom (Django + gunicorn) | HTTP: webhooks, API, dashboard, health, metrics | `8000` | `GET /health/` |
| `worker` | Custom (Celery) | Background review + feedback processing | — | Celery ping |
| `redis` | `redis:7-alpine` | Celery broker + result backend + LLM cache | `6379` | `redis-cli ping` |
| `db` | `postgres:16-alpine` | Primary database | `5432` | `pg_isready` |
| `flower` | `mher/flower:2.0` | Celery monitoring (basic-auth) | `5555` | — |

---

## 🚀 Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) & [Docker Compose](https://docs.docker.com/compose/install/) v2.20+
- A [GitHub App](https://docs.github.com/en/apps/creating-github-apps)
- An [Anthropic](https://console.anthropic.com/) or [OpenAI](https://platform.openai.com/) API key

### One-Command Start

```bash
# 1. Clone
git clone https://github.com/sentinel-review/sentinel-review.git
cd sentinel-review

# 2. Configure
cp .env.example .env
# → Edit .env with your GitHub App credentials and LLM API key

# 3. Start (first build: 30-60s)
docker compose up --build
```

**That's it.** Once all services are healthy:

| Service | URL | Purpose |
|---------|-----|---------|
| 🖥️ **Dashboard** | `http://localhost:8000` | Web UI — repos, reviews, stats |
| 🔌 **API** | `http://localhost:8000/api/` | REST endpoints (paginated, filtered) |
| 📄 **API Docs** | `http://localhost:8000/api/docs/` | Swagger UI (OpenAPI) |
| 🔧 **Admin** | `http://localhost:8000/admin/` | Django admin |
| 🌸 **Flower** | `http://localhost:5555` | Celery monitoring (basic-auth) |
| ❤️ **Health** | `http://localhost:8000/health/` | Liveness/readiness |
| 📊 **Metrics** | `http://localhost:8000/metrics` | Prometheus metrics |
| 🔗 **Webhook** | `http://localhost:8000/webhooks/github/` | GitHub webhook receiver |

### GitHub App Setup

<details>
<summary><strong>Step-by-step (click to expand)</strong></summary>

1. **GitHub Settings → Developer settings → GitHub Apps → New GitHub App**
2. Configure:
   - **App name:** `sentinel-review` (or your choice)
   - **Homepage URL:** `https://github.com/sentinel-review/sentinel-review`
   - **Webhook URL:** `https://your-public-url.com/webhooks/github/`
   - **Webhook secret:** Strong random string → copy to `.env` as `WEBHOOK_SECRET`
3. **Permissions** (least-privilege):
   - Repository contents: **Read-only**
   - Pull requests: **Read & Write**
   - Repository metadata: **Read-only**
4. **Subscribe to events:**
   - `Pull request`
   - `Pull request review comment`
5. Generate **private key** → download `.pem` → save as `.secrets/github-app-private-key.pem`
6. Copy **App ID**, **Client ID**, **Client Secret** to `.env`

</details>

For local dev, expose your webhook:

```bash
ngrok http 8000
# → Copy the https:// URL to your GitHub App's webhook URL
```

### GitHub Actions Mode (No Server Needed)

```yaml
# .github/workflows/sentinel-review.yml
name: Sentinel Review
on: [pull_request]
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: sentinel-review/sentinel-review/.github/actions/sentinel-review@main
        with:
          github-token: ${{ github.token }}
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

---

## 🔧 Configuration

### Required

| Variable | Description |
|----------|-------------|
| `DJANGO_SECRET_KEY` | Django cryptographic signing key (required — app fails to start if unset) |
| `WEBHOOK_SECRET` | GitHub webhook shared secret (required — app fails to start if unset) |
| `GITHUB_APP_ID` | GitHub App ID |
| `GITHUB_APP_PRIVATE_KEY_B64` | Base64-encoded private key |

### LLM Provider

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `openai` |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Claude model ID |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model ID |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level |
| `JSON_LOG` | `False` | Enable structured JSON logging |
| `SENTRY_DSN` | — | Sentry DSN for error tracking |
| `METRICS_ENABLED` | `False` | Enable Prometheus `/metrics` endpoint |
| `FLOWER_USER` | — | Flower dashboard username (basic auth) |
| `FLOWER_PASSWORD` | — | Flower dashboard password (basic auth) |

---

## 🖥️ Dashboard & API

### Web Dashboard

| Page | Route | Highlights |
|------|-------|------------|
| **Home** | `/` | KPI cards, recent reviews, status distribution, 7-day trend |
| **Repositories** | `/repos/` | Searchable list with review/comment counts (HTMX) |
| **Repo Detail** | `/repos/{id}/` | Config panel (HTMX), review history, per-repo stats |
| **Review Detail** | `/reviews/{id}/` | All comments with 👍/👎 counts |
| **Analytics** | `/stats/` | Chart.js charts: usefulness bar, volume donut, trending line, upvote/downvote breakdown |

### REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/installations/` | GET | List installations (paginated, searchable) |
| `/api/v1/repos/` | GET | List repos (`?search=`, paginated) |
| `/api/v1/repos/{id}/config/` | PATCH | Update repo configuration |
| `/api/v1/pull-requests/` | GET | List PRs (`?repo_id=`, paginated) |
| `/api/v1/reviews/` | GET | List reviews (`?pull_request_id=`, `?status=`, paginated) |
| `/api/v1/comments/` | GET | List comments (`?review_id=`, `?category=`, `?severity=`, paginated) |
| `/api/v1/feedback/` | POST | Submit manual feedback (auth required) |
| `/api/v1/stats/` | GET | Usefulness rate & metrics (`?repo=`) |

### Operational Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/health/` | Liveness check |
| `/health/ready/` | Readiness check (DB + Redis) |
| `/metrics` | Prometheus metrics (if enabled) |
| `/api/schema/` | OpenAPI schema (JSON) |
| `/api/docs/` | Swagger UI |

---

## 🛠️ Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Backend** | Django 5.x + DRF | Batteries-included: auth, ORM, admin, API framework |
| **Async jobs** | Celery + Redis | Fast broker, task routing, Flower monitoring |
| **Database** | PostgreSQL 16 | JSONField for flexible config, robust for production |
| **Frontend** | Django Templates + HTMX + Alpine.js | Python-rendered, zero Node runtime, ~15KB JS |
| **Charts** | Chart.js 4.x | Server-rendered data, dark theme optimized |
| **LLM** | Claude Sonnet / GPT-4o | Strong structured output via tool-use mode |
| **Validation** | Pydantic v2 | Strict schema — malformed output never reaches GitHub |
| **Static analysis** | Semgrep | Deterministic security signal, merged with LLM |
| **GitHub API** | PyJWT + httpx | JWT auth → installation tokens, inline comments |
| **Testing** | pytest + pytest-django + respx + mypy | 352 tests, 91% coverage, mocked HTTP/LLM at every boundary |
| **CI/CD** | GitHub Actions | Ruff lint → pytest (PostgreSQL) → Docker build → Semgrep scan |
| **Infrastructure** | Docker + docker-compose | Single-command local dev, 5 services |

---

## 📁 Project Structure

```
sentinel-review/
├── backend/
│   ├── sentinel_review/
│   │   ├── __init__.py          # Celery app initialization
│   │   ├── apps.py              # Django AppConfig
│   │   ├── celery_app.py        # Celery application
│   │   ├── settings.py          # Django settings (startup validation)
│   │   ├── urls.py              # Root URL config
│   │   ├── logging_filters.py   # Log redaction + JSON formatter
│   │   ├── models/              # 6 Django ORM models
│   │   ├── webhooks/            # GitHub webhook + HMAC verification
│   │   ├── workers/             # Pipeline stages, LLM, GitHub, cache, circuit breaker
│   │   ├── dashboard/           # Server-rendered dashboard (5 pages)
│   │   └── api/                 # DRF REST API + health + metrics
│   ├── tests/
│   │   ├── test_e2e.py          # 6 E2E tests
│   │   ├── test_cache.py        # 19 cache tests
│   │   ├── test_circuit_breaker.py # 15 circuit breaker tests
│   │   ├── test_ignore_rules.py # 26 .sentinel-ignore tests
│   │   ├── test_gha_review.py   # 18 GHA runner tests
│   │   ├── test_health.py       # 8 health endpoint tests
│   │   ├── test_metrics.py      # 4 metrics tests
│   │   ├── test_logging.py      # 8 JSON logging tests
│   │   ├── test_startup.py      # 4 startup/auth tests
│   │   ├── test_signature.py    # 10 HMAC tests
│   │   ├── test_schemas.py      # 22 Pydantic tests
│   │   └── ...                  # 22 test files total (352 tests)
│   ├── conftest.py
│   ├── manage.py
│   └── pytest.ini
├── .github/
│   ├── workflows/ci.yml         # 6-job CI pipeline: lint → mypy → test → docker → semgrep → compose
│   └── actions/sentinel-review/ # GHA composite action
├── docs/
│   ├── index.md                 # mkdocs home page
│   ├── architecture.md
│   ├── decisions.md             # 22 ADRs
│   ├── limitations.md           # Known limitations
│   ├── security-notes.md
│   ├── evaluation-report.md     # Multi-model comparison
│   ├── grafana/                 # Grafana dashboard + alerts
│   └── demo/                    # Self-review demo
├── scripts/
│   ├── run_evaluation.py        # Evaluation runner
│   ├── run_comparison.py        # Multi-model comparison
│   ├── build_eval_set.py        # Eval set builder
│   └── gha_review.py            # GHA entry point
├── CHANGELOG.md
├── CODEOWNERS
├── docker-compose.yml           # 5 services + healthchecks
├── Dockerfile
└── requirements*.txt            # Prod + dev split
```

---

## 📊 Case Study: The Audit → Before/After Story

### The Problem

This project started as a functional MVP — working pipeline, 157 tests, feedback loop, dashboard. But a comprehensive **28-category production audit** revealed critical gaps:

| Audit Finding | Severity | Example |
|:--------------|:--------:|:--------|
| `AllowAny` on API write endpoints | 🔴 Critical | Anyone could POST feedback without auth |
| Insecure default secrets | 🔴 Critical | `SECRET_KEY` fell back to dev value in production |
| Blanket `except Exception` | 🔴 Critical | `ProgrammingError`, `KeyError`, `TypeError` all silently swallowed |
| 250-line God function | 🔴 High | `review_pull_request` did 7 things sequentially |
| No pagination on any API | 🟠 Medium | 10K repos? 10K reviews? One giant JSON response |
| No health checks | 🟠 Medium | Orchestrator can't tell if the app is alive |
| No rate limiting | 🟠 Medium | `/webhooks/github` is public |
| Log redaction matches git SHAs | 🟢 Low | `a1b2c3d4e5...` redacted in logs |
| No E2E test | 🟠 Medium | Pipeline only tested in pieces |

**Overall audit score: 5.7/10.** Not production-ready.

### The Remediation

We executed a three-stage remediation plan spanning **31 items** across 4 priority tiers:

#### P0 — Critical (7 items)
```diff
+ API auth: FeedbackViewSet → IsAuthenticated, StatsViewSet → IsAuthenticatedOrReadOnly
+ Startup validation: ImproperlyConfigured if secrets unset
+ Webhook signature: returns False (not True) when unset
+ requirements: cleaned, split into prod/dev
+ semgrep-action: pinned to SHA (no @v1)
+ Migration: consolidated to single 0001_initial.py
+ TemplateSyntaxError: fixed in stats.html
```

#### P1 — Structural (10 items)
```diff
+ 7-stage pipeline architecture with typed ReviewContext
+ Specific exception handling (no more blanket except)
+ LLM corrective retry on validation failure
+ Webhook idempotency via delivery-ID dedup
+ API pagination (50/page) + SearchFilter
+ /health/ and /health/ready/ endpoints
+ DRF throttle classes (100/1000 per hour)
+ Composite indexes on (review, category) and (comment, reaction)
+ Single httpx.Client reuse
+ 6 E2E tests covering full pipeline
```

#### P2 — Reliability & Observability (8 items)
```diff
+ JSON structured logging (controlled by JSON_LOG env var)
+ Sentry integration (conditionally via SENTRY_DSN)
+ Prometheus /metrics endpoint (latency, errors, queue depth, cache rate)
+ Circuit breaker for GitHub API + LLM calls
+ Log redaction: removed false-positive SHA pattern
+ HTMX loading states + CDN fallback handlers
+ Flower basic auth
+ OpenAPI schema at /api/schema/
```

#### P3 — Differentiating Features (6 items)
```diff
+ LLM response cache (SHA256 diff-hash → Redis/in-memory)
+ GitHub Actions execution mode (composite action)
+ Multi-model comparison framework
+ .sentinel-ignore file support (glob patterns)
+ Feature flags via repo config
+ Notification event subscriber pattern
```

### The Result

| Metric | Before | After | Δ |
|:-------|:------:|:-----:|:-:|
| **Audit Score** | 5.7/10 | **9.0/10** | +3.3 |
| **Tests** | 157 | **352** | +195 |
| **Test Files** | 10 | **22** | +12 |
| **Coverage** | — | **91%** | — |
| **Lint Errors** | ~15 | **0** | Cleared |
| **Security Issues** | 4 open | 0 | All resolved |
| **E2E Tests** | 0 | **6** | Pipeline validated end-to-end |
| **Pipeline Pattern** | God function | **7 staged modules** | Independently testable |
| **API** | No pagination/filtering | **Paginated, filterable** | Production-ready |
| **Observability** | None | **JSON logs + Sentry + Prometheus** | Full visibility |
| **Resilience** | None | **Circuit breaker + cache + retry + idempotency** | Survives failures |

### The Architecture Decision

The original `review_pull_request` function was a ~250-line monolith doing 7 sequential responsibilities (DB upsert, GitHub fetch, LLM call, Semgrep, dedup, post, finalize). We extracted each responsibility into a named **pipeline stage**:

```python
# Before: 250-line monolith
def review_pull_request(...):
    # ... upsert DB records
    # ... fetch diff
    # ... fetch context
    # ... run LLM
    # ... run Semgrep
    # ... deduplicate
    # ... post comments

# After: Staged pipeline
class ReviewPipeline:
    stages = [
        UpsertStage(),        # DB records + private repo check
        FetchDiffStage(),     # GitHub diff + file contents
        FetchContextStage(),  # Repo metadata (non-fatal)
        LLMReviewStage(),     # Cache check → LLM call → cache store
        SemgrepStage(),       # Static analysis (non-fatal)
        DedupeStage(),        # Merge, deduplicate, .sentinel-ignore, limit
        PostCommentsStage(),  # Post inline comments + save to DB
    ]
```

Each stage receives and returns a typed `ReviewContext` dataclass. Each stage is independently unit-testable. A pipeline error in any stage marks the review as `FAILED` with a specific error message — the remaining stages are skipped.

### Why This Matters

This before/after story is the project's strongest portfolio signal. It demonstrates:

1. **Self-awareness** — commissioning an audit of your own work
2. **Prioritization** — fixing P0 before P1, security before features
3. **Architecture skill** — refactoring a monolith into a modular pipeline
4. **Production sense** — circuit breakers, health checks, rate limiting, idempotency
5. **Testing discipline** — adding E2E tests that prove the pipeline works
6. **Security mindset** — auth controls, startup validation, log redaction

These are exactly the signals senior engineering hiring managers look for.

---

## 🎬 Demo: Self-Review

The ultimate proof: **the bot reviewed its own code.**

We planted a deliberately vulnerable function — an unsafe `pickle.load()` on user-controlled input (CWE-502) — and documented the pipeline:

```
 1. GitHub webhook fires (pull_request opened)
 2. HMAC verified → idempotency check → Celery task enqueued
 3. Worker fetches diff + full file content
 4. LLM flags pickle.load() as security/blocking
 5. Semgrep independently flags same line → high confidence
 6. Findings merged with "llm+semgrep" source
 7. Inline comment posted on the diff
```

**Result:** 1 finding (blocking/security), high confidence, suggested fix included, zero false positives.

See [`docs/assets/demo/README.md`](docs/assets/demo/README.md) for the full walkthrough.

---

## 🧪 Development

### Running Tests

```bash
cd backend

# Run all 352 tests
pytest -v

# With coverage (currently 91%)
pytest --cov=. --cov-report=term-missing

# Faster — skip database migrations
pytest --nomigrations

# Run a specific test file
pytest tests/test_cache.py -v
```

### Code Quality

```bash
# Lint with Ruff
ruff check .

# Type-check with mypy (strict mode)
mypy sentinel_review/

# Auto-fix issues
ruff check . --fix
```

### Adding a New LLM Provider

1. Create a subclass of `LLMProvider` in `workers/llm.py`
2. Implement `_call_api()` with Pydantic validation
3. Add the provider to `get_llm_provider()` factory
4. Write tests in `tests/test_llm.py`

---

## 🔄 Testing & CI

### CI Pipeline (6 Jobs)

```
┌──────────┐    ┌──────────────────────┐    ┌──────────────┐    ┌───────────┐
│ Ruff Lint │──▶│ Type Check (mypy)   │──▶│ pytest (PG)   │──▶│ Docker    │
│ (3s)      │    │ (10s)               │    │ (10s, 352     │    │ Build     │
└──────────┘    └──────────────────────┘    │  tests)       │    │ (30s)     │
                                            └──────┬───────┘    └─────┬─────┘
                                                   │                  │
                                                   ▼                  ▼
                                            ┌──────────────┐   ┌──────────────┐
                                            │ Semgrep Scan │   │ docker-      │
                                            │ (5s)         │   │ compose      │
                                            └──────────────┘   │ Check (30s)  │
                                                                └──────────────┘
```

**CI features:**
- Path-filtered triggers (only relevant jobs on docs-only PRs)
- Ruff linting with strict rules
- mypy type checking
- Full test suite against PostgreSQL (not SQLite)
- Docker image build verification
- Semgrep security scan (pinned SHA, not `@v1`)
- Docker Compose smoke test
- Pip dependency caching with `cache-dependency-path`

---

## 🌐 Deployment

### Webhook Mode (Server Required)

**Render.com:** [`render.yaml`](render.yaml) — auto-detected by Render's Blueprint system:

```bash
# 1. Push repo to GitHub
# 2. Go to https://dashboard.render.com/blueprints
# 3. Connect your repository
# 4. Set required environment variables
# 5. Deploy — Render provisions: web, worker, PostgreSQL 16, Redis
```

**Fly.io:** [`fly.toml`](fly.toml) — one command deploy:

```bash
fly launch --copy-config --no-deploy
fly postgres create --name sentinel-review-db
fly redis create --name sentinel-review-redis
fly secrets set DJANGO_SECRET_KEY="..." WEBHOOK_SECRET="..." ANTHROPIC_API_KEY="..."
fly deploy
```

### GitHub Actions Mode (No Server Needed)

```yaml
# .github/workflows/sentinel-review.yml
name: Sentinel Review
on: [pull_request]
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: sentinel-review/sentinel-review/.github/actions/sentinel-review@main
        with:
          github-token: ${{ github.token }}
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

---

## 🗺️ Roadmap

### Done
- [x] Core pipeline: webhook → worker → LLM → inline comments
- [x] Semgrep integration with high-confidence merging
- [x] Feedback loop: 👍/👎 capture + usefulness dashboard
- [x] Chart.js analytics on `/stats/` page
- [x] Log redaction for secrets in logs
- [x] Self-review demo with planted CWE-502 vulnerability
- [x] Deployment configs (Render.com + Fly.io)
- [x] **Production audit + 31-item remediation (score: 5.7 → 9.0)**
- [x] **Staged pipeline architecture (7 named stages)**
- [x] **LLM response cache (SHA256 diff-hash)**
- [x] **Health checks, rate limiting, auth controls, circuit breaker**
- [x] **OpenAPI docs, Prometheus metrics, JSON logging, Sentry**
- [x] **E2E tests, .sentinel-ignore, GHA execution mode**
- [x] **Multi-model comparison framework**

### Next
- [ ] Slack/email notification hook
- [ ] Multi-language fixture set (JavaScript, TypeScript, Go, Ruby)
- [ ] Dependency scanning (Dependabot / Snyk)

### Future
- [ ] Multi-region deployment
- [ ] Fine-tuned custom model
- [ ] Kubernetes/Helm chart

---

## 🤝 Contributing

1. **Fork** the repository
2. **Create a branch**: `git checkout -b feat/amazing-feature`
3. **Make changes** with small, logical commits
4. **Run tests**: `cd backend && pytest`
5. **Lint**: `cd backend && ruff check .`
6. **Open a pull request** — describe what you changed and why

### Guidelines

- Keep PRs focused on a single concern
- Write tests for new functionality
- Follow existing conventions (type hints, docstrings, `from __future__ import annotations`)
- Update docs if you change behavior

---

## 📜 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.

---

<div align="center">
  <br/>
  <p>
    🛡️ <strong>Sentinel Review</strong> —
    <em>"The senior engineer who never gets tired."</em>
  </p>
  <p>
    Built with <strong>Django</strong>, <strong>Celery</strong>, and <strong>Anthropic Claude</strong>
  </p>
  <p>
    <a href="https://github.com/sentinel-review/sentinel-review/issues">🐛 Report Bug</a>
    ·
    <a href="https://github.com/sentinel-review/sentinel-review/issues">💡 Request Feature</a>
    ·
    <a href="https://github.com/sentinel-review/sentinel-review/pulls">🔧 Contribute</a>
    ·
    <a href="https://github.com/sentinel-review/sentinel-review/stargazers">⭐ Star the Repo</a>
  </p>
  <br/>
</div>
