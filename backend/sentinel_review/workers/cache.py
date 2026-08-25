"""
LLM response cache — keyed by diff-content hash.

Avoids re-reviewing an unchanged diff on a synchronize event.
Backed by Redis with an in-memory fallback for single-worker / test environments.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import time
from typing import Any

from sentinel_review.workers.llm import LLMResult
from sentinel_review.workers.schemas import Finding

logger = logging.getLogger(__name__)

# Configuration

_CACHE_TTL = 3600  # 1 hour default
_DEFAULT_MAX_ENTRIES = 5000
_CACHE_PREFIX = "llm_cache:"

# Shared Redis client (lazy-initialized singleton to avoid per-call connection overhead)
_redis_client_instance = None

# In-memory store (fallback when Redis is unavailable)
_in_memory_store: dict[str, str] = {}
_in_memory_expiry: dict[str, float] = {}


# Key generation


def _make_key(diff: str, repo_context: str = "") -> str:
    """Generate a cache key from the diff content (and optional repo context)."""
    raw = diff + "|context:" + repo_context
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{_CACHE_PREFIX}{digest}"


# Serialization


def _serialize(result: LLMResult) -> str:
    """Serialize an LLMResult to a JSON string for caching."""
    data: dict[str, Any] = {
        "findings": [f.model_dump() for f in result.findings],
        "raw_output": result.raw_output,
        "total_tokens": result.total_tokens,
        "latency_ms": result.latency_ms,
        "provider": result.provider,
        "model": result.model,
        "validation_success": result.validation_success,
        "error_message": result.error_message,
    }
    return json.dumps(data)


def _deserialize(raw: str) -> LLMResult | None:
    """Deserialize a JSON string back to an LLMResult."""
    try:
        data = json.loads(raw)
        findings = [Finding(**f) for f in data.get("findings", [])]
        return LLMResult(
            findings=findings,
            raw_output=data.get("raw_output", ""),
            total_tokens=data.get("total_tokens", 0),
            latency_ms=data.get("latency_ms", 0),
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            validation_success=data.get("validation_success", True),
            error_message=data.get("error_message", ""),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.warning("Failed to deserialize cached LLM result: %s", e)
        return None


# Redis backend


def _get_redis_client():
    """Get (or create) a shared Redis client from the Celery broker URL.

    Uses a lazy-initialized singleton to avoid per-call connection overhead.
    Returns None if Redis is unavailable or unconfigured.
    """
    global _redis_client_instance
    if _redis_client_instance is not None:
        return _redis_client_instance

    redis_url = os.environ.get("CELERY_BROKER_URL", "")
    if not redis_url:
        return None

    try:
        import redis as redis_lib

        _redis_client_instance = redis_lib.from_url(
            redis_url, socket_connect_timeout=2.0, decode_responses=True
        )
        return _redis_client_instance
    except (ImportError, OSError, ConnectionError):
        return None


# Cache API


def cache_get(diff: str, repo_context: str = "") -> LLMResult | None:
    """Look up a cached LLM result by diff hash.

    Returns the cached LLMResult or None if not found.
    """
    key = _make_key(diff, repo_context)

    # Try Redis first
    redis_client = _get_redis_client()
    if redis_client is not None:
        try:
            raw = redis_client.get(key)
            if raw is not None:
                logger.debug("LLM cache HIT (redis): key=%s", key[:30])
                return _deserialize(raw)
        except (OSError, ConnectionError, ValueError):
            pass  # Fall through to in-memory

    # Try in-memory fallback
    if key in _in_memory_store:
        expiry = _in_memory_expiry.get(key, 0)
        if time.time() < expiry:
            logger.debug("LLM cache HIT (memory): key=%s", key[:30])
            return _deserialize(_in_memory_store[key])
        # Expired — clean up
        _in_memory_store.pop(key, None)
        _in_memory_expiry.pop(key, None)

    logger.debug("LLM cache MISS: key=%s", key[:30])
    return None


def cache_set(diff: str, result: LLMResult, repo_context: str = "", ttl: int | None = None) -> None:
    """Store an LLM result in the cache, keyed by diff hash.

    Args:
        diff: The PR diff content.
        result: The LLMResult to cache.
        repo_context: Optional repo context string (included in hash).
        ttl: Time-to-live in seconds. Defaults to _CACHE_TTL.
    """
    key = _make_key(diff, repo_context)
    serialized = _serialize(result)
    effective_ttl = ttl or _CACHE_TTL

    # Try Redis first
    redis_client = _get_redis_client()
    if redis_client is not None:
        try:
            redis_client.setex(key, effective_ttl, serialized)
            logger.debug("LLM cache SET (redis): key=%s, ttl=%ds", key[:30], effective_ttl)
            return
        except (OSError, ConnectionError, ValueError):
            pass  # Fall through to in-memory

    # In-memory fallback
    _in_memory_store[key] = serialized
    _in_memory_expiry[key] = time.time() + effective_ttl

    # Bounded in-memory store
    if len(_in_memory_store) > _DEFAULT_MAX_ENTRIES:
        # Evict oldest entries
        sorted_keys = sorted(_in_memory_expiry.keys(), key=lambda k: _in_memory_expiry[k])
        for old_key in sorted_keys[: len(sorted_keys) // 2]:
            _in_memory_store.pop(old_key, None)
            _in_memory_expiry.pop(old_key, None)

    logger.debug("LLM cache SET (memory): key=%s, ttl=%ds", key[:30], effective_ttl)


def cache_clear(diff: str, repo_context: str = "") -> None:
    """Remove a specific entry from the cache."""
    key = _make_key(diff, repo_context)

    redis_client = _get_redis_client()
    if redis_client is not None:
        with contextlib.suppress(Exception):
            redis_client.delete(key)

    _in_memory_store.pop(key, None)
    _in_memory_expiry.pop(key, None)
    logger.debug("LLM cache CLEAR: key=%s", key[:30])


def cache_clear_all() -> None:
    """Clear all cached LLM results."""
    # Redis — delete all keys with the cache prefix
    redis_client = _get_redis_client()
    if redis_client is not None:
        try:
            cursor = 0
            while True:
                cursor, keys = redis_client.scan(
                    cursor=cursor, match=f"{_CACHE_PREFIX}*", count=100
                )
                if keys:
                    redis_client.delete(*keys)
                if cursor == 0:
                    break
        except (OSError, ConnectionError, ValueError):
            pass

    # In-memory
    _in_memory_store.clear()
    _in_memory_expiry.clear()
    logger.info("LLM cache cleared")
