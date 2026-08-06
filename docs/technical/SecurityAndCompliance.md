# SecurityAndCompliance — Sentinel Review: Security

|Field|Value|
|---|---|
|Version|v0.1|
|Last Updated|2026-08-06|
|Owner|Security Engineer|
|Status|In Review|

---

## 1. Threat Model (STRIDE)

|Threat|Surface|Impact|Mitigation|
|---|---|---|---|
|Spoofing|Webhook forgery|Fake reviews|HMAC-SHA256 constant-time verify|
|Tampering|LLM output|Malformed/false comments|Pydantic validation + corrective retry|
|Repudiation|Reviews|No accountability|Persisted reviews + feedback|
|Info disclosure|Secrets in logs|Credential leak|Log redaction + structured logging|
|DoS|Webhook flood|Queue exhaustion|Rate limits + idempotency|
|Elevation|Write endpoints|Forgery|IsAuthenticated + RBAC|

## 2. Auth / Authorization

- Webhook: HMAC shared secret.
- API: IsAuthenticated on writes; IsAuthenticatedOrReadOnly on reads.
- Throttles: 100/hr anon, 1000/hr auth.
- Startup validation: refuses to boot with missing/default secrets.

## 3. Data Classification

|Data|Class|Handling|
|---|---|---|
|Repo code/diffs|Confidential|transient, deleted after job|
|Secrets found|Critical|redacted, never logged|
|Feedback|Internal|dashboard|
|GitHub tokens|Credential|env/secrets, never committed|

## 4. Encryption

- In transit: TLS (GitHub, LLM APIs).
- At rest: DB at provider; tokens in env.

## 5. Compliance Checklist

- [ ] HMAC on webhooks
- [ ] IsAuthenticated on write endpoints
- [ ] Throttles on API/webhook
- [ ] Log redaction verified (tests)
- [ ] Gitleaks + Semgrep in CI (pinned)
- [ ] Startup validation tests

## 6. Incident Response Plan (outline)

1. Detect: metrics/alert.
2. Triage.
3. Contain: revoke webhook secret / disable repo.
4. Remediate + regression tests.
5. Recover.
6. Postmortem (blameless; see docs/).

## 7. Related Documents

|Document|Relationship|
|---|---|
|[Rules.md](../project/Rules.md)|Security baseline|
|[API.md](API.md)|HMAC + throttles|
|[Schema.md](Schema.md)|Sensitive map|
|[TechSpec.md](TechSpec.md)|NFRs|
|[PRD.md](../product/PRD.md)|Goals|
|[AppFlow.md](../design/AppFlow.md)|Flows|
|[Design.md](../design/Design.md)|Design|
|[ImplementationPlan.md](../project/ImplementationPlan.md)|Tasks|
|[Tracker.md](../project/Tracker.md)|Status|
|[Testing.md](Testing.md)|Security tests|
|[Deployment.md](Deployment.md)|Secrets|
|[Glossary.md](../reference/Glossary.md)|Vocabulary|
|[RiskRegister.md](../project/RiskRegister.md)|Risks|
