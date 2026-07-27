# Sentinel Review — Remediation Plan

> **Version:** 2.0  
> **Status:** Active remediation blueprint  
> **Original score:** 5.7/10  
> **Target score:** 9.0/10+  
> **Execution order:** P0 → P1 → P2 → P3 (strict priority, no tier-skipping)

---

## 1. Target Architecture

### 1.1 Services Layer

Refactor from the current flat structure to a **modular, layered architecture** with clear boundaries:

```
sentinel_review/
├── services/              # Business logic — NEW
│   ├── __init__.py
│   ├── review_service.py      # Orchestrates the review pipeline
│   ├── github_service.py      # GitHub API operations
│   ├── llm_service.py         # LLM provider abstraction (moved from workers/)
│   ├── feedback_service.py    # Feedback/usefulness computation
│   └── metrics_service.py     # Prometheus metrics wiring
├── repositories/           # Data access — NEW
│   ├── __init__.py
│   ├── review_repository.py    # Review + Comment queries
│   ├── repo_repository.py      # Repo + Installation queries
│   └── feedback_repository.py  # Feedback queries
├── domain/                 # Domain events — NEW
│   ├── __init__.py
│   ├── events.py              # Event definitions
│   └── dispatcher.py          # In-process signal dispatcher
├── workers/                # Celery tasks — THINNED
│   ├── review_worker.py       # Orchestration only (calls services)
│   └── feedback_worker.py     # Thin wrapper over FeedbackService
├── webhooks/               # Webhook layer — UNCHANGED
├── api/                    # REST API — REFINED
│   └── v1/                    # Versioned endpoints
├── dashboard/              # Dashboard views — REFINED
└── models/                 # Django models — UNCHANGED
```

### 1.2 Pipeline Architecture

`review_pull_request` is redesigned as an explicit **pipeline of named stages**, each receiving/returning a typed context object:

```
ReviewContext
├── installation_id, repo_id, repo_full_name, pr_number
├── diff: str
├── repo_context: GitHubRepoContext
├── file_contents: dict[str, str]
├── llm_findings: list[Finding]
├── semgrep_findings: list[Finding]
├── merged_findings: list[dict]
├── posted_comments: list[Comment]
└── errors: list[str]

Pipeline:
  FetchDiffStage
    ↓ (populates diff, file_contents)
  FetchContextStage
    ↓ (populates repo_context)
  LLMReviewStage       ─┐  ← parallel with SemgrepStage
    ↓                    │
  SemgrepStage ←─────────┘
    ↓ (both merged)
  DedupeStage
    ↓
  FilterStage (by category, max_comments)
    ↓
  PostCommentsStage
```

### 1.3 Domain Events (In-Process)

Lightweight event mechanism to decouple cross-cutting concerns:

```python
# domain/events.py
@dataclass
class ReviewCompleted:
    review_id: int
    repo_full_name: str
    pr_number: int
    findings_count: int
    latency_ms: int
    status: str

@dataclass
class ReviewFailed:
    review_id: int
    error: str

# domain/dispatcher.py
class EventDispatcher:
    _handlers: dict[type, list[callable]]
    def register(self, event_type, handler): ...
    def dispatch(self, event): ...
```

Subscribers (registered in `apps.py` ready hook):
- `SlackNotifier` on `ReviewFailed` / `ReviewCompleted` with blocking findings
- `MetricsCollector` on `ReviewCompleted` (records latency, token cost)

### 1.4 Idempotency

Enforced at two levels:
1. **Webhook level:** Dedup key = `(repo_id, pr_number, delivery_id)` checked before enqueueing
2. **Pipeline level:** `review_pull_request` checks `(repo_id, pr_number, triggered_by, head_sha)` — if a completed review already exists with the same head_sha, skip the LLM call and return cached results

---

## 2. Security Architecture

### 2.1 Authentication Scheme

**FeedbackViewSet:**
- GET (list/retrieve): `IsAuthenticated` + read scoped to the user's installations
- POST (create): Webhook-originated only (HMAC-signed request), OR staff-only for manual entries
- PATCH/PUT/DELETE: Staff-only

**StatsViewSet:**
- GET: `IsAuthenticatedOrReadOnly` — anonymous read of aggregate stats only; authenticated users see their scoped data

### 2.2 Rate Limiting

```python
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "1000/hour",
    },
}
```

Webhook endpoint is exempt from DRF throttling (uses its own HMAC-based guard).

### 2.3 Secrets Policy

- **No fallback defaults.** If `DJANGO_SECRET_KEY`, `WEBHOOK_SECRET`, or `ANTHROPIC_API_KEY` are unset and `DEBUG=False`, raise `ImproperlyConfigured` at startup.
- Local dev still works via `.env.example` + `python-dotenv` integration (actually wire it in).
- The insecure fallback `change-me-in-production` is removed entirely.

