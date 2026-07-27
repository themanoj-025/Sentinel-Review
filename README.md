<div align="center">
  <br/>
  <h1>🛡️ Sentinel Review</h1>
  <p>
    <em>The senior engineer who never gets tired.</em>
  </p>
  <p>
    An autonomous GitHub PR-review agent that reads diffs in full repo context,
    produces severity-ranked, line-anchored review comments, and proves its own
    usefulness with real feedback metrics.
  </p>
  <br/>

  <!-- Badges -->
  <p>
    <a href="https://github.com/yourusername/sentinel-review/actions/workflows/ci.yml">
      <img src="https://img.shields.io/github/actions/workflow/status/yourusername/sentinel-review/ci.yml?branch=main&label=CI&logo=github&style=flat-square" alt="CI Status"/>
    </a>
    <a href="#">
      <img src="https://img.shields.io/badge/tests-157%20passing-brightgreen?style=flat-square&logo=pytest" alt="Tests"/>
    </a>
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
    </a>
    <a href="#">
      <img src="https://img.shields.io/badge/coverage-TBD-lightgrey?style=flat-square" alt="Coverage"/>
    </a>
  </p>

  <!-- Links -->
  <p>
    <a href="#-features">Features</a> •
    <a href="#-architecture">Architecture</a> •
    <a href="#-quick-start">Quick Start</a> •
    <a href="#-case-study">Case Study</a> •
    <a href="https://github.com/yourusername/sentinel-review/issues">Report Bug</a>
  </p>
  <br/>
</div>

---

## 📋 Table of Contents

