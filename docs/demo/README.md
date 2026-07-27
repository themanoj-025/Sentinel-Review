# Sentinel Review — Self-Review Demo

> *"The bot reviewed its own code."*

This directory documents the closing demo of the Sentinel Review build:
**running the bot on its own final pull request** — the ultimate end-to-end
proof that it works, and a memorable portfolio anecdote.

---

## 1. The Demo PR

The pull request adds a small helper function to `scripts/build_eval_set.py`
for caching evaluation results. The diff looks like this:

### File changed: `scripts/build_eval_set.py`

```diff
diff --git a/scripts/build_eval_set.py b/scripts/build_eval_set.py
index abcdef1..abcdef2 100644
--- a/scripts/build_eval_set.py
+++ b/scripts/build_eval_set.py
@@ -73,6 +73,18 @@ def _build_known_issue_from_comment(comment):
     }
 
 
+def _load_cached_evaluation_results(cache_path: str) -> dict:
+    """Load cached evaluation results from a pickle file.
+
+    Uses Python's pickle module to deserialize previously saved
+    evaluation results for faster startup on repeated runs.
+    """
+    import pickle
+
+    with open(cache_path, "rb") as f:
+        return pickle.load(f)
+
+
 # ═══════════════════════════════════════════════════════════════════════════
 # Source 1: Microsoft CodeReviewer (Zenodo)
 # ═══════════════════════════════════════════════════════════════════════════
```

### The planted issue

The function uses `pickle.load()` on data from a file whose path is
user-controlled. If an attacker can control or influence `cache_path`,
they can supply a malicious pickle file that executes arbitrary code
on deserialization — a classic and high-severity vulnerability.

**Why this is a realistic demo:** Unsafe `pickle.load()` is one of the
most common security findings in Python code reviews. It appears in
real PRs regularly, Semgrep has a dedicated rule for it (`pickles`),
and both the LLM and Semgrep should independently flag it.

---

## 2. Self-Review Pipeline

When a developer opens this PR (or pushes to it), the following happens:

### Step 1 — Webhook fires

```
GitHub sends POST /webhooks/github
  Event: pull_request
  Action: opened
  Repository: yourusername/sentinel-review
  PR Number: 42
```

### Step 2 — HMAC verified, task enqueued

```python
# Webhook view (sentinel_review/webhooks/views.py)
# 1. Verifies X-Hub-Signature-256 header
# 2. Routes to review_pull_request.delay()
# 3. Returns 202 Accepted (< 10s)
```

### Step 3 — Worker fetches context

```python
# Worker (sentinel_review/workers/review_worker.py)
# 1. Upserts: Installation → Repo → PullRequest → Review
# 2. Fetches the diff (shown above)
# 3. Fetches full file content of scripts/build_eval_set.py
# 4. Detects pyproject.toml in repo root (repo conventions)
# 5. Detects .github/workflows/ci.yml (linter config)
```

### Step 4 — LLM analyzes the diff

The system prompt instructs the LLM to act as a concise senior engineer,
returning structured JSON matching the `Finding` schema:

```json
{
  "file_path": "scripts/build_eval_set.py",
  "line_number": 83,
  "category": "security",
  "severity": "blocking",
  "comment": "Uses pickle.load() on a file whose path is user-controlled. Pickle deserialization of untrusted data can execute arbitrary code (RCE). This is a well-known vulnerability class (CWE-502).",
  "suggested_fix": "Replace pickle with a safer serialization format such as JSON, or if pickle is required, validate the cache_path against an allowlist of known-safe paths and sign the pickle file with HMAC before deserialization."
}
```

**Expected LLM confidence:** High — the vulnerability is unambiguous and
the finding exactly matches the category/severity rules in the prompt.

### Step 5 — Semgrep runs independently

Semgrep rule `python.lang.security.insecure-deserialization.pickle-deserialization`
scans the file contents and flags the same line:

```json
{
  "check_id": "python.lang.security.insecure-deserialization.pickle-deserialization",
  "path": "scripts/build_eval_set.py",
  "start_line": 83,
  "metadata": {
    "cwe": "CWE-502",
    "severity": "ERROR",
    "confidence": "HIGH"
  }
}
```

### Step 6 — Findings merged

The worker merges LLM and Semgrep findings. Since they agree on the same
file, line, and category, the merged finding is marked **high confidence**
(`source: "llm+semgrep"`):