### 2.4 CSP Headers

```python
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "https://unpkg.com", "https://cdn.jsdelivr.net", ...)
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")
```

Add via `django-csp` middleware.

### 2.5 Log Redaction Fix

Narrow the hex-match pattern from `[a-fA-F0-9]{40,}` to specifically match known secret formats:
- JWT tokens: `eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}`
- GitHub tokens: `gh[pousvb]_[a-zA-Z0-9_]{36,}`
- API keys: `sk-[a-zA-Z0-9]{20,}`
- Remove the generic `[a-fA-F0-9]{40,}` pattern that catches git SHAs

---

## 3. Scalability & Performance Plan

### 3.1 LLM Response Caching

- Key: `sha256(diff_content)[:16]` 
- Store: Redis with 1-hour TTL
- Invalidation: On new `synchronize` event with different `head_sha`
- Metrics: Cache hit/miss counters via Prometheus

### 3.2 Database Indexes

```python
# Add to Comment.Meta.indexes:
models.Index(fields=["review", "category"]),   # N+1 filter by category
models.Index(fields=["review", "severity"]),   # N+1 filter by severity

# Add to Feedback.Meta.indexes:
models.Index(fields=["comment", "reaction"]),  # Vote counting queries
```

### 3.3 Connection Reuse

```python
# github_client.py
class GitHubClient:
    def __init__(self):
        self._client = httpx.Client(
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=httpx.Timeout(60.0),
        )
```

### 3.4 Pipeline Concurrency

- Stages 1 (FetchDiff) and 2 (FetchContext) run **sequentially** (they share the same auth token)
- Stages 3 (LLM) and 4 (Semgrep) run **in parallel** via `concurrent.futures.ThreadPoolExecutor`
- Merge results after both complete

### 3.5 Celery Result Backend TTL

```python
CELERY_RESULT_EXPIRES = 3600 * 24  # 24 hours
```

### 3.6 API Pagination

```python
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}
```

### 3.7 Scaling Ceiling

The current architecture (single Django app, single Celery queue, single DB) scales to approximately:
- **10K reviews/month** with 1 worker → comfortable
- **50K reviews/month** with 3-4 workers → needs attention
- **100K+ reviews/month** → requires: separate review queues per org, read replicas for dashboard, horizontal web workers, CDN for static assets

At that point, migrate to: K8s (multiple web pods + worker pools), read replicas, and domain-based queue partitioning.

---

## 4. Reliability Plan

### 4.1 LLM Retry Policy

```python
# Retry 1: Same diff, ask model to fix its own JSON
# Retry 2: If still fails, return empty findings with error logged
MAX_LLM_RETRIES = 2
RETRY_DELAY_MS = [0, 1000]  # First retry immediate, second after 1s

def review_with_retry(diff, context):
    for attempt in range(MAX_LLM_RETRIES):
        result = provider.review_diff(diff, context)
        if result.validation_success:
            return result
        if attempt == 0:
            # Corrective retry: tell the model what went wrong
            context["corrective_hint"] = result.error_message
            continue
    return LLMResult(error_message="LLM failed after retries")
```

### 4.2 Circuit Breaker

Simple implementation (no external library):

```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=30):
        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED / OPEN / HALF_OPEN
        self.last_failure_time = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

    def call(self, fn, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
            else:
                raise CircuitBreakerOpenError()
        try:
            result = fn(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
            raise
```

Applied around `GitHubClient._request()` and `LLMProvider.review_diff()`.

### 4.3 Exception Handling Policy

**Rules:**
1. Every `try/except` must catch the **most specific exception type possible**
2. A bare `except Exception` is ONLY allowed at the outermost Celery task boundary, solely to mark the task as `FAILED`
3. Mid-pipeline: catch only `ProgrammingError`, `httpx.HTTPStatusError`, `pydantic.ValidationError`, `ConnectionError`, `TimeoutError`
4. All exceptions must be logged with lazy formatting: `logger.error("...: %s", e)`

**Current sites to fix (10+):**
- `review_worker.py:92` → `except IntegrityError, ObjectDoesNotExist`
- `review_worker.py:117` → `except httpx.HTTPStatusError`
- `review_worker.py:135` → `except (AttributeError, KeyError, ValueError)`
- `review_worker.py:151` → `except Exception` → narrow per operation
- ... (full list in the original audit)

---

## 5. Observability Plan

### 5.1 Structured Logging

```python
class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "task_id": getattr(record, "task_id", None),
            "repo": getattr(record, "repo", None),
            "pr_number": getattr(record, "pr_number", None),
        })
```

### 5.2 Sentry Integration