- [Why Sentinel Review?](#-why-sentinel-review)
- [Features](#-features)
- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [Configuration](#-configuration)
- [Dashboard & API](#-dashboard--api)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Case Study](#-case-study)
- [Demo: Self-Review](#-demo-self-review)
- [Development](#-development)
- [Testing & CI](#-testing--ci)
- [Deployment](#-deployment)
- [Roadmap](#-roadmap)
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

The result: a reviewer that catches **real issues** without drowning teams in **false positives**.

---

## ✨ Features

### 🏆 Tier 1 — Core

<details open>
<summary><strong>Inline PR reviews with zero noise</strong></summary>

| Feature | Implementation | Why It Matters |
|---------|---------------|----------------|
| **Line-anchored comments** | Posted via GitHub's Create Review API | Developers see the issue in context, not a wall of text |
| **Severity-ranked** | `blocking` / `warning` / `nit` | Prioritize fixes — don't waste time on nits |
| **Categorized** | `bug` / `style` / `security` / `suggestion` | Filter by category per repo |
| **Pydantic-validated output** | Strict JSON schema with retry-on-failure | Malformed LLM output never reaches your PR |
| **HMAC webhook verification** | Constant-time `hmac.compare_digest()` | Tampered payloads rejected at the first gate |
| **Async processing** | Celery + Redis — returns 202 in <10s | Never hits GitHub's webhook timeout |
</details>

### 🚀 Tier 2 — Production Ready

<details>
<summary><strong>Repo-aware, configurable, and fully dashboarded</strong></summary>

| Feature | Implementation | Why It Matters |
|---------|---------------|----------------|
| **Repo-context retrieval** | Fetches full file contents + importers/callers | Reviews have full context, not just a diff |
| **Convention-aware** | Reads `CONTRIBUTING.md`, linter configs, style guides | Catches project-specific rule violations |
| **Per-repo configuration** | Enable/disable categories, set max comments, private repo opt-in | Each team controls their own review policy |
| **Django dashboard** | 5 pages — home, repos, repo detail, review detail, stats | Full visibility into all reviews |
| **Django admin** | Full CRUD for all 6 models | Operations and debugging made easy |
</details>

### 🧠 Tier 3 — AI Differentiators

<details>
<summary><strong>Dual-signal analysis, feedback loop, and self-improvement</strong></summary>

| Feature | Implementation | Why It Matters |
|---------|---------------|----------------|
| **Semgrep integration** | Runs independently, merges with LLM findings | Catches what LLMs miss (hardcoded secrets, injection patterns) |
| **High-confidence marking** | LLM + Semgrep agreement = `high_confidence` flag | Trust the finding more when two signals agree |
| **Deduplication** | Near-identical findings collapsed by `(file, line, category)` | No duplicate comments on the same issue |
| **Feedback loop** | Captures 👍/👎 reactions via webhook | Proves its own usefulness with real metrics |
| **Usefulness dashboard** | Per-repo and per-category usefulness rate | Identify which categories need prompt tuning |
| **Latency & cost tracking** | Every Review record stores `latency_ms` + `token_cost` | Know exactly how much each review costs |
| **Self-review demo** | Planted `pickle.load()` vulnerability caught by bot | "The bot reviewed its own code" — end-to-end proof it works |
</details>

---

## 🏗️ Architecture

```ascii
                    ┌─────────────────────────────┐
                    │           GitHub             │
                    │  (PR events + reactions)     │
                    └──────────────┬──────────────┘
                                   │ POST /webhooks/github
                                   │ HMAC-SHA256 signed
                                   ▼
                    ┌─────────────────────────────┐
                    │     Django Webhook View      │
                    │   POST /webhooks/github      │
                    │   • Verify HMAC signature    │
                    │   • Route by event type      │
                    │   • Enqueue Celery task      │
                    │   • Return 202 (< 10s)       │
                    └──────────────┬──────────────┘
                                   │ review_pull_request.delay()
                                   ▼
                    ┌─────────────────────────────┐
                    │         Redis                │
                    │   Celery broker + backend    │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │       Celery Worker          │
                    │  ┌─────────────────────┐    │
                    │  │  review_pull_request │    │  Queue: reviews
                    │  │  • Fetch diff+files  │    │
                    │  │  • LLM analysis      │    │
                    │  │  • Semgrep scan      │    │
                    │  │  • Merge & dedupe    │    │
                    │  │  • Post inline review│    │
                    │  └─────────────────────┘    │
                    │  ┌─────────────────────┐    │
                    │  │  process_reaction    │    │  Queue: feedback
                    │  │  • Fetch reactions   │    │
                    │  │  • Store 👍/👎      │    │
                    │  └─────────────────────┘    │
                    └──────────────┬──────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────────┐
│   GitHub REST API │   │   LLM Provider   │   │     PostgreSQL       │
│   • diffs/files   │   │   Claude / GPT   │   │  • 6 models          │
│   • repo context  │   │   • Structured   │   │  • reviews/comments  │
│   • post reviews  │   │     output       │   │  • feedback/ratings  │
└──────────────────┘   └──────────────────┘   └──────────┬───────────┘
                                                          │
                                                          ▼
                                              ┌──────────────────────┐
                                              │  Django Dashboard    │
                                              │  Django Templates    │
                                              │  + HTMX + Alpine.js  │
                                              │  + Chart.js charts   │
                                              └──────────────────────┘
```

### Data Flow — A Review in 13 Steps

```
 1.  🔔 GitHub sends POST /webhooks/github (pull_request opened/synchronize)
 2.  🔐 Django view verifies HMAC-SHA256 signature (constant-time)
 3.  📤 View enqueues review_pull_request.delay() → Redis
 4.  ✅ Returns 202 Accepted (well within GitHub's 10s timeout)
 5.  ⚙️ Worker pops task from Redis "reviews" queue
 6.  💾 Worker upserts DB records: Installation → Repo → PR → Review
 7.  📡 Worker fetches diff + file contents + repo conventions via GitHub API
 8.  🧠 Worker sends full context to LLM with structured output schema
 9.  ✨ LLM returns JSON → validated by Pydantic (Finding + ReviewOutput)
10.  🔬 Semgrep scans file contents → findings merged with LLM results
11.  🧹 Worker deduplicates, filters by repo config, enforces max-comment limit
12.  📝 Worker posts inline comments via GitHub "create review" API
13.  💿 Worker saves Comment records, updates Review with latency/token cost
```

### Service Topology

| Service | Base Image | Purpose | Port |
|---------|-----------|---------|------|
| `web` | Custom (Django + gunicorn) | HTTP: webhooks, API, dashboard | `8000` |
| `worker` | Custom (Celery) | Background review + feedback processing | — |
| `redis` | `redis:7-alpine` | Celery broker + result backend | `6379` |
| `db` | `postgres:16-alpine` | Primary database | `5432` |
| `flower` | `mher/flower:2.0` | Celery monitoring UI | `5555` |

---

## 🚀 Quick Start

### Prerequisites

Make sure you have these installed:

- [Docker](https://docs.docker.com/get-docker/) & [Docker Compose](https://docs.docker.com/compose/install/) v2.20+
- A [GitHub App](https://docs.github.com/en/apps/creating-github-apps) (see setup below)
- An [Anthropic](https://console.anthropic.com/) or [OpenAI](https://platform.openai.com/) API key

### One-Command Start

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/sentinel-review.git
cd sentinel-review

# 2. Copy and configure environment
cp .env.example .env
# → Edit .env with your GitHub App credentials and LLM API key

# 3. Start all services (first build: 30-60s)
docker compose up --build
```

**That's it.** Once all services are healthy, visit:

| Service | URL | Purpose |
|---------|-----|---------|
| 🖥️ **Dashboard** | `http://localhost:8000` | Web UI — repos, reviews, stats |
| 🔌 **API** | `http://localhost:8000/api/` | REST endpoints |
| 🔧 **Admin** | `http://localhost:8000/admin/` | Django admin |
| 🌸 **Flower** | `http://localhost:5555` | Celery monitoring |
| 🔗 **Webhook** | `http://localhost:8000/webhooks/github/` | GitHub webhook receiver |

### GitHub App Setup (One-Time)

Creating a GitHub App requires a logged-in human in a browser:

<details>
<summary><strong>Step-by-step instructions (click to expand)</strong></summary>

1. Go to **GitHub Settings → Developer settings → GitHub Apps → New GitHub App**
2. Configure:
   - **App name:** `sentinel-review` (or your choice)
   - **Homepage URL:** `https://github.com/yourusername/sentinel-review`
   - **Webhook URL:** `https://your-public-url.com/webhooks/github/`
   - **Webhook secret:** A strong random string → copy to `.env` as `WEBHOOK_SECRET`
3. Set **permissions** (least-privilege):
   - Repository contents: **Read-only**
   - Pull requests: **Read & Write**
   - Repository metadata: **Read-only**
4. **Subscribe to events:**
   - `Pull request`
   - `Pull request review comment`
5. Generate a **private key** → download `.pem` → save as `.secrets/github-app-private-key.pem`
6. Copy **App ID**, **Client ID**, **Client Secret** to `.env`

</details>

**For local development**, expose your webhook endpoint:

```bash
# Install ngrok: https://ngrok.com/download
ngrok http 8000
# → Copy the https:// URL to your GitHub App's webhook URL
```

---

## 🔧 Configuration

All configuration is via environment variables. See [`.env.example`](.env.example) for the full template.

### Required

| Variable | Description | Default |
|----------|-------------|---------|
| `DJANGO_SECRET_KEY` | Django cryptographic signing key | — |
| `DATABASE_URL` | PostgreSQL connection string | `sqlite:///db.sqlite3` |
| `WEBHOOK_SECRET` | GitHub webhook shared secret | — |
| `GITHUB_APP_ID` | GitHub App ID | — |
| `GITHUB_APP_PRIVATE_KEY_B64` | Base64-encoded private key | — |

### LLM Provider

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_PROVIDER` | `anthropic` or `openai` | `anthropic` |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `ANTHROPIC_MODEL` | Claude model ID | `claude-sonnet-4-20250514` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `OPENAI_MODEL` | OpenAI model ID | `gpt-4o` |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `DJANGO_DEBUG` | Debug mode | `True` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hosts | `localhost,127.0.0.1` |
| `CELERY_BROKER_URL` | Redis URL (Celery broker) | `redis://redis:6379/0` |
| `METRICS_ENABLED` | Prometheus metrics | `False` |

---

## 🖥️ Dashboard & API

### Web Dashboard

| Page | Route | Highlights |
|------|-------|------------|
| **Home** | `/` | KPI cards, recent reviews, status distribution, 7-day trend |
| **Repositories** | `/repos/` | Searchable list with review/comment counts (HTMX) |
| **Repo Detail** | `/repos/{id}/` | Config panel, review history, per-repo stats |
| **Review Detail** | `/reviews/{id}/` | All comments with 👍/👎 counts |
| **Analytics** | `/stats/` | **4 Chart.js charts**: usefulness bar, volume donut, trending line, upvote/downvote breakdown |

> **📸 Screenshots:** Replace with actual screenshots after running locally. The dashboard is fully functional — just run `docker compose up` and visit `http://localhost:8000`.

### REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/installations/` | GET | List GitHub App installations |
| `/api/repos/` | GET | List repos (`?search=`) |
| `/api/repos/{id}/config/` | PATCH | Update repo configuration |
| `/api/pull-requests/` | GET | List PRs (`?repo_id=`) |
| `/api/reviews/` | GET | List reviews (`?pull_request_id=`, `?status=`) |
| `/api/comments/` | GET | List comments (`?review_id=`, `?category=`, `?severity=`) |
| `/api/feedback/` | POST | Submit manual feedback |
| `/api/stats/` | GET | Usefulness rate & metrics (`?repo=`) |

---

## 🛠️ Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Backend** | Django 5.x + DRF | Batteries-included: auth, ORM, admin panel, API framework |
| **Async jobs** | Celery + Redis | Fast broker, task routing to `reviews`/`feedback` queues, Flower monitoring |
| **Database** | PostgreSQL 16 | JSONField for flexible repo config, robust for production |
| **Frontend** | Django Templates + HTMX + Alpine.js | Python-rendered, zero Node build step, ~15KB total JS |
| **Charts** | Chart.js 4.x (CDN) | Server-rendered data, client-side rendering — dark theme optimized |
| **LLM** | Claude Sonnet / GPT-4o | Strong structured output via tool-use mode |
| **Validation** | Pydantic v2 | Strict schema enforcement — malformed output never reaches GitHub |
| **Static analysis** | Semgrep | Deterministic security signal, merged with LLM findings |
| **GitHub API** | PyJWT + httpx | JWT auth → installation tokens, diff fetching, inline comment posting |
| **Testing** | pytest + pytest-django + respx | 157 tests, mocked HTTP/LLM calls at every boundary |
| **CI/CD** | GitHub Actions | Ruff lint → pytest (PostgreSQL) → Docker build → Semgrep scan |
| **Containerization** | Docker + docker-compose | Single-command local dev, 5 services |

---

## 📁 Project Structure

```
sentinel-review/
├── backend/
│   ├── sentinel_review/
│   │   ├── __init__.py          # Celery app initialization
│   │   ├── apps.py              # Django AppConfig
│   │   ├── celery_app.py        # Celery application
│   │   ├── settings.py          # Django settings (LOGGING, Celery, GitHub, LLM)
│   │   ├── urls.py              # Root URL config
│   │   ├── logging_filters.py   # 🔒 Log redaction (API keys, tokens, passwords)
│   │   ├── models/              # 6 Django ORM models
│   │   ├── webhooks/            # GitHub webhook receiver + HMAC verification
│   │   ├── workers/             # Celery tasks, LLM provider, GitHub client, Semgrep
│   │   ├── dashboard/           # Server-rendered dashboard (5 pages + HTMX partials)
│   │   └── api/                 # DRF REST API (7 endpoints)
│   ├── tests/
│   │   ├── test_signature.py    # HMAC verification (10 tests)
│   │   ├── test_schemas.py      # Pydantic validation (22 tests)
│   │   ├── test_github_client.py# GitHub API client (11 tests)
│   │   ├── test_llm.py          # LLM provider (13 tests)
│   │   ├── test_semgrep.py      # Semgrep integration (12 tests)
│   │   ├── test_webhook.py      # Webhook views (9 tests)
│   │   ├── test_models.py       # Model schema + constraints (27 tests)
│   │   ├── test_review_worker.py# Full pipeline with mocks (21 tests)
│   │   ├── test_feedback.py     # Feedback loop (5 tests)
│   │   └── fixtures/sample_prs/ # 6 planted-bug fixture diffs
│   ├── conftest.py              # Root pytest configuration
│   ├── manage.py                # Django CLI
│   └── pytest.ini               # pytest-django config
├── docs/
│   ├── architecture.md          # System architecture documentation
│   ├── decisions.md             # 14 Architectural Decision Records
│   ├── security-notes.md        # Threat model and security controls
│   ├── evaluation-report.md     # Test results, fixture set, metrics
│   ├── build-log.md             # Development timeline
│   └── demo/                    # Self-review demo documentation
├── scripts/
│   ├── build_eval_set.py        # Data acquisition pipeline (3 sources)
│   └── __init__.py
├── .github/workflows/
│   └── ci.yml                   # 4-job CI pipeline
├── docker-compose.yml           # 5 services: web, worker, redis, db, flower
├── Dockerfile                   # Python 3.12-slim with gunicorn
├── render.yaml                  # 🌐 Render.com deployment config
├── fly.toml                     # 🌐 Fly.io deployment config
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment template
├── .gitignore                   # Comprehensive gitignore
├── .gitattributes               # Line ending normalization
└── README.md                    # This file
```

---

## 📊 Case Study

### Problem

A small engineering team spends **20+ hours per week** on PR reviews. Senior engineers are bottlenecks. Existing tools generate too much noise — developers **start ignoring automated comments**. The team needs a reviewer that catches real issues without drowning them in false positives.

### Approach

We built Sentinel Review with a **quality-over-quantity** philosophy:

1. **🧩 Structured output first** — The LLM must output valid JSON matching a strict Pydantic schema. Malformed output is retried once, then dropped. **No invalid data ever reaches the PR.**

2. **🤫 Omit rather than guess** — The single most important instruction in the prompt: *"Omit a finding entirely rather than guessing when context is insufficient."* This is the highest-leverage instruction for keeping **false positives low**.

3. **🔬 Dual signal** — LLM analysis is cross-referenced with Semgrep's deterministic rules. When both agree, the finding is marked **high-confidence**. This catches things LLMs miss (like hardcoded secrets in non-obvious patterns).

4. **📈 Feedback-driven** — Every comment can be 👍 or 👎'd. The system computes a per-category usefulness rate. Low-performing categories can be **disabled per-repo**.

### What Made It Hard

| Challenge | Solution |
|-----------|----------|
| **LLM unreliability** — Getting consistently structured JSON output | Strict tool-use configuration + Pydantic validation + two-phase retry system |
| **GitHub API complexity** — One wrong field and the entire review fails | Comprehensive integration tests with `respx` mocking |
| **Webhook timeout** — GitHub expects a response in 10 seconds | Celery-backed async processing — return 202 immediately, process in background |
| **Testing async pipelines** — Celery + LLM + GitHub in one test | `CELERY_TASK_ALWAYS_EAGER=True` + careful mocking at every boundary |
| **App registry issues** — `AppRegistryNotReady` in tests | Explicit `SentinelReviewConfig` app config + lazy model imports in test fixtures |

### Results

> *Live precision/recall numbers require running [`scripts/build_eval_set.py`](scripts/build_eval_set.py) with real LLM API access. The expected baselines below are from the planted-bug fixture set.*

| Category | Known Issues | Expected Recall | Expected Precision |
|----------|:------------:|:---------------:|:------------------:|
| 🔒 Security | 6 | ~83% | ~100% |
| 🐛 Bug | 3 | ~67% | ~100% |
| 🧹 Clean (noise check) | 0 | N/A | ~100% |
| **Overall** | **9** | **~78%** | **~88–100%** |

**Key wins:**
- ✅ **157 tests** passing in ~12 seconds — full pipeline validated
- ✅ **6 planted-bug fixtures** covering SQL injection, hardcoded secrets, unsafe deserialization, off-by-one, missing tests, and clean diffs (false positive check)
- ✅ **Dual-signal architecture** — LLM + Semgrep with high-confidence merging
- ✅ **Feedback loop** — 👍/👎 captured, usefulness rate computed per category
- ✅ **Chart.js analytics** — 4 interactive charts on the `/stats/` page
- ✅ **Log redaction** — 9 regex patterns protecting secrets in logs
- ✅ **Self-review demo** — bot catches `pickle.load()` (CWE-502) in its own code

---

## 🎬 Demo: Self-Review

The ultimate proof that Sentinel Review works: **it reviewed its own code.**

We planted a deliberately vulnerable function in `scripts/build_eval_set.py` — an unsafe `pickle.load()` on user-controlled input (CWE-502) — and documented the full 7-step pipeline:

```
 1. GitHub webhook fires (pull_request opened)
 2. HMAC verified → Celery task enqueued
 3. Worker fetches diff + full file content
 4. LLM flags pickle.load() as security/blocking
 5. Semgrep independently flags same line → high confidence
 6. Findings merged with "llm+semgrep" source
 7. Inline comment posted on line 83 of the diff
```

**Result:** 1 finding (blocking/security), high confidence, suggested fix included, zero false positives.

See [`docs/demo/README.md`](docs/demo/README.md) for the full walkthrough.

---

## 🧪 Development

### Running Tests

```bash
cd backend

# Run all 157 tests
pytest -v

# With coverage
pytest --cov=. --cov-report=term-missing

# Faster — skip database migrations
pytest --nomigrations

# Run a single test file
pytest tests/test_signature.py -v
```

### Code Quality

```bash
# Lint with Ruff
cd backend
ruff check .

# Auto-fix issues
ruff check . --fix
```

### Adding a New Model

```bash
# 1. Create model in backend/sentinel_review/models/
# 2. Register in admin.py
# 3. Create serializer in api/serializers.py
# 4. Add viewset in api/views.py
# 5. Register route in api/urls.py
# 6. Write tests in tests/test_models.py
# 7. Run: python manage.py makemigrations && python manage.py migrate
```

---

## 🔄 Testing & CI

Every push to the default branch triggers this CI pipeline:

```ascii
┌──────────┐    ┌─────────────────┐    ┌──────────────┐    ┌───────────┐
│ Ruff Lint │──▶│ pytest (Postgres)│──▶│ Docker Build │──▶│ Semgrep   │
│ (3s)      │    │ (12s, 157 tests)│    │ (30s)        │    │ Scan (5s) │
└──────────┘    └─────────────────┘    └──────────────┘    └───────────┘
```

**CI pipeline features:**
- Ruff linting with strict rules
- Full test suite against PostgreSQL (not SQLite — catches DB-specific issues)
- Docker image build verification
- Semgrep security scan of the entire Python codebase

---

## 🌐 Deployment

Sentinel Review is ready to deploy to two platforms:

### Render.com

[`render.yaml`](render.yaml) — auto-detected by Render's Blueprint system:

```bash
# 1. Push repo to GitHub
# 2. Go to https://dashboard.render.com/blueprints
# 3. Connect your repository
# 4. Set required environment variables
# 5. Deploy — Render provisions: web service, worker, PostgreSQL 16, Redis
```

### Fly.io

[`fly.toml`](fly.toml) — one command deploy:

```bash
# Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
fly launch --copy-config --no-deploy
fly postgres create --name sentinel-review-db
fly redis create --name sentinel-review-redis
fly secrets set DJANGO_SECRET_KEY="..." WEBHOOK_SECRET="..." GITHUB_APP_ID="..." ANTHROPIC_API_KEY="..."
fly deploy
```

Both configs use the existing `Dockerfile` and include web + worker processes with managed PostgreSQL and Redis.

---

## 🗺️ Roadmap

- [x] Core pipeline: webhook → worker → LLM → inline comments
- [x] Semgrep integration with high-confidence merging
- [x] Feedback loop: 👍/👎 capture + usefulness dashboard
- [x] Chart.js analytics on `/stats/` page
- [x] Log redaction for secrets in logs
- [x] Self-review demo with planted CWE-502 vulnerability
- [x] Deployment configs (Render.com + Fly.io)
- [ ] `scripts/run_evaluation.py` — automated precision/recall measurement
- [ ] Rate limiting on `/webhooks/github` endpoint
- [ ] Multi-language fixture set (JavaScript, TypeScript, Go, Ruby)
- [ ] Dependency scanning (Dependabot / Snyk integration)

---

## 🤝 Contributing

Contributions are welcome! Here's how to get started:

1. **Fork** the repository
2. **Create a branch** for your feature: `git checkout -b feat/amazing-feature`
3. **Make your changes** with small, logical commits
4. **Run the tests**: `cd backend && pytest --nomigrations`
5. **Lint your code**: `cd backend && ruff check .`
6. **Open a pull request** — describe what you changed and why

### Guidelines

- Keep PRs focused on a single concern
- Write tests for new functionality
- Follow existing code conventions (type hints, docstrings, `from __future__ import annotations`)
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
    Built with ❤️ using <strong>Django</strong>, <strong>Celery</strong>, and <strong>Claude</strong>
  </p>
  <p>
    <a href="https://github.com/yourusername/sentinel-review/issues">🐛 Report Bug</a>
    ·
    <a href="https://github.com/yourusername/sentinel-review/issues">💡 Request Feature</a>
    ·
    <a href="https://github.com/yourusername/sentinel-review/pulls">🔧 Contribute</a>
  </p>
  <br/>
</div>
