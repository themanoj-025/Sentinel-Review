# Glossary — Sentinel Review: Shared Vocabulary

| Field | Value |
|---|---|
| Version | v0.1 |
| Last Updated | 2026-08-06 |
| Owner | Tech Writer |
| Status | In Review |

---

| Term | Definition |
|---|---|
| Pipeline stage | One of 7 named modules with typed ReviewContext |
| ReviewContext | Typed dataclass passed between stages |
| Severity | blocking / warning / nit |
| Category | bug / style / security / suggestion |
| HMAC | Webhook signature verification |
| Idempotency | Dedup by delivery_id |
| Circuit breaker | CLOSED/OPEN/HALF_OPEN provider protection |
| LLM cache | SHA256(diff) → cached review |
| high_confidence | LLM + Semgrep agreement |
| .sentinel-ignore | Glob exclusion file |
| Usefulness | 👍/(👍+👎) rate per comment |
| GHA mode | Zero-infra composite action |
| Corrective retry | Retry LLM with validation error shown |

## Related Documents

| Document | Relationship |
|---|---|
| [PRD.md](PRD.md) | Terms used there |
| [TechSpec.md](TechSpec.md) | Terms used there |
| [AppFlow.md](AppFlow.md) | Terms used there |
| [Design.md](Design.md) | Terms used there |
| [Schema.md](Schema.md) | Terms used there |
| [ImplementationPlan.md](ImplementationPlan.md) | Terms used there |
| [Tracker.md](Tracker.md) | Terms used there |
| [Rules.md](Rules.md) | Terms used there |
| [API.md](API.md) | Terms used there |
| [SecurityAndCompliance.md](SecurityAndCompliance.md) | Terms used there |
| [Testing.md](Testing.md) | Terms used there |
| [Deployment.md](Deployment.md) | Terms used there |
| [RiskRegister.md](RiskRegister.md) | Terms used there |
