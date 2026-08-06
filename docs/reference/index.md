# Sentinel Review

> **An autonomous GitHub PR-review agent.**  
> Reads diffs in full repo context, produces severity-ranked, line-anchored
> review comments, and proves its own usefulness with real feedback metrics.

---

## What is Sentinel Review?

Sentinel Review is a Django-based service that monitors GitHub pull request
events via webhooks, analyzes changes using a combination of LLM-based
reasoning (Claude / GPT-4o) and static analysis (Semgrep), and posts
inline review comments on the PR diff.

**Key differentiators:**

- **Two-signal architecture:** LLM + Semgrep independently analyze each
  diff. When both agree, findings are marked **high confidence**.
- **Line-anchored comments:** Each finding is pinned to a specific line
  in the diff, not a summary blob.
- **Feedback-driven:** Every comment can be 👍/👎'd. Usefulness metrics
  prove the bot's value with real data.
- **Production-hardened:** Circuit breakers, LLM caching, webhook
  idempotency, rate limiting, structured logging, Prometheus metrics,
  and startup validation.

## Architecture at a Glance

```
GitHub PR Event → Webhook (HMAC verified) → Celery Queue → 7-Stage Pipeline
                                                             ├─ Upsert DB Records
                                                             ├─ Fetch Diff + Context
                                                             ├─ LLM Review (cached)
                                                             ├─ Semgrep Scan
                                                             ├─ Deduplicate & Merge
                                                             └─ Post Inline Comments
```

## Quick Links

| Page | Description |
| ------ | ------------- |
| [Architecture](../technical/TechSpec.md) | System design, component details, data flow |
| [Decisions](../decisions/decisions.md) | 22 Architecture Decision Records (ADRs) |
| [Evaluation Report](evaluation-report.md) | Precision/recall/F1 across 8 fixtures |
| [Security Notes](../technical/security-notes.md) | Security architecture and threat model |
| [Limitations](limitations.md) | Known limitations and conscious scope decisions |
| [Demo: Self-Review](../assets/demo/README.md) | "The bot reviewed its own code" |

## Quick Start

```bash
git clone https://github.com/sentinel-review/sentinel-review.git
cd sentinel-review
cp .env.example .env
# Edit .env with your GitHub App + LLM API credentials
docker compose up --build
```

Dashboard: [http://localhost:8000](http://localhost:8000)

## Stats

- **Tests:** 352 passing, 91% coverage
- **Python:** 3.12, Django 5.1
- **License:** MIT
