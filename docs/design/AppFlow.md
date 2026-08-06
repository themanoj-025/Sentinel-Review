# AppFlow — Sentinel Review: Application Flow

|Field|Value|
|---|---|
|Version|v0.1|
|Last Updated|2026-08-06|
|Owner|PM / QA|
|Status|In Review|

---

## 1. Screen Inventory

|SCR-###|Screen|Purpose|Entry|Exit|Auth|
|---|---|---|---|---|---|
|SCR-001|Home|KPI cards, recent reviews, 7-day trend|`/`|all|Yes|
|SCR-002|Repositories|Searchable list (HTMX)|`/repos/`|detail|Yes|
|SCR-003|Repo Detail|Config panel + review history|`/repos/{id}/`|—|Yes|
|SCR-004|Review Detail|Comments + 👍/👎 counts|`/reviews/{id}/`|—|Yes|
|SCR-005|Analytics|Usefulness, volume, trends|`/stats/`|—|Yes|
|SCR-006|Django Admin|Admin CRUD|`/admin/`|—|Staff|
|SCR-007|API Docs|Swagger UI|`/api/docs/`|—|—|
|SCR-008|Health|`/health/` + `/health/ready/`|ops|—|—|

## 2. Navigation Map

```mermaid
graph LR
    HOME[Home] --> REPS[Repositories]
    REPS --> RD[Repo Detail]
    RD --> REV[Review Detail]
    HOME --> STATS[Analytics]
    HOME --> ADMIN[Django Admin]
    HOME --> DOCS[API Docs]
    HOME --> HEALTH[Health]
```

## 3. Detailed Flow per Journey

### Review lifecycle

```mermaid
stateDiagram-v2
    [*] --> RECEIVED: webhook
    RECEIVED --> VERIFIED: HMAC ok
    VERIFIED --> QUEUED: 202
    QUEUED --> UPSERTING: worker
    UPSERTING --> FETCHING: records saved
    FETCHING --> CONTEXTING: diff fetched
    CONTEXTING --> REVIEWING: LLM (+cache check)
    REVIEWING --> SEMGREPING
    SEMGREPING --> DEDUPING
    DEDUPING --> POSTING
    POSTING --> COMPLETED: comments posted
    COMPLETED --> [*]
    UPSERTING --> FAILED: private repo / error
    REVIEWING --> FAILED: provider down (after retries)
```

### Feedback loop

```mermaid
stateDiagram-v2
    [*] --> POSTED: comment posted
    POSTED --> REACTED: 👍/👎 event
    REACTED --> RECORDED: feedback saved
    RECORDED --> [*]: stats updated
```

## 4. Empty / Loading / Error States

|Screen|Empty|Loading|Error|
|---|---|---|---|
|Home|"No reviews yet"|skeleton|API error|
|Repos|"No repos"|HTMX indicator|—|
|Review Detail|"No comments"|—|404|
|Analytics|"No data"|chart load|—|

## 5. Edge Cases & Branching Logic

|IF condition|THEN route|
|---|---|
|HMAC invalid|400, no enqueue|
|Same delivery_id|200 idempotent skip|
|Private repo not opted in|Skip with log|
|LLM cache hit|Skip LLM call (<1ms)|
|Semgrep unavailable|Non-fatal skip|
|Malformed LLM JSON|Corrective retry once|
|Provider circuit OPEN|Cache/backoff, mark failed after retries|
|.sentinel-ignore match|Filtered out|

## 6. Notifications & Re-engagement

|Trigger|Channel|Destination|
|---|---|---|
|Review comments|GitHub inline|PR thread|
|Review failure|logs + Sentry|operators|
|Feedback|webhook → dashboard|stats|

## 7. Cross-Platform Deltas

- Server mode (webhook + dashboard) vs GHA mode (no server) — same pipeline core.

## 8. Related Documents

|Document|Relationship|
|---|---|
|[PRD.md](../product/PRD.md)|US-001…007|
|[TechSpec.md](../technical/TechSpec.md)|Components|
|[Design.md](Design.md)|Screens|
|[Schema.md](../technical/Schema.md)|Entities|
|[ImplementationPlan.md](../project/ImplementationPlan.md)|Tasks|
|[Tracker.md](../project/Tracker.md)|Status|
|[Rules.md](../project/Rules.md)|Standards|
|[API.md](../technical/API.md)|Endpoints|
|[SecurityAndCompliance.md](../technical/SecurityAndCompliance.md)|Security|
|[Testing.md](../technical/Testing.md)|Tests|
|[Deployment.md](../technical/Deployment.md)|Env|
|[Glossary.md](../reference/Glossary.md)|Vocabulary|
|[RiskRegister.md](../project/RiskRegister.md)|Risks|
