"""
Prometheus metrics endpoint for Sentinel Review.

Wires the existing METRICS_ENABLED setting to a real /metrics endpoint.
Tracks review latency, LLM errors, queue depth, and token costs.
"""

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from prometheus_client import REGISTRY, Counter, Gauge, Histogram, generate_latest

# Metrics Definitions

# Review latency histogram (ms)
review_latency = Histogram(
    "sentinel_review_latency_ms",
    "Review latency in milliseconds",
    labelnames=["status"],
    buckets=[500, 1000, 2000, 5000, 10000, 30000, 60000],
)

# LLM API error counter
llm_errors = Counter(
    "sentinel_review_llm_errors_total",
    "Total LLM API errors",
    labelnames=["provider"],
)

# Reviews by outcome
reviews_total = Counter(
    "sentinel_review_reviews_total",
    "Total reviews processed",
    labelnames=["status"],  # completed, failed, skipped
)

# Tokens consumed
token_cost = Counter(
    "sentinel_review_token_cost_total",
    "Total tokens consumed across all LLM calls",
    labelnames=["provider", "model"],
)

# Usefulness rate (set by dashboard)
usefulness_gauge = Gauge(
    "sentinel_review_usefulness_rate",
    "Overall usefulness rate percentage",
)

# LLM response cache hit/miss counters
llm_cache_hits = Counter(
    "sentinel_review_llm_cache_hits_total",
    "Total LLM response cache hits",
)

llm_cache_misses = Counter(
    "sentinel_review_llm_cache_misses_total",
    "Total LLM response cache misses (includes bypasses)",
)

# Celery queue depth (set by a periodic task)
celery_queue_depth = Gauge(
    "sentinel_review_celery_queue_depth",
    "Current Celery queue depth",
    labelnames=["queue"],
)


def metrics_view(request: HttpRequest) -> HttpResponse:
    """Expose Prometheus metrics at /metrics.

    Only available when METRICS_ENABLED=True or DEBUG=True.
    """
    if not settings.METRICS_ENABLED and not settings.DEBUG:
        return HttpResponse("Metrics not enabled", status=404)

    return HttpResponse(
        generate_latest(REGISTRY).decode("utf-8"),
        content_type="text/plain; charset=utf-8",
    )
