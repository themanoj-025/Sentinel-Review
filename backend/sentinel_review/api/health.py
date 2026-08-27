"""
Health check endpoints for liveness and readiness probes.

- /health/     — Liveness: returns 200 if the app process is alive
- /health/ready/ — Readiness: returns 200 if DB, Redis, and Celery are reachable
"""

from __future__ import annotations

import os

from django.db import OperationalError, DatabaseError, connection
from django.http import HttpRequest, JsonResponse

SENTINEL_VERSION = os.environ.get("SENTINEL_VERSION", "1.0.0")


def liveness(request: HttpRequest) -> JsonResponse:
    """Simple liveness check — returns 200 as long as the process is running."""
    return JsonResponse({"status": "ok", "version": SENTINEL_VERSION})


def readiness(request: HttpRequest) -> JsonResponse:
    """Readiness check — verifies database and Redis connectivity."""
    checks = {"status": "ok", "version": SENTINEL_VERSION, "checks": {}}

    # Check database connectivity
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            checks["checks"]["database"] = "connected"
    except (OperationalError, DatabaseError) as e:
        checks["status"] = "degraded"
        checks["checks"]["database"] = f"error: {e}"

    # Check Redis / Celery broker connectivity
    redis_url = os.environ.get("CELERY_BROKER_URL", "")
    if redis_url:
        try:
            import redis as redis_lib

            r = redis_lib.from_url(redis_url, socket_connect_timeout=3.0, decode_responses=True)
            r.ping()
            checks["checks"]["redis"] = "connected"
        except (redis_lib.RedisError, OSError) as e:
            checks["checks"]["redis"] = f"error: {e}"
            checks["status"] = "degraded"
    else:
        checks["checks"]["redis"] = "not configured"

    status_code = 200 if checks["status"] == "ok" else 503
    return JsonResponse(checks, status=status_code)
