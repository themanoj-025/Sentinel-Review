# Sentinel Review

[![CI](https://img.shields.io/github/actions/workflow/status/themanoj-025/Sentinel-Review/ci.yml?branch=main&label=CI&style=flat-square)](https://github.com/themanoj-025/Sentinel-Review/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](./LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg?style=flat-square)](https://www.python.org/)
[![Django 5.1](https://img.shields.io/badge/Django-5.1-success.svg?style=flat-square)](https://www.djangoproject.com/)
[![Celery + Redis](https://img.shields.io/badge/Async-Celery%20%2B%20Redis-37814A.svg?style=flat-square)](https://docs.celeryq.dev/)
[![Tests: 352 Passing](https://img.shields.io/badge/Tests-352%20Passing-brightgreen.svg?style=flat-square)](backend/tests/)

Autonomous GitHub PR-review agent that reads pull request diffs in full repository
context, produces severity-ranked, line-anchored inline review comments, and proves
its usefulness with real feedback metrics. Combines LLM semantic reasoning
(Anthropic Claude / OpenAI GPT-4o) with deterministic Semgrep static analysis
and a 7-stage Celery processing pipeline.

---

## Quick Facts

| Dimension | Details |
| --- | --- |
| **Domain** | Developer Tools, Automated Code Review & Security Analysis |
| **Core Framework** | Django 5.1 + Django REST Framework + Celery + Redis |
| **Analysis Pipeline** | 7-stage worker pipeline merging LLM reasoning with deterministic Semgrep SAST |
| **Comment Anchoring** | Line-anchored GitHub review comments with `blocking`, `warning`, and `nit` tiers |
| **Feedback Loop** | Tracks developer feedback (👍/👎) to quantify usefulness rates across repositories |
| **Reliability** | Distributed Redis caching (SHA-256 diff hash), circuit breakers, and delivery deduplication |
| **Test Coverage** | 352 collected tests across 22 test modules (91% backend coverage) |
| **License** | [MIT License](./LICENSE) |

---

## Table of Contents

- [Why Sentinel Review](#why-sentinel-review)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Data Flow](#data-flow)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Dashboard and API](#dashboard-and-api)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Case Study: The Audit Story](#case-study-the-audit-story)
- [Development](#development)
- [Testing and CI](#testing-and-ci)
- [Deployment](#deployment)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Support](#support)
- [License](#license)
- [Star History](#star-history)

---

## Why Sentinel Review

Code review is the highest-leverage quality practice in software engineering — and the hardest to scale.

| Review Mechanism | Strengths | Weaknesses |
| --- | --- | --- |
| **Linters & Static Analyzers** | Fast, deterministic, zero false positives on syntax | Miss business logic bugs, security context, and holistic design issues |
| **Generic LLM Reviewers** | Catch semantic issues | Generate unstructured summary dumps, high noise, not line-anchored |
| **Human Reviewers** | Deep institutional understanding | Expensive, slow, creates delivery bottlenecks |

**Sentinel Review bridges this gap** by combining:
- **LLM Reasoning:** Anthropic Claude Sonnet or OpenAI GPT-4o for contextual understanding.
- **Deterministic Static Analysis:** Semgrep rules for high-confidence vulnerability detection.
- **Line-Anchored Comments:** Direct inline diff comments rather than generic PR summaries.
- **Feedback-Driven Calibration:** Every comment supports reaction tracking (👍/👎) to measure real-world usefulness.

---

## Key Features

### Core Review Capabilities

| Feature | Implementation | Engineering Rationale |
| --- | --- | --- |
| **Line-Anchored Comments** | GitHub Create Review API | Developers inspect findings directly in code context |
| **Severity Tiers** | `blocking` / `warning` / `nit` | Prioritizes actionable bugs over stylistic suggestions |
| **Dual Engine** | Claude / GPT-4o + Semgrep | Blends semantic reasoning with deterministic rules |
| **Context Extraction** | Reads `CONTRIBUTING.md`, linters, related files | Adapts reviews to repository conventions |
| **Diff Caching** | SHA-256 diff hash in Redis | Avoids re-reviewing identical code commits |
| **Idempotency** | Delivery ID deduplication | Guards against webhook retransmissions |

### Operational Resilience

- **Circuit Breakers:** Wraps GitHub and LLM API clients to isolate upstream outages.
- **Log Redaction:** Sanitizes tokens, passwords, and private keys from all application logs.
- **Asynchronous Execution:** Django webhook acknowledges receipt in `<200ms`, delegating analysis to Celery workers.
- **Two Execution Modes:** Deploy as a full self-hosted server or run serverless via GitHub Actions.

---

## Architecture

```text
GitHub Event (POST) ──▶ Django Webhook View (HMAC + Dedup) ──▶ Redis Queue
                                                                   │
                                                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                   Celery Worker (7-Stage Pipeline)               │
│                                                                  │
│  1. UpsertStage        ── Record installation, repo, PR state    │
│  2. FetchDiffStage     ── Fetch PR diff with size guardrails     │
│  3. FetchContextStage  ── Read repository rules & linters        │
│  4. LLMReviewStage     ── Check cache, prompt Claude / GPT-4o    │
│  5. SemgrepStage       ── Run local SAST rules on diff           │
│  6. DedupeStage        ── Reconcile overlapping findings         │
│  7. PostCommentsStage  ── Publish line-anchored GitHub review    │
└──────────────────────────────────────────────────────────────────┘
         │                          │                         │
         ▼                          ▼                         ▼
  GitHub REST API             LLM Provider               PostgreSQL
  (Circuit Breaker)         (Circuit Breaker)         (Dashboard & API)
```

### GitHub Actions Mode (Serverless)

For repositories that prefer not to host infrastructure, Sentinel Review also executes as a standalone GitHub Action:

```yaml
name: Sentinel Review
on: [pull_request]
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: themanoj-025/Sentinel-Review/.github/actions/sentinel-review@main
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

---

## Data Flow

A complete review cycle executes across 14 deterministic steps:

1. **Webhook Event:** GitHub sends `POST /webhooks/github/` on `pull_request` triggers.
2. **Signature Verification:** Constant-time HMAC-SHA256 signature verification validates payload authenticity.
3. **Idempotency Gate:** Checks delivery ID in Redis; duplicates return `200 OK` immediately.
4. **Task Enqueue:** Enqueues review job to Redis queue; returns `202 Accepted` to GitHub in `<200ms`.
5. **Worker Pickup:** Celery worker claims the job and updates review status to `PROCESSING`.
6. **Diff Retrieval:** Fetches git unified diff, verifying file count and line size limits.
7. **Context Assembly:** Reads `.sentinel-ignore`, `CONTRIBUTING.md`, and linter configurations.
8. **Cache Lookup:** Computes SHA-256 diff hash; cache hits reuse prior analysis.
9. **LLM Evaluation:** Sends structured prompts to Claude Sonnet or GPT-4o using Pydantic schemas.
10. **Semgrep Analysis:** Executes Semgrep security rules across modified files.
11. **Deduplication:** Merges findings, elevating confidence when both Semgrep and LLM agree.
12. **Comment Formatting:** Groups findings by file and line, filtering out ignored patterns.
13. **GitHub Posting:** Posts an inline review with comments anchored to commit line offsets.
14. **Metrics Recording:** Updates database state and logs review execution duration to Prometheus.

---

## Quick Start

### Option A: Docker Compose (Recommended)

#### Windows (PowerShell)

```powershell
git clone https://github.com/themanoj-025/Sentinel-Review.git
cd Sentinel-Review
Copy-Item .env.example .env
# Edit .env with your GitHub App credentials and Anthropic/OpenAI keys
docker compose up --build
```

#### Linux / macOS

```bash
git clone https://github.com/themanoj-025/Sentinel-Review.git
cd Sentinel-Review
cp .env.example .env
# Edit .env with your GitHub App credentials and Anthropic/OpenAI keys
docker compose up --build
```

Once all containers are healthy:

| Service | Address | Role |
| --- | --- | --- |
| **Web Dashboard** | `http://localhost:8000` | Review overview, repository settings, analytics |
| **REST API** | `http://localhost:8000/api/` | Paginated API endpoints for integration |
| **Swagger UI** | `http://localhost:8000/api/docs/` | Interactive OpenAPI documentation |
| **Django Admin** | `http://localhost:8000/admin/` | Model administration and user management |
| **Flower** | `http://localhost:5555` | Celery task monitoring dashboard |
| **Health Check** | `http://localhost:8000/health/` | Liveness and readiness endpoints |
| **Prometheus** | `http://localhost:8000/metrics` | Real-time Prometheus metrics endpoint |

---

## Configuration

All configuration is managed via environment variables defined in `.env`:

### Mandatory Settings

| Variable | Secret? | Description |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Yes | Django cryptographic signing key |
| `WEBHOOK_SECRET` | Yes | Shared secret for verifying GitHub webhook HMAC signatures |
| `GITHUB_APP_ID` | No | GitHub App identification number |
| `GITHUB_APP_PRIVATE_KEY_B64` | Yes | Base64-encoded GitHub App RSA private key (`.pem`) |

### LLM Integration

| Variable | Default | Secret? | Description |
| --- | --- | --- | --- |
| `LLM_PROVIDER` | `anthropic` | No | Active provider (`anthropic` or `openai`) |
| `ANTHROPIC_API_KEY` | `""` | Yes | Anthropic Claude API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | No | Target Claude model identifier |
| `OPENAI_API_KEY` | `""` | Yes | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | No | Target OpenAI model identifier |

### Operational Settings

| Variable | Default | Secret? | Description |
| --- | --- | --- | --- |
| `DATABASE_URL` | `postgresql://...` | Yes | PostgreSQL connection URI |
| `REDIS_URL` | `redis://redis:6379/0` | No | Redis broker and cache connection URI |
| `JSON_LOG` | `true` | No | Enable JSON structured log formatting |
| `METRICS_ENABLED` | `true` | No | Enable Prometheus scraping at `/metrics` |
| `SENTRY_DSN` | `""` | Yes | Optional Sentry error reporting DSN |

---

## Dashboard and API

### Web Dashboard

- **Overview (`/`):** KPI cards showing total reviews, comments posted, and usefulness percentage.
- **Repositories (`/repos/`):** Searchable list with review counts and configuration panels.
- **Review Inspector (`/reviews/{id}/`):** Comprehensive view of inline comments with 👍/👎 developer reaction counts.
- **Analytics (`/stats/`):** Chart.js charts illustrating review volume, severity breakdowns, and trending usefulness.

### REST API Reference

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/v1/installations/` | List authorized GitHub App installations |
| `GET` | `/api/v1/repos/` | List repositories with review statistics |
| `PATCH` | `/api/v1/repos/{id}/config/` | Update per-repository review settings |
| `GET` | `/api/v1/reviews/` | Query review sessions filtered by repository or status |
| `GET` | `/api/v1/comments/` | Fetch generated comments filtered by severity |
| `POST` | `/api/v1/feedback/` | Submit developer feedback on specific comments |
| `GET` | `/api/v1/stats/` | Compute overall usefulness rate and volume aggregates |

---

## Tech Stack

| Layer | Component | Version | Purpose |
| --- | --- | --- | --- |
| **Backend Framework** | Django + DRF | `5.1.x` | Webhooks, ORM, authentication, and REST API |
| **Asynchronous Engine** | Celery + Redis | `5.4.x` | Background job processing and broker |
| **Database** | PostgreSQL | `16` | Relational persistence with JSONField config storage |
| **Frontend UI** | Django Templates + HTMX + Alpine.js | Latest | Server-rendered lightweight dashboard |
| **Visualizations** | Chart.js | `4.x` | Analytics charts with dark mode optimization |
| **LLM Reasoning** | Anthropic Claude / OpenAI GPT-4o | Latest | Semantic code review and vulnerability analysis |
| **Static Analysis** | Semgrep | Latest | Deterministic security and anti-pattern rules |
| **Validation** | Pydantic | `v2` | Strict JSON schema parsing of LLM outputs |
| **Testing** | Pytest & pytest-django | Latest | 352 unit, integration, and E2E tests (91% coverage) |

---

## Project Structure

```text
Sentinel-Review/
├── backend/
│   ├── sentinel_review/
│   │   ├── api/                # DRF REST API, health probes, and metrics
│   │   ├── dashboard/          # Server-rendered HTMX + Alpine dashboard
│   │   ├── models/             # ORM entities (Installation, Repo, Review, Comment)
│   │   ├── webhooks/           # GitHub webhook handler and HMAC validation
│   │   └── workers/            # 7-stage review pipeline and LLM connectors
│   ├── tests/                  # Pytest suite (352 unit and integration tests)
│   ├── manage.py               # Django management CLI
│   └── settings.py             # Central application configuration
├── docs/                       # Architecture diagrams and design records
├── scripts/                    # Evaluation runners and GitHub Action entrypoint
├── docker-compose.yml          # Container stack orchestration (5 services)
├── Dockerfile                  # Production container definition
├── pyproject.toml              # Build settings and tool configurations
└── README.md
```

---

## Case Study: The Audit Story

Sentinel Review was subjected to a rigorous 28-category production engineering audit:

- **Initial State (Score 5.7/10):** Functional MVP, but contained unbounded API endpoints, blanket exception handlers, insecure secret fallbacks, and monolithic worker functions.
- **Remediation Plan (31 Actions):** Refactored the God worker into a 7-stage pipeline, added circuit breakers on external HTTP calls, implemented constant-time HMAC validation, added strict Pydantic schemas, and introduced automated E2E tests.
- **Final Outcome (Score 9.0/10):** Production-grade security posture with 352 passing tests, 91% code coverage, and sub-200ms webhook response times.

---

## Development

### Local Setup Without Docker

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r ../requirements.txt -r ../requirements-dev.txt
python manage.py migrate
python manage.py runserver
```

---

## Testing and CI

The comprehensive test suite covers webhook authentication, idempotency deduplication,
pipeline stage isolation, schema parsing, circuit breakers, and database operations.

```bash
# Run backend tests
cd backend
pytest -v -o addopts=""

# Run with coverage report
pytest --cov=sentinel_review -o addopts=""
```

All external GitHub and LLM API requests are mocked using `respx` to guarantee
deterministic offline execution.

---

## Deployment

Production deployment configurations are included for major cloud hosts:
- **Docker Compose:** Production stack with PostgreSQL, Redis, Celery worker, and Web daemon.
- **Fly.io:** Configured via `fly.toml` for scalable container execution.
- **Render.com:** Pre-configured via `render.yaml` with managed database attachments.

---

## Roadmap

- [x] 7-Stage pipeline architecture with dedicated context stages
- [x] SHA-256 diff-based LLM response caching
- [x] Health checks, rate limiting, and circuit breakers
- [x] OpenAPI Swagger documentation and Prometheus metrics
- [x] Standalone GitHub Action runner mode
- [ ] Slack and Discord outbound notification webhooks
- [ ] Support for additional static analysis linters (Ruff, ESLint)

---

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository.
2. Create your topic branch: `git checkout -b feat/my-improvement`.
3. Verify linting and formatting: `ruff check backend/` and `ruff format backend/`.
4. Ensure all tests pass: `pytest backend/tests/ -o addopts=""`.
5. Open a pull request against `main`.

See [CONTRIBUTING.md](./CONTRIBUTING.md) for full contribution details.

---

## Support

- 🐛 [Report a Bug](https://github.com/themanoj-025/Sentinel-Review/issues)
- 💡 [Request a Feature](https://github.com/themanoj-025/Sentinel-Review/issues)
- ⭐ [Star on GitHub](https://github.com/themanoj-025/Sentinel-Review)

---

## License

This project is licensed under the [MIT License](./LICENSE).

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=themanoj-025/Sentinel-Review&type=Date)](https://star-history.com/#themanoj-025/Sentinel-Review&Date)
