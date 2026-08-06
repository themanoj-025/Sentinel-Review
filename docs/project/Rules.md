# Rules — Sentinel Review: Coding Standards & AI-Agent Operating Rules

| Field | Value |
| --- | --- |
| Version | v0.1 |
| Last Updated | 2026-08-06 |
| Owner | Engineering Lead |
| Status | In Review |

---

## 1. Guiding Principles

1. Staged, independently testable modules — no god functions.
2. Typed context (ReviewContext) through every stage.
3. No silent failures — specific exceptions, review marked FAILED.
4. Security: HMAC, auth, throttles, startup validation.
5. Small PRs only.
6. Tests at every boundary (mocked HTTP/LLM).
7. Docs updated in the same PR.

## 2. Code Style

- Python 3.12, type hints, `from __future__ import annotations`.
- Linter: Ruff (strict); typecheck: mypy strict.
- Structure:

```
backend/
  sentinel_review/
    models/       # 6 ORM models
    webhooks/     # HMAC + view
    workers/      # 7 stages, LLM, GitHub, cache, circuit breaker
    dashboard/    # 5 pages
    api/          # DRF + health + metrics
  tests/          # 22 files, 352 tests
.github/actions/sentinel-review/  # GHA composite
docs/             # mkdocs, 22 ADRs
```

## 3. Git Workflow

- Branches: `feat/<slug>`, `fix/<slug>`, `security/<slug>`.
- Commits: Conventional Commits.
- PRs: ≤ 400 lines; CI green (6 jobs); 1+ reviewer.
- Merge: squash to main.
- CODEOWNERS in place.

## 4. Testing Requirements

- Coverage ≥ 91% (current); mypy strict.
- MUST have tests: HMAC, schemas, cache, circuit breaker, ignore rules, GHA runner, health, E2E.
- See [Testing.md](../technical/Testing.md).

## 5. AI Agent Operating Rules

- Always read Tracker.md and ImplementationPlan.md before starting.
- Never mark a task 🟢 Done without tests passing.
- Never invent requirements not in ../product/PRD.md/../technical/TechSpec.md — flag ambiguity.
- Always update ../technical/Schema.md when models change.
- Never commit secrets; env vars per ../technical/SecurityAndCompliance.md.
- Keep the staged pipeline architecture — no new god functions.
- State conflicts rather than silently picking one.

## 6. Security Baseline Rules

- HMAC-SHA256 constant-time verification on webhooks.
- Startup validation: ImproperlyConfigured on missing secrets.
- DRF throttles (100/hr anon, 1000/hr auth); IsAuthenticated on writes.
- Log redaction (secrets never logged).
- Semgrep in CI (pinned SHA).
- Dependency scanning cadence: weekly.

## 7. Documentation Rules

- Model changes → ../technical/Schema.md same PR.
- Endpoint changes → ../technical/API.md same PR.
- New decisions → ADR in docs/../decisions/decisions.md.

## 8. Prohibited Patterns

| Anti-pattern | Why |
| --- | --- |
| `except Exception: pass` | Silent failures (audit finding) |
| AllowAny on write endpoints | Forgery vector (P0 audit fix) |
| Default secrets in prod | Startup validation |
| God functions | Audit remediation |
| Posting unvalidated LLM output | Malformed comments |
| Unpinned action versions | Supply-chain risk |

## 9. Escalation Rules

**Ask a human when:** GitHub App credential changes, LLM provider changes, new severity categories, security incidents.
**Decide autonomously:** stage refactors, tests, caching, logging, ignore rules.

## 10. Related Documents

| Document | Relationship |
| --- | --- |
| [Testing.md](../technical/Testing.md) | Test requirements |
| [SecurityAndCompliance.md](../technical/SecurityAndCompliance.md) | Security baseline |
| [PRD.md](../product/PRD.md) | Requirements |
| [TechSpec.md](../technical/TechSpec.md) | Architecture |
| [AppFlow.md](../design/AppFlow.md) | Flows |
| [Design.md](../design/Design.md) | Design |
| [Schema.md](../technical/Schema.md) | Data |
| [ImplementationPlan.md](ImplementationPlan.md) | Tasks |
| [Tracker.md](Tracker.md) | Status |
| [API.md](../technical/API.md) | Contract |
| [Deployment.md](../technical/Deployment.md) | Env vars |
| [Glossary.md](../reference/Glossary.md) | Vocabulary |
| [RiskRegister.md](RiskRegister.md) | Risks |
