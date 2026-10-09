# Known Limitations

> *Last updated: 2026-07-27*
>
> This document states plainly what Sentinel Review does **not** do.
> A clear, confident limitations section reads as more senior than
> pretending there are none — it shows we understand the problem space
> deeply enough to know where the edges are.

---

## No Multi-Region / High-Availability Deployment

The reference deployment (Docker Compose or single Fly.io VM) runs all
services on one machine: Django web server, Celery worker, PostgreSQL,
Redis, and Flower. There is no load balancer, no read replica, and no
failover mechanism. For a production multi-tenant SaaS, you would need:

- Multiple Django/Gunicorn instances behind a load balancer
- PostgreSQL with streaming replicas and automated failover
- Redis Sentinel or a managed Redis service for HA
- Celery workers on separate instances with autoscaling

**Why it's not done:** The current deployment targets ~10-50 repos.
The single-instance architecture handles that scale fine. Adding HA
before there's proven demand would be premature optimization.

---

## No Fine-Tuned Model

The LLM review uses general-purpose models (Claude Sonnet 4, GPT-4o)
with prompt engineering. There is no fine-tuned model specifically
trained on code review data. A fine-tuned model would likely achieve
higher precision and recall, especially for project-specific patterns.

**Why it's not done:** Fine-tuning requires a large, high-quality
dataset of reviewed diffs with human-verified labels. Building that
dataset is a significant project in itself. The prompt-based approach
is a pragmatic starting point that still delivers useful results.

---

## No Vision / Multimodal Diff Review

The system reviews code diffs (text) only. It cannot analyze:
- UI screenshots or visual regressions
- Architecture diagrams
- Log files or screenshots attached to PR descriptions
- Screen recordings of bugs

**Why it's not done:** Multimodal LLM support adds significant
complexity (image processing, storage, context window management)
and cost. It would be a valuable feature for a v2 but is out of
scope for the initial release.

---

## Cost Estimates Are Approximate

The `estimated_cost_usd` field on each review is computed from:
- Reported token counts from the LLM provider
- A static pricing table that must be manually updated when
  provider pricing changes
- An assumed 3:1 input-to-output token ratio when exact counts
  aren't available

The estimate is intended for **cost awareness**, not billing.
It may differ from your actual invoice due to:
- Cached responses (no cost, but estimate may still show tokens)
- Provider-specific rounding and minimums
- Pricing changes between updates to the price table

---

## No Multi-Tenant Isolation

All repositories share the same database and queue. There is no
per-tenant data isolation, no tenant-specific rate limiting, and
no usage-based billing telemetry. For a multi-org SaaS deployment,
you would need:

- Row-level security or schemas-per-tenant in PostgreSQL
- Tenant-scoped Celery queues with prioritization
- Per-tenant rate limiting and usage tracking

**Why it's not done:** The project currently operates as a single-tenant
installation (one organization's GitHub App). Multi-tenant isolation
is a cross-cutting architectural concern best added intentionally,
not retrofitted.

---

## Evaluation Set Is Small

The planted-bug fixture set covers **14 known issues across 8 fixtures**
(6 Python, 1 TypeScript, 1 Go). While this is sufficient for basic
validation and regression detection, it is not statistically significant
for claiming general-purpose code review accuracy. A production-grade
evaluation set would have:

- 500+ fixtures across 10+ languages
- Real-world (not planted) bugs drawn from CVE databases
- Edge cases: empty diffs, gigantic diffs, generated code, vendored deps

**Why it's small:** Building high-quality evaluation fixtures is
labor-intensive. The current set is designed to catch regressions
and demonstrate the evaluation framework, not to be a comprehensive
benchmark. The `scripts/run_evaluation.py` framework is designed to
make it easy to add new fixtures over time.

---

## Mock-Only Evaluation Numbers

The `docs/evaluation-report.md` currently shows **mock provider**
numbers (rule-based pattern matching). These are illustrative of the
evaluation harness, not representative of real LLM accuracy.

**Live LLM numbers require:**
- Real Anthropic and/or OpenAI API keys
- ~$2-5 per full evaluation run
- Running: `python scripts/run_evaluation.py --mode live`

Until live numbers are generated and published, all precision/recall/F1
claims should be understood as upper bounds from a deterministic
pattern-matching analyzer, not real-world LLM performance.

---

## No Automatic Dependency Updates

The Dependabot configuration detects outdated dependencies but does
not auto-merge any updates (even patch-level). Auto-merge for
low-risk updates (documented in `docs/../decisions/decisions.md`) is planned but
not yet implemented.

**Why it's not done:** Auto-merge requires a mature test suite with
strong coverage and fast CI feedback. While the current test suite
is solid (159 tests), it does not yet have the coverage breadth to
catch every regression from a dependency bump.

---

## No Multi-Language LLM Evaluation

The mock provider has no rules for JavaScript, TypeScript, or Go
vulnerability patterns. The evaluation fixtures for these languages
exist but score 0 TP / 5 FN in mock mode. Live LLM evaluation
is needed to demonstrate real multi-language capability.

---

## No Automated UI Tests

The dashboard frontend (Django templates + HTMX + Alpine.js) has no
automated browser tests. There are template-rendering unit tests,
but no tests verify:
- HTMX interactions (clicking "load more", submitting forms)
- JavaScript behavior (Chart.js rendering, Alpin.js toggles)
- Responsive layout at different viewport sizes

A tool like Playwright or Cypress would be needed for this.

---

## Summary

These limitations are not flaws — they are conscious scope decisions.
Every item above represents a known, documented boundary that could
be extended as the project and its user base grow. The architecture
is designed to accommodate all of them without structural changes.