```python
# settings.py
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.celery import CeleryIntegration

if SENTRY_DSN := os.environ.get("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
    )
```

### 5.3 Health Endpoints

```python
# /health/ — liveness
{"status": "ok", "version": "1.0.0"}

# /health/ready/ — readiness
{"status": "ok", "database": "connected", "redis": "connected", "celery": "reachable"}
```

### 5.4 Prometheus Metrics

Wire the existing `METRICS_ENABLED` flag:

```python
# /metrics — Prometheus endpoint
from prometheus_client import Histogram, Counter, Gauge, generate_latest

review_latency = Histogram("review_latency_ms", "Review latency", buckets=[500, 1000, 2000, 5000, 10000, 30000])
llm_errors = Counter("llm_error_total", "LLM API errors")
queue_depth = Gauge("celery_queue_depth", "Celery queue depth")
usefulness_rate = Gauge("review_usefulness_rate", "Usefulness rate %")
token_cost = Counter("review_token_cost_total", "Total tokens consumed")
```

---

## 6. Frontend Plan

### 6.1 Tailwind Build Pipeline

Replace CDN Tailwind with a compiled CSS file:

1. Use `django-tailwind` or a standalone Tailwind CLI
2. Docker build: Run `npx tailwindcss -i ./src/input.css -o ./static/css/output.css` during the Docker build stage
3. No Node.js runtime dependency in the container — only build-time
4. Results: ~30KB compiled CSS vs ~3MB CDN script

### 6.2 stats.html TemplateSyntaxError Fix

The problematic line:
```django
{% with ratio=cat.usefulness_rate %}
```

**Fix:** Compute the ratio in the view and pass it as a pre-computed field, or use `{{ cat.usefulness_rate }}` directly in the template without `{% with %}`.

### 6.3 Loading States

Add to every HTMX-triggering element:
```html
<button hx-post="..." hx-indicator="#loading-spinner" ...>
<div id="loading-spinner" class="htmx-indicator">Loading...</div>
```

### 6.4 CDN Fallback

```html
<script>
window.chartFallback = function() {
    document.getElementById('charts-section').innerHTML = 
        '<p class="text-gray-400">Charts unavailable — try refreshing.</p>';
};
</script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js" 
        onerror="chartFallback()"></script>
```

---

## 7. API & Documentation Plan

### 7.1 OpenAPI Schema

Add `drf-spectacular`:
```python
INSTALLED_APPS += ["drf_spectacular"]
REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"
SPECTACULAR_SETTINGS = {"TITLE": "Sentinel Review API", "VERSION": "1.0.0"}
```

### 7.2 API Versioning

```python
# urls.py
path("api/v1/", include("sentinel_review.api.v1.urls")),
```

### 7.3 Standard Error Envelope

```python
# api/exceptions.py
class APIError(Exception):
    def __init__(self, error_code, message, details=None, status_code=400):
        self.error_code = error_code
        self.message = message
        self.details = details
        self.status_code = status_code

# In DRF exception handler:
def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        response.data = {
            "error": getattr(exc, "error_code", "error"),
            "message": response.data,
            "details": getattr(exc, "details", None),
        }
    return response
```

### 7.4 Documentation Fixes

- Replace `yourusername` → real repo URL in README
- Add `CHANGELOG.md`
- Add `CODEOWNERS`
- Add deployment troubleshooting guide
- Expand contribution guide (running tests, adding providers, adding categories)

---

## 8. Feature Roadmap (Portfolio Differentiation)

### P3 — Build (high impact, reasonable effort):

| Feature | Effort | Portfolio Impact | Justification |
|---------|--------|-----------------|---------------|
| GitHub Actions mode | 2-3 days | Very High | Shows two integration patterns (webhook + CI) |
| Multi-model ensemble | 2-3 days | Very High | Directly uses existing abstraction, produces comparison table |
| LLM response caching | 1 day | High | Shows caching strategy understanding |
| `.sentinel-ignore` | 1 day | Medium | Shows attention to DX |
| Feature flags | 1 day | Medium | Shows operational maturity |
| Slack notifications | 1-2 days | Medium | Shows integration skills |

### Future / Won't Build Now:

| Item | Reason |
|------|--------|
| Full K8s/Helm | Can't realistically demo solo, needs cluster |
| Multi-region | Infrastructure cost too high for portfolio |
| Fine-tuned model | Requires training data and GPU budget |
| Mobile app | Out of scope for a code review tool |

---

## 9. Testing Strategy

### 9.1 Required Integration Test

Full pipeline end-to-end (using eager Celery):
1. POST valid webhook payload to `/webhooks/github/` with valid HMAC signature
2. Assert `202 Accepted` returned quickly
3. Assert `Review` row created in processing state
4. Assert `Comment` rows created with correct file/line/category/severity
5. Assert `findings_count` on Review matches the number of mocked LLM findings

