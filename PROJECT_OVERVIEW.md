# Sentinel Review — Autonomous GitHub PR Review Agent

> An autonomous GitHub PR-review agent that reads diffs in full repo context, produces severity-ranked, line-anchored review comments, and proves its usefulness with real feedback metrics.

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![Django 5.1](https://img.shields.io/badge/Django-5.1-success.svg)](https://djangoproject.com)
[![Tests: 352](https://img.shields.io/badge/Tests-352%20passing-brightgreen.svg)](#testing)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Audit: 9.0/10](https://img.shields.io/badge/Audit-9.0%2F10-blue.svg)](#audit-story)

---

## Table of Contents

- [1. Executive Summary](#1-executive-summary)
- [2. Tech Stack & Core Technologies](#2-tech-stack--core-technologies)
- [3. High-Level Architecture](#3-high-level-architecture)
- [4. Complete Folder Structure Tree](#4-complete-folder-structure-tree)
- [5. Exhaustive File-by-File & Folder-by-Folder Breakdown](#5-exhaustive-file-by-file--folder-by-folder-breakdown)
- [6. Data Models & Schemas](#6-data-models--schemas)
- [7. API Surface](#7-api-surface)
- [8. Configuration & Environment Variables](#8-configuration--environment-variables)
- [9. Build, Run & Deployment Instructions](#9-build-run--deployment-instructions)
- [10. Data & Control Flow Walkthroughs](#10-data--control-flow-walkthroughs)
- [11. Dependency Graph Summary](#11-dependency-graph-summary)
- [12. Testing Strategy](#12-testing-strategy)
- [13. Known Issues, Technical Debt & Assumptions](#13-known-issues-technical-debt--assumptions)
- [14. Glossary](#14-glossary)
- [15. Appendix](#15-appendix)

---

## 1. Executive Summary

**Sentinel Review** is an autonomous GitHub PR-review agent that bridges the gap between linters (fast but shallow), LLM reviewers (semantic but noisy), and human reviewers (deep but expensive). It combines LLM-based reasoning (Claude/GPT-4o) with deterministic static analysis (Semgrep) to produce severity-ranked, line-anchored review comments posted directly on PR diffs.

**Target users**: Development teams wanting automated, high-quality code review that catches logic bugs, security issues, and design problems.

**What problem it solves**: Code review is the highest-leverage quality practice in software engineering — and the hardest to scale. Existing tools either miss semantic issues (linters) or produce generic summaries (LLM reviewers). Sentinel Review provides line-anchored, severity-ranked comments with a feedback loop that proves its usefulness.

**Why it exists**: To create an autonomous code review agent that combines the best of deterministic analysis and AI reasoning, with production-grade reliability (circuit breakers, caching, idempotency, health checks).

*Note: The audit story (5.7 → 9.0/10) and staged pipeline architecture are explicitly documented in the README.*

---

## 2. Tech Stack & Core Technologies

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| Language | Python | 3.12 | Backend |
| Web Framework | Django | 5.1 | Webhooks, API, dashboard |
| API | Django REST Framework | — | REST API with pagination |
| Async Jobs | Celery + Redis | — | Background review processing |
| Database | PostgreSQL | 16 | Primary data store |
| Frontend | Django Templates + HTMX + Alpine.js | — | Server-rendered dashboard |
| Charts | Chart.js | 4.x | Analytics visualization |
| LLM | Anthropic Claude / OpenAI GPT-4o | — | Code review reasoning |
| Static Analysis | Semgrep | — | Deterministic security signals |
| Validation | Pydantic | v2 | Strict JSON schema validation |
| GitHub API | PyJWT + httpx | — | JWT auth, inline comments |
| Testing | pytest + pytest-django | — | 352 tests, 91% coverage |
| Linting | Ruff | — | Code quality |
| Type Checking | mypy | — | Static type analysis |
| CI/CD | GitHub Actions | — | 6-job pipeline |
| Containerization | Docker + docker-compose | — | 5-service stack |

---

## 3. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    GitHub Platform                                   │
│  ┌──────────┐    ┌──────────────┐    ┌────────────────────────┐    │
│  │   PR     │───▶│   Webhook    │───▶│   GitHub REST API      │    │
│  │  Event   │    │   (POST)     │    │   (Reviews + Comments) │    │
│  └──────────┘    └──────┬───────┘    └───────────▲────────────┘    │
└─────────────────────────┼─────────────────────────┼─────────────────┘
                          │ HMAC-SHA256             │
                          ▼                         │
┌─────────────────────────────────────────────────────────────────────┐
│                    Sentinel Review System                            │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Django Webhook View                                         │   │
│  │  • Verify HMAC signature (constant-time)                    │   │
│  │  • Idempotency check (delivery-ID dedup)                    │   │
│  │  • Enqueue Celery task                                      │   │
│  │  • Return 202 (< 10s)                                       │   │
│  └───────────────────────┬──────────────────────────────────────┘   │
│                          │                                          │
│                          ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Redis (Celery Broker + LLM Cache + Delivery Dedup)          │   │
│  └───────────────────────┬──────────────────────────────────────┘   │
│                          │                                          │
│                          ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Celery Worker — 7-Stage Pipeline                            │   │
│  │                                                                │   │
│  │  1. UpsertStage      — DB records + private repo check       │   │
│  │  2. FetchDiffStage   — GitHub diff + file contents           │   │
│  │  3. FetchContextStage — Repo metadata (non-fatal)            │   │
│  │  4. LLMReviewStage   — Cache check → LLM call → cache store  │   │
│  │  5. SemgrepStage     — Static analysis (non-fatal)           │   │
│  │  6. DedupeStage      — Merge, dedup, .sentinel-ignore, limit │   │
│  │  7. PostCommentsStage — Inline comments + DB save            │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Resilience Layer                                            │   │
│  │  • Circuit breaker (GitHub + LLM)                            │   │
│  │  • LLM response cache (SHA256 diff-hash)                     │   │
│  │  • Webhook idempotency (delivery-ID dedup)                   │   │
│  │  • Rate limiting (100/hr anon, 1000/hr auth)                 │   │
│  │  • Health checks (/health/, /health/ready/)                  │   │
│  │  • Prometheus metrics                                        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Dashboard (Django Templates + HTMX + Chart.js)              │   │
│  │  • Home: KPIs, recent reviews, status distribution           │   │
│  │  • Repos: searchable list with HTMX                          │   │
│  │  • Review Detail: comments with 👍/👎                         │   │
│  │  • Analytics: usefulness, volume, trending charts            │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

**Architectural Pattern**: **Staged Pipeline** with **Event-Driven Processing**. The 7-stage pipeline processes PR reviews asynchronously via Celery, with each stage independently testable. The system also supports a GitHub Actions execution mode (no server needed).

---

## 4. Complete Folder Structure Tree

```
sentinel-review/
├── .dockerignore
├── .gitattributes
├── .github/
│   ├── dependabot.yml
│   ├── ISSUE_TEMPLATE/
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── workflows/
│       ├── ci.yml                  # 6-job CI pipeline
│       ├── load-test.yml
│       ├── sbom.yml
│       └── security-scan.yml
├── .gitignore
├── .pre-commit-config.yaml
├── AGENTS.md
├── AGENTS_FIX.md
├── backend/
│   ├── conftest.py
│   ├── manage.py
│   ├── pytest.ini
│   ├── sentinel_review/
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── health.py
│   │   │   ├── health_urls.py
│   │   │   ├── metrics.py
│   │   │   ├── serializers.py
│   │   │   ├── urls.py
│   │   │   └── views.py
│   │   ├── apps.py
│   │   ├── celery_app.py
│   │   ├── dashboard/
│   │   │   ├── templates/dashboard/
│   │   │   ├── urls.py
│   │   │   └── views.py
│   │   ├── logging_filters.py
│   │   ├── migrations/
│   │   ├── models/
│   │   │   ├── comment.py
│   │   │   ├── feedback.py
│   │   │   ├── installation.py
│   │   │   ├── pull_request.py
│   │   │   ├── repo.py
│   │   │   └── review.py
│   │   ├── services/
│   │   │   ├── notification_service.py
│   │   │   └── stats_service.py
│   │   ├── settings.py
│   │   ├── urls.py
│   │   ├── webhooks/
│   │   │   ├── signature.py
│   │   │   ├── urls.py
│   │   │   └── views.py
│   │   ├── workers/
│   │   │   ├── cache.py
│   │   │   ├── circuit_breaker.py
│   │   │   ├── feature_flags.py
│   │   │   ├── feedback_worker.py
│   │   │   ├── gha_runner.py
│   │   │   ├── github_client.py
│   │   │   ├── http_transport.py
│   │   │   ├── ignore_rules.py
│   │   │   ├── llm.py
│   │   │   ├── pipeline.py
│   │   │   ├── prompt_builder.py
│   │   │   ├── review_worker.py
│   │   │   ├── schemas.py
│   │   │   ├── semgrep_integration.py
│   │   │   └── token_manager.py
│   │   └── wsgi.py
│   └── tests/
│       ├── conftest.py
│       ├── fixtures/
│       ├── test_*.py               # 22 test files, 352 tests
│       └── __init__.py
├── CODEOWNERS
├── data/
│   └── .gitkeep
├── docker-compose.yml
├── Dockerfile
├── docs/
│   ├── assets/
│   ├── community/
│   ├── decisions/
│   ├── design/
│   ├── product/
│   ├── project/
│   ├── reference/
│   └── technical/
├── fly.toml
├── frontend/
│   ├── esbuild.config.mjs
│   ├── package.json
│   ├── src/
│   ├── static/
│   └── tailwind.config.js
├── LICENSE
├── Makefile
├── mkdocs.yml
├── PROJECT_ANALYSIS.md
├── PROJECT_OVERVIEW.md
├── pyproject.toml
├── README.md
├── render.yaml
├── requirements-dev.txt
├── requirements.txt
└── scripts/
    ├── build_eval_set.py
    ├── gha_review.py
    ├── load_test.py
    ├── run_comparison.py
    └── run_evaluation.py
```

---

## 5. Exhaustive File-by-File & Folder-by-Folder Breakdown

### Backend Core

#### `sentinel-review/backend/sentinel_review/settings.py`
- **Purpose**: Django settings with startup validation — fails fast if `SECRET_KEY` or `WEBHOOK_SECRET` are unset.

#### `sentinel-review/backend/sentinel_review/webhooks/signature.py`
- **Purpose**: HMAC-SHA256 webhook verification using constant-time `hmac.compare_digest()`.

#### `sentinel-review/backend/sentinel_review/workers/pipeline.py`
- **Purpose**: 7-stage review pipeline with typed `ReviewContext` dataclass. Each stage independently testable.

#### `sentinel-review/backend/sentinel_review/workers/llm.py`
- **Purpose**: LLM provider abstraction (Anthropic/OpenAI) with Pydantic validation and corrective retry.

#### `sentinel-review/backend/sentinel_review/workers/cache.py`
- **Purpose**: SHA256 diff-hash → Redis/in-memory LLM response cache.

#### `sentinel-review/backend/sentinel_review/workers/circuit_breaker.py`
- **Purpose**: CLOSED/OPEN/HALF_OPEN circuit breaker for GitHub API and LLM calls.

#### `sentinel-review/backend/sentinel_review/workers/semgrep_integration.py`
- **Purpose**: Semgrep static analysis integration, merged with LLM findings.

### Models (6 Django ORM models)

| Model | Purpose |
|-------|---------|
| `Installation` | GitHub App installations |
| `Repo` | Repository configuration |
| `PullRequest` | PR metadata |
| `Review` | Review results |
| `Comment` | Individual review comments |
| `Feedback` | 👍/👎 reactions |

---

## 6. Data Models & Schemas

### Review Comment

```json
{
  "file": "str — file path",
  "line": "int — line number",
  "severity": "blocking | warning | nit",
  "category": "bug | style | security | suggestion",
  "message": "str — review comment text",
  "high_confidence": "bool — LLM + Semgrep agreement"
}
```

---

## 7. API Surface

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/installations/` | List installations |
| `GET` | `/api/v1/repos/` | List repos |
| `PATCH` | `/api/v1/repos/{id}/config/` | Update repo config |
| `GET` | `/api/v1/reviews/` | List reviews |
| `GET` | `/api/v1/comments/` | List comments |
| `POST` | `/api/v1/feedback/` | Submit feedback |
| `GET` | `/api/v1/stats/` | Usefulness metrics |
| `POST` | `/webhooks/github/` | GitHub webhook receiver |
| `GET` | `/health/` | Liveness check |
| `GET` | `/health/ready/` | Readiness check |
| `GET` | `/metrics` | Prometheus metrics |

---

## 8. Configuration & Environment Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `DJANGO_SECRET_KEY` | Django signing key | **Yes** |
| `WEBHOOK_SECRET` | GitHub webhook secret | **Yes** |
| `GITHUB_APP_ID` | GitHub App ID | Yes |
| `GITHUB_APP_PRIVATE_KEY_B64` | Base64-encoded private key | Yes |
| `LLM_PROVIDER` | `anthropic` or `openai` | No (default: anthropic) |
| `ANTHROPIC_API_KEY` | Anthropic API key | If provider=anthropic |
| `OPENAI_API_KEY` | OpenAI API key | If provider=openai |
| `SENTRY_DSN` | Sentry error tracking | No |
| `METRICS_ENABLED` | Prometheus metrics | No |

---

## 9. Build, Run & Deployment Instructions

### Docker (Recommended)

```bash
git clone https://github.com/sentinel-review/sentinel-review.git
cd sentinel-review
cp .env.example .env
# Edit .env with your credentials
docker compose up --build
```

### Services

| Service | URL | Purpose |
|---------|-----|---------|
| Dashboard | `http://localhost:8000` | Web UI |
| API | `http://localhost:8000/api/` | REST endpoints |
| API Docs | `http://localhost:8000/api/docs/` | Swagger UI |
| Health | `http://localhost:8000/health/` | Liveness |
| Metrics | `http://localhost:8000/metrics` | Prometheus |
| Flower | `http://localhost:5555` | Celery monitoring |

### GitHub Actions Mode (No Server)

```yaml
- uses: sentinel-review/sentinel-review/.github/actions/sentinel-review@main
  with:
    github-token: ${{ github.token }}
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

---

## 10. Data & Control Flow Walkthroughs

### Flow 1: PR Review (14 Steps)

1. GitHub sends POST /webhooks/github
2. HMAC-SHA256 signature verified
3. Idempotency check (delivery-ID dedup)
4. Enqueue Celery task → Redis
5. Return 202 (< 10s)
6. Worker pops task
7. UpsertStage — DB records
8. Private repo check
9. FetchDiffStage — GitHub diff
10. FetchContextStage — repo metadata
11. LLMReviewStage — cache check → LLM call
12. SemgrepStage — static analysis
13. DedupeStage — merge, filter, limit
14. PostCommentsStage — inline comments + DB

---

## 11. Dependency Graph Summary

```
webhooks/views.py → workers/pipeline.py → workers/* (7 stages)
workers/llm.py → workers/cache.py → Redis
workers/semgrep_integration.py → semgrep CLI
api/views.py → models/* → PostgreSQL
dashboard/views.py → models/* → templates
```

---

## 12. Testing Strategy

- **Framework**: pytest + pytest-django
- **Tests**: 352 tests across 22 test files
- **Coverage**: 91%
- **CI**: 6-job pipeline (lint → typecheck → test → docker → semgrep → compose)

---

## 13. Known Issues, Technical Debt & Assumptions

### Known Issues

1. **Python only**: Currently supports Python code review only.
2. **LLM costs**: Each review incurs API costs (mitigated by cache).

### Technical Debt

1. **Single-region**: No multi-region deployment support.
2. **No fine-tuned model**: Uses off-the-shelf LLMs.

---

## 14. Glossary

| Term | Definition |
|------|-----------|
| **Circuit Breaker** | Pattern to prevent cascading failures (CLOSED/OPEN/HALF_OPEN) |
| **Idempotency** | Processing same event once despite multiple deliveries |
| **Semgrep** | Static analysis tool for finding bugs and enforcing code standards |
| **High Confidence** | Finding backed by both LLM and Semgrep signals |
| **.sentinel-ignore** | Glob patterns for excluded files/directories |

---

## 15. Appendix

### Audit Story

| Metric | Before | After | Δ |
|--------|--------|-------|---|
| Audit Score | 5.7/10 | **9.0/10** | +3.3 |
| Tests | 157 | **352** | +195 |
| Coverage | — | **91%** | — |
| E2E Tests | 0 | **6** | Pipeline validated |

### Self-Review Demo

The bot reviewed its own code and caught a planted `pickle.load()` vulnerability (CWE-502) — 1 finding (blocking/security), high confidence, zero false positives.

---

*This document was generated as part of a comprehensive project documentation effort. Last updated: August 8, 2026.*
