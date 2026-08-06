# Glossary — Sentinel Review: Shared Vocabulary

| Field | Value |
| --- | --- |
| Version | v0.1 |
| Last Updated | 2026-08-06 |
| Owner | Tech Writer |
| Status | In Review |

---

| Term | Definition |
| --- | --- |
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
| --- | --- |
| [PRD.md](../product/PRD.md) | Terms used there |
| [TechSpec.md](../technical/TechSpec.md) | Terms used there |
| [AppFlow.md](../design/AppFlow.md) | Terms used there |
| [Design.md](../design/Design.md) | Terms used there |
| [Schema.md](../technical/Schema.md) | Terms used there |
| [ImplementationPlan.md](../project/ImplementationPlan.md) | Terms used there |
| [Tracker.md](../project/Tracker.md) | Terms used there |
| [Rules.md](../project/Rules.md) | Terms used there |
| [API.md](../technical/API.md) | Terms used there |
| [SecurityAndCompliance.md](../technical/SecurityAndCompliance.md) | Terms used there |
| [Testing.md](../technical/Testing.md) | Terms used there |
| [Deployment.md](../technical/Deployment.md) | Terms used there |
| [RiskRegister.md](../project/RiskRegister.md) | Terms used there |