### 9.2 Coverage Targets

| Module | Current (est.) | Target | Critical paths |
|--------|---------------|--------|----------------|
| `review_worker.py` | ~30% | 85% | Main pipeline, retry, dedup |
| `github_client.py` | ~40% | 80% | Auth, diff fetch, comment posting |
| `feedback_worker.py` | ~50% | 80% | Reaction processing, rate computation |
| `dashboard/views.py` | ~0% | 70% | All views, HTMX partials |
| `webhooks/` | ~80% | 90% | Signatures, event routing |
| `llm.py` | ~70% | 85% | Provider abstraction, retry, validation |

### 9.3 Mocking Policy

- `respx` for all `httpx` calls (no live network)
- `monkeypatch` for Django settings overrides
- `unittest.mock.patch` for LLM provider calls
- Exactly one GitHub-behind-a-flag live integration test, skipped by default, runnable with `pytest --run-live`

---

## 10. Delivery Plan — Prioritized Backlog

### P0 — Critical (must ship first)

| # | Item | Definition of Done |
|---|------|-------------------|
| 1 | Fix `AllowAny` on FeedbackViewSet/StatsViewSet | Test: unauthenticated POST returns 401/403 |
| 2 | Fix `stats.html` TemplateSyntaxError | Test: template renders without error, ratio displays correctly |
| 3 | Replace Tailwind CDN with compiled CSS | Verify: page load drops >2MB, no runtime CSS compilation |
| 4 | Clean requirements.txt | Verify: `pip install -r requirements.txt` installs only prod deps |
| 5 | Pin semgrep-action to SHA | Verify: CI workflow has pinned SHA instead of `@v1` |
| 6 | Remove insecure fallback defaults | Test: `DJANGO_SECRET_KEY=""` + `DEBUG=False` raises at startup |
| 7 | Generate Django migrations | Verify: `python manage.py migrate` succeeds without errors |

### P1 — High Priority

| # | Item | Definition of Done |
|---|------|-------------------|
| 8 | Pipeline refactor | Each stage unit-tested in isolation, Celery task is thin orchestration |
| 9 | Specific exceptions | No `except Exception` remains mid-pipeline; test proves each site |
| 10 | LLM retry logic | Test: malformed JSON triggers corrective retry, not immediate failure |
| 11 | Webhook idempotency | Test: duplicate webhook delivery does not create duplicate Review row |
| 12 | DRF pagination + filtering | Test: list endpoint respects `?page=`, `?search=`, `?category=` |
| 13 | Health endpoints | Test: `/health/` returns 200, `/health/ready/` checks DB+Redis |
| 14 | Rate limiting | Test: 100+ requests from same IP in 1s returns 429 |
| 15 | Composite indexes | Verify: migration creates indexes, query EXPLAIN shows index scans |
| 16 | httpx.Client reuse | Verify: `GitHubClient` uses one client, not one per call |
| 17 | E2E integration test | Test: full webhook→Review→Comment pipeline with mocked deps passes |

### P2 — Reliability & Observability

| # | Item | Definition of Done |
|---|------|-------------------|
| 18 | Structured JSON logging | Verify: log output is parseable JSON with required fields |
| 19 | Sentry integration | Test: deliberately thrown exception appears in Sentry |
| 20 | Prometheus metrics | Verify: `/metrics` returns review_latency, llm_errors, etc. |
| 21 | Circuit breaker | Test: 5 consecutive GitHub failures → circuit opens → after cooldown, half-opens |
| 22 | Log redaction fix | Test: git SHA `abc...` (40 hex chars) NOT redacted; `sk-ant-test...` IS redacted |
| 23 | HTMX loading states | Verify: each hx-trigger has `hx-indicator`, CDN failure shows fallback |
| 24 | Flower auth | Verify: Flower requires `--basic-auth` credentials |
| 25 | OpenAPI + versioning | Verify: `/api/v1/schema/` returns valid OpenAPI JSON |

### P3 — Portfolio Features

| # | Item | Definition of Done |
|---|------|-------------------|
| 26 | LLM response cache | Test: same diff twice → second call hits cache (mocked LLM not invoked) |
| 27 | GitHub Actions mode | Verify: `action.yml` exists and runs review as CI step |
| 28 | Multi-model comparison | Verify: evaluation report includes side-by-side LLM provider table |
| 29 | `.sentinel-ignore` support | Test: ignored file excluded even if LLM flags it |
| 30 | Feature flags | Test: disabling "security" category via config → security findings filtered |
| 31 | Slack notification | Test: domain event dispatched → Slack subscriber called with correct payload |

---

## Start Execution

Move to **Prompt 2** — begin building in P0→P3 order, committing after each verified item.
