# Sentinel Review — Documentation Index

Single home for all Sentinel Review documentation. Sentinel Review is an
autonomous GitHub PR-review agent with a 7-stage pipeline, LLM caching, and
real evaluation results.

**Start here:** [architecture.md](architecture.md) (system map) →
[folder_structure.md](folder_structure.md) (repo tree) →
[technical/TechSpec.md](technical/TechSpec.md) (build details).

## Structure

```
docs/
├── README.md                      ← this index
├── architecture.md                system architecture
├── folder_structure.md            repository + docs tree
├── module_dependency.md           dependency graph
├── package_overview.md            module inventory
├── startup_flow.md                boot + review flow
├── community/
│   ├── CHANGELOG.md               changelog
│   ├── CODE_OF_CONDUCT.md         code of conduct
│   ├── CONTRIBUTING.md            contribution guide
│   └── SECURITY.md                security policy
├── decisions/
│   └── decisions.md               decision log
├── design/
│   ├── AppFlow.md                 app screens / states / flows
│   └── Design.md                  design decisions
├── product/
│   └── PRD.md                     product requirements
├── project/
│   ├── analysis_report.md         repo inventory & classification
│   ├── ImplementationPlan.md      implementation plan
│   ├── RiskRegister.md            risks & mitigations
│   ├── Rules.md                   engineering rules
│   └── Tracker.md                 status tracker
├── reference/
│   ├── index.md                   reference index
│   ├── evaluation-report.md       evaluation results (48 files, 7 stages)
│   ├── Glossary.md                terminology
│   └── limitations.md             known limitations
├── technical/
│   ├── API.md                     endpoint reference
│   ├── Deployment.md              deployment guide
│   ├── Schema.md                  data model
│   ├── SecurityAndCompliance.md   security baseline
│   ├── security-notes.md          security implementation notes
│   ├── TechSpec.md                technical spec
│   └── Testing.md                 test strategy
├── assets/
│   ├── demo/
│   │   ├── README.md              demo walkthrough
│   │   └── sample_pr_diff.diff    sample PR diff
│   ├── grafana/
│   │   ├── prometheus-alerts.yml  alert rules
│   │   └── sentinel-review-dashboard.json  Grafana dashboard
│   └── screenshots/               screenshots dir (placeholder)
├── migration/
│   ├── migration_summary.md       modernization record
│   ├── old_tree_to_new_tree.md    restructure before/after
│   └── file_move_ledger.md        file-move ledger
└── audit/
    ├── cleanup-audit-2026-08-13.md  previous cleanup audit
    └── cleanup-audit-2026-08-15.md  docs de-LLM-ification audit
```

## Guidance

| You want... | Read |
|---|---|
| How the agent works end-to-end | [architecture.md](architecture.md) |
| Evaluation results | [reference/evaluation-report.md](reference/evaluation-report.md) |
| Known limitations | [reference/limitations.md](reference/limitations.md) |
| Demo walkthrough | [assets/demo/README.md](assets/demo/README.md) |
| Grafana assets | [assets/grafana/sentinel-review-dashboard.json](assets/grafana/sentinel-review-dashboard.json) |
| API surface | [technical/API.md](technical/API.md) |
| What's shipped / next | [project/Tracker.md](project/Tracker.md) |
| Risks & follow-ups | [project/RiskRegister.md](project/RiskRegister.md) |
