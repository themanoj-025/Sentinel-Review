# ✦ AI Assistance Disclosure

## Summary

sentinel-review was built with substantial AI assistance. The review
pipeline, static-analysis integration, API, and dashboard were drafted
end-to-end by AI. Human maintainers then reviewed every design decision,
validated the review quality, and wired up the CI and security controls.

## Tools & Models Used

| Tool | Provider / Model | Interface | Approx. dates used |
|---|---|---|---|
| **Claude / Opus** | Anthropic | CLI agent + web chat | 2025-11 → 2026-09 |
| **Cursor** | Anthropic (via IDE) | IDE agent | 2026-03 → 2026-09 |
| **GitHub Copilot** | GitHub | IDE completion | 2025-11 → 2026-09 |

## Scope — What AI Did vs. What Humans Did

- **AI:**
  - First drafts of the review pipeline, API, and dashboard.
  - Initial drafts of `README.md`, `CONTRIBUTING.md`, and the CI
    workflows.
- **Human:**
  - All architecture decisions (pipeline topology, model inputs).
  - Security review — secrets handling, input validation.
  - All evaluation, test suite, CI workflows, and production hardening.
  - The open-source stewardship.

## Estimated AI-Assisted Share

Roughly **60–75%** of lines in `api/`, `review/`, and `dashboard/`
follow AI-generated boilerplate. The business logic, security controls,
and tests are mostly human-authored. This is an estimate, not a measured
statistic — the exact ratio was never instrumented.

## Human Review Process

- Every PR is reviewed line-by-line by the maintainer.
- Security review by maintainer: secrets handling, input validation,
  gitleaks/bandit findings.
- Automated gates: pre-commit (ruff + mypy), pytest (≥ 80% coverage
  floor), gitleaks, trivy, and an AI-disclosure metadata check.

## Known Limitations & Risks

- **LLM hallucination:** the model may over-flag or under-flag a finding;
  the precision/recall evaluation harness catches drift.
- **False positives:** the static-analysis signals are manually tuned to
  the project's baseline.
- **License-contamination risk:** upstream training data may contain code
  copies. The CI gitleaks/bandit gates catch obvious secrets.

## How to Verify

- `git log --all --oneline --grep="assistant\\|ai\\|gen"` and the
  `Co-authored-by:` trailers in recent commits.
- `cat docs/audit/*` — per-repo audit reports.
- `git log --all --oneline --grep="ai-assisted\\|LLM\\|llm"` — the commit
  history trail.

## Last Updated

2026-10-06 · Maintained by `themanoj-025 <code.me.025@gmail.com>`