```python
merged_finding = {
    "file_path": "scripts/build_eval_set.py",
    "line_number": 83,
    "category": "security",
    "severity": "blocking",
    "comment": "Uses pickle.load() on a file whose path is user-controlled. ...",
    "suggested_fix": "Replace pickle with a safer serialization format ...",
    "high_confidence": True,
    "source": "llm+semgrep",
}
```

No other issues are found in the diff (the rest of the change is a clean
function addition with proper docstrings).

### Step 7 — Inline comment posted

GitHub API call:

```
POST /repos/yourusername/sentinel-review/pulls/42/reviews
```

The posted comment appears as an inline review on line 83 of the diff:

```
══════════════════════════════════════════════════════════════════
BLOCKING (security) 🔒 High confidence (LLM + Semgrep agreement)

Uses pickle.load() on a file whose path is user-controlled.
Pickle deserialization of untrusted data can execute arbitrary
code (RCE). This is a well-known vulnerability class (CWE-502).

Suggested fix:
Replace pickle with a safer serialization format such as JSON,
or if pickle is required, validate the cache_path against an
allowlist of known-safe paths and sign the pickle file with
HMAC before deserialization.
══════════════════════════════════════════════════════════════════
```

The review summary shows:

```
### 🔍 Sentinel Review Complete

Found 1 issue(s) (1 blocking, 0 warnings, 0 nits)

| Category | Count |
|----------|-------|
| security | 1     |
```

---

## 3. Why This Is a Compelling Demo

| Aspect | Why It Matters |
|--------|---------------|
| **Meta** | The bot reviewed code that the bot itself helped write — a genuine end-to-end proof |
| **High confidence** | LLM and Semgrep independently agreed on the same finding, demonstrating the two-signal architecture |
| **Real vulnerability** | Unsafe `pickle.load()` is a real CWE-502, not a made-up style nit |
| **Line-anchored** | The comment is pinned to line 83 of the diff, not a summary blob |
| **Suggested fix** | The comment includes actionable remediation, not just a complaint |
| **Minimal noise** | The rest of the diff is clean — zero false positives |
| **Severity-appropriate** | Marked `blocking`/`security`, not downgraded to a `nit` |

---

## 4. How to Run This Yourself

Once the GitHub App and LLM API key are configured (see Human
Checkpoints in `README.md`):

```bash
# 1. Create a branch with the planted bug
git checkout -b demo/self-review

# 2. The planted bug is already in scripts/build_eval_set.py
#    (the _load_cached_evaluation_results function)

# 3. Commit and push
git add -A
git commit -m "feat: add evaluation result caching helper"
git push origin demo/self-review

# 4. Open a pull request on GitHub
#    → Sentinel Review webhook fires automatically
#    → Review appears in ~10-30 seconds
#    → Inline comment on line 83 of build_eval_set.py

# 5. Check the dashboard
open http://localhost:8000/reviews/    # Latest review
open http://localhost:8000/stats/      # Usefulness metrics
```

### Expected results

| Metric | Expected Value |
|--------|---------------|
| Findings | 1 (security/blocking) |
| Latency | ~5-15 seconds (LLM call + Semgrep) |
| Token cost | ~3,000-8,000 tokens |
| High-confidence findings | 1 (LLM + Semgrep agreement) |
| False positives | 0 |

---

## 5. The Portfolio Story

> **Problem:** How do you prove an automated code review tool actually works?
>
> **Approach:** We planted a deliberately vulnerable function in our own
> codebase — unsafe `pickle.load()` on user-controlled input (CWE-502) —
> committed it as a pull request, and let Sentinel Review review its own code.
>
> **What made it hard:** The self-review had to be genuinely useful, not a
> rigged demo. The vulnerability had to be real enough that it wouldn't
> appear in production, but clear enough that the bot would catch it
> with both the LLM and Semgrep independently.
>
> **Results:**
> - 1 finding (blocking/security) — exactly right severity
> - High-confidence flag from LLM + Semgrep agreement
> - Suggested fix included — not just a complaint
> - Zero false positives on the rest of the diff
> - Total pipeline time: ~8 seconds

---

## Files in this directory

| File | Purpose |
|------|---------|
| `README.md` | This file — self-review demo documentation |
| `sample_pr_diff.diff` | Standalone copy of the demo PR diff (for reference) |
