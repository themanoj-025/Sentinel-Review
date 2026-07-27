# Sentinel Review — Evaluation Report

> *Generated: 2026-07-27*
> *Mode: Mock (rule-based pattern matching)*
> *Fixtures: 6 entries, 9 known issues*
> *Duration: 0.0s*

---

## Results Summary

| Metric | Value |
|--------|:-----:|
| Precision | 100.0% |
| Recall | 88.9% |
| F1 Score | 0.941 |
| True Positives | 8 |
| False Positives | 0 |
| False Negatives | 1 |

### By Category

| Category | Known Issues | TP | FP | FN | Precision | Recall |
|----------|:------------:|:--:|:--:|:--:|:---------:|:------:|
| bug | 3 | 2 | 0 | 1 | 100% | 67% |
| security | 6 | 6 | 0 | 0 | 100% | 100% |

---

## Multi-Model Comparison

> **Note:** These results are from **mock** mode. In mock mode, both providers use the same rule-based analyzer, so precision/recall are identical. The latency and cost figures reflect the mock pipeline overhead, not real API latency. Run with `--mode live` and valid API keys for real provider comparison.

To run a live comparison:

```bash
# Requires both ANTHROPIC_API_KEY and OPENAI_API_KEY
python scripts/run_comparison.py --mode live --output docs/evaluation-report.md
```

| Provider | Model | Precision | Recall | F1 | Avg Latency | Total Tokens | Est. Cost |
|----------|:-----:|:---------:|:------:|:--:|:-----------:|:------------:|:---------:|
| **Anthropic** | `claude-sonnet-4-20250514` | 100% | 89% | 0.94 | 0ms | 0 | — |
| **Openai** | `gpt-4o` | 100% | 89% | 0.94 | 0ms | 0 | — |


## Per-Fixture Breakdown

### Evaluation Results (mock mode)

| Fixture | Known Issues | TP | FP | FN | Precision | Recall | F1 |
|---------|:------------:|:--:|:--:|:--:|:---------:|:------:|:--:|
| sql_injection | 2 | 2 | 0 | 0 | 100% | 100% | 1.00 |
| hardcoded_secret | 3 | 3 | 0 | 0 | 100% | 100% | 1.00 |
| unsafe_deserialization | 1 | 1 | 0 | 0 | 100% | 100% | 1.00 |
| off_by_one | 2 | 1 | 0 | 1 | 100% | 50% | 0.67 |
| clean | 0 | 0 | 0 | 0 | — | — | — |
| missing_test | 1 | 1 | 0 | 0 | 100% | 100% | 1.00 |
| **Total** | **9** | **8** | **0** | **1** | **100%** | **89%** | **0.94** |

### Fixture Details

#### sql_injection

**True Positives:**
- ✅ `users.py:6` (security/blocking) — SQL injection vulnerability
- ✅ `users.py:11` (security/blocking) — SQL injection vulnerability

#### hardcoded_secret

**True Positives:**
- ✅ `config.py:2` (security/blocking) — Hardcoded API secret key
- ✅ `config.py:3` (security/blocking) — Hardcoded password
- ✅ `config.py:4` (security/blocking) — Hardcoded Django SECRET_KEY

#### unsafe_deserialization

**True Positives:**
- ✅ `api.py:5` (security/blocking) — Unsafe `pickle.loads` on untrusted input

#### off_by_one

**True Positives:**
- ✅ `processor.py:8` (bug/blocking) — Off-by-one error

**False Negatives (missed):**
- ⚠️ `processor.py:9` (bug) — Related off-by-one issue on a second line

#### clean

- No known issues and no findings (correct).

#### missing_test

**True Positives:**
- ✅ `calculator.py:2` (bug/blocking) — Missing zero-division guard

---

## Test Suite

### Current Test Coverage

| File | Tests | Area |
|------|:-----:|------|
| `test_signature.py` | 10 | HMAC verification |
| `test_schemas.py` | 22 | Pydantic validation |
| `test_github_client.py` | 11 | GitHub API client |
| `test_llm.py` | 13 | LLM provider |
| `test_semgrep.py` | 12 | Semgrep integration |
| `test_webhook.py` | 9 | Webhook views |
| `test_models.py` | 27 | Model schema + constraints |
| `test_review_worker.py` | 21 | Full pipeline with mocks |
| `test_feedback.py` | 5 | Feedback loop |
| `test_cache.py` | 19 | LLM response cache |
| `test_e2e.py` | 6 | End-to-end pipeline |
| `test_startup.py` | 4 | Startup validation + auth |
| `test_ignore_rules.py` | 26 | .sentinel-ignore support |
| `test_circuit_breaker.py` | 15 | Circuit breaker |
| `test_logging.py` | 8 | JSON logging |
| `test_health.py` | 8 | Health endpoints |
| `test_gha_review.py` | 18 | GHA execution mode |
| `test_metrics.py` | 4 | Prometheus metrics |
| **Total** | **237** | |

### Recent Additions (Post-Remediation)

| Test | What It Covers |
|------|---------------|
| `test_e2e.py` | Full webhook→Celery→GitHub→LLM→database flow (6 tests) |
| `test_cache.py` | LLM cache key gen, serialization, in-memory ops, TTL, clear (19 tests) |
| `test_startup.py` | `ImproperlyConfigured` on missing secrets, auth rejection (4 tests) |
| `test_ignore_rules.py` | `.sentinel-ignore` parsing, fnmatch matching, finding filtering (26 tests) |
| `test_circuit_breaker.py` | CLOSED/OPEN/HALF_OPEN transitions, recovery, thundering herd prevention (15 tests) |
| `test_logging.py` | JSON formatter, structured fields, env-var control (8 tests) |
| `test_health.py` | Liveness/readiness endpoints, DB/Redis checks (8 tests) |
| `test_gha_review.py` | GHA runner: diff, LLM, dedup, posting, error paths (18 tests) |
| `test_metrics.py` | Prometheus metric registry, counters, histograms (4 tests) |

---

## Methodology

### Metric Definitions

```
Precision = TP / (TP + FP)   — How many of our findings are correct?
Recall    = TP / (TP + FN)   — How many real issues did we catch?
F1        = 2 × P × R / (P + R) — Harmonic mean of precision and recall
```

### Matching Criteria

A finding is considered a **True Positive** if it matches a known issue on:

1. **file_path** — same file
2. **line_number** — same line (or both null for file-level findings)
3. **category** — same category (`bug`, `security`, `style`, `suggestion`)

If a finding doesn't match any known issue, it's a **False Positive**.
If a known issue isn't matched by any finding, it's a **False Negative**.

### Mode: Mock

This evaluation was run in **mock** mode using rule-based pattern matching
to simulate LLM output. Results may differ when using a real LLM provider
(run with `--mode live`).

### Reproducibility

```bash
# Regenerate evaluation set
python scripts/build_eval_set.py --sources fixtures

# Re-run evaluation (mock mode)
python scripts/run_evaluation.py --output docs/evaluation-report.md --mode mock

# Re-run evaluation with live LLM provider
python scripts/run_evaluation.py --output docs/evaluation-report.md --mode live
```

---

## Limitations

- **Planted-bug set is small (9 known issues):** Statistical significance
  requires 100+ fixtures across more languages
- **Python-only:** All fixtures are Python — no JS/TS/Go/Ruby coverage
- **Mock mode:** Rule-based patterns miss context-dependent issues an LLM
  would catch; live numbers will differ
- **No production data:** Usefulness metrics require real deployment with
  actual PR reviews and human feedback
