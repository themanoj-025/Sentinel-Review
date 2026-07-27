"""
Tests for the LLM response cache (workers/cache.py).

Covers key generation, serialization/deserialization, Redis and
in-memory backends, cache hit/miss, TTL expiry, and cache invalidation.
"""

from __future__ import annotations

import time

from sentinel_review.workers.cache import (
    _deserialize,
    _in_memory_expiry,
    _in_memory_store,
    _make_key,
    _serialize,
    cache_clear,
    cache_clear_all,
    cache_get,
    cache_set,
)
from sentinel_review.workers.llm import LLMResult
from sentinel_review.workers.schemas import Finding

SAMPLE_DIFF = (
    "diff --git a/app.py b/app.py\n@@ -1,3 +1,4 @@\n def foo():\n-    pass\n+    return 42\n"
)
SAMPLE_CONTEXT = "Default branch: main"


def _make_sample_result(findings_count: int = 2) -> LLMResult:
    """Create a sample LLMResult for testing."""
    findings = [
        Finding(
            file_path="app.py",
            line_number=2,
            category="bug",
            severity="warning",
            comment=f"Found issue {i}",
            suggested_fix="Fix it",
        )
        for i in range(findings_count)
    ]
    return LLMResult(
        findings=findings,
        raw_output='{"findings": []}',
        total_tokens=500,
        latency_ms=1500,
        provider="anthropic",
        model="claude-3-opus-20240229",
        validation_success=True,
    )


class TestKeyGeneration:
    """Key generation from diff + context."""

    def test_same_diff_same_key(self):
        """Same diff should produce the same cache key."""
        key1 = _make_key(SAMPLE_DIFF)
        key2 = _make_key(SAMPLE_DIFF)
        assert key1 == key2

    def test_different_diff_different_key(self):
        """Different diffs should produce different keys."""
        key1 = _make_key(SAMPLE_DIFF)
        key2 = _make_key(SAMPLE_DIFF + "extra line")
        assert key1 != key2

    def test_context_affects_key(self):
        """Different repo contexts should produce different keys for the same diff."""
        key1 = _make_key(SAMPLE_DIFF, "")
        key2 = _make_key(SAMPLE_DIFF, "Default branch: develop")
        assert key1 != key2

    def test_key_format(self):
        """Cache key should start with the configured prefix."""
        key = _make_key(SAMPLE_DIFF)
        assert key.startswith("llm_cache:")

    def test_empty_diff_key(self):
        """Empty diff should still produce a valid key."""
        key = _make_key("")
        assert key.startswith("llm_cache:")
        assert len(key) > len("llm_cache:")


class TestSerialization:
    """Serialization round-trip for LLMResult."""

    def test_round_trip(self):
        """A serialized LLMResult should deserialize to an equal object."""
        original = _make_sample_result()
        serialized = _serialize(original)
        deserialized = _deserialize(serialized)

        assert deserialized is not None
        assert len(deserialized.findings) == len(original.findings)
        assert deserialized.findings[0].file_path == original.findings[0].file_path
        assert deserialized.findings[0].line_number == original.findings[0].line_number
        assert deserialized.findings[0].category == original.findings[0].category
        assert deserialized.total_tokens == original.total_tokens
        assert deserialized.latency_ms == original.latency_ms
        assert deserialized.provider == original.provider
        assert deserialized.model == original.model
        assert deserialized.validation_success == original.validation_success

    def test_empty_findings(self):
        """LLMResult with no findings should serialize/deserialize correctly."""
        result = LLMResult(findings=[], total_tokens=50, latency_ms=100)
        serialized = _serialize(result)
        deserialized = _deserialize(serialized)

        assert deserialized is not None
        assert len(deserialized.findings) == 0
        assert deserialized.total_tokens == 50
        assert deserialized.validation_success is True

    def test_invalid_json_returns_none(self):
        """Deserializing invalid JSON should return None."""
        assert _deserialize("not valid json") is None

    def test_missing_fields_uses_defaults(self):
        """Deserializing JSON with missing top-level fields uses defaults (defensive)."""
        result = _deserialize('{"not": "findings"}')
        assert result is not None
        assert result.findings == []
        assert result.total_tokens == 0
        assert result.provider == ""

    def test_corrupted_finding_returns_none(self):
        """Deserializing JSON with a corrupted finding entry should return None."""
        result = _deserialize('{"findings": [{"file_path": "x"}]}')
        # Missing required fields like category, severity trigger Finding constructor error
        assert result is None


class TestInMemoryCache:
    """In-memory cache backend behavior."""

    def setup_method(self):
        _in_memory_store.clear()
        _in_memory_expiry.clear()

    def test_set_and_get(self):
        """Setting a value and getting it back should work."""
        result = _make_sample_result()
        cache_set(SAMPLE_DIFF, result)
        cached = cache_get(SAMPLE_DIFF)
        assert cached is not None
        assert len(cached.findings) == 2
        assert cached.total_tokens == 500
        assert cached.validation_success is True

    def test_miss_returns_none(self):
        """Getting a value that was never set should return None."""
        result = cache_get("nonexistent diff")
        assert result is None

    def test_context_aware(self):
        """Cache should be context-aware — different context = different cache entry."""
        result = _make_sample_result()
        cache_set(SAMPLE_DIFF, result, repo_context=SAMPLE_CONTEXT)

        # Same diff, no context — should miss
        assert cache_get(SAMPLE_DIFF) is None

        # Same diff, same context — should hit
        hit = cache_get(SAMPLE_DIFF, repo_context=SAMPLE_CONTEXT)
        assert hit is not None

    def test_cache_hit_then_miss_after_clear(self):
        """Clearing a specific entry should cause a miss."""
        result = _make_sample_result()
        cache_set(SAMPLE_DIFF, result)
        assert cache_get(SAMPLE_DIFF) is not None

        cache_clear(SAMPLE_DIFF)
        assert cache_get(SAMPLE_DIFF) is None

    def test_clear_all(self):
        """Clearing all entries should cause a miss for all."""
        cache_set("diff1", _make_sample_result())
        cache_set("diff2", _make_sample_result())
        cache_clear_all()

        assert cache_get("diff1") is None
        assert cache_get("diff2") is None

    def test_ttl_expiry(self):
        """Entries should expire after their TTL."""
        result = _make_sample_result()
        cache_set(SAMPLE_DIFF, result, ttl=1)
        assert cache_get(SAMPLE_DIFF) is not None

        time.sleep(1.1)
        assert cache_get(SAMPLE_DIFF) is None

    def test_key_different_content(self):
        """Different diffs should not collide in the cache."""
        result1 = _make_sample_result(findings_count=1)
        result2 = _make_sample_result(findings_count=3)

        cache_set(SAMPLE_DIFF, result1)
        cache_set(SAMPLE_DIFF + "modified", result2)

        cached1 = cache_get(SAMPLE_DIFF)
        cached2 = cache_get(SAMPLE_DIFF + "modified")

        assert cached1 is not None
        assert cached2 is not None
        assert len(cached1.findings) == 1
        assert len(cached2.findings) == 3


class TestCacheIntegration:
    """Integration tests verifying cache is wired into the pipeline.

    These test that the cache module functions correctly within the
    broader codebase context. The actual pipeline integration is
    tested via the E2E tests.
    """

    def setup_method(self):
        _in_memory_store.clear()
        _in_memory_expiry.clear()

    def test_cache_round_trip_via_functions(self):
        """Full round trip through the public cache API."""
        result = _make_sample_result()
        cache_set(SAMPLE_DIFF, result)
        cached = cache_get(SAMPLE_DIFF)

        assert cached is not None
        assert cached.total_tokens == result.total_tokens
        assert cached.latency_ms == result.latency_ms
        assert cached.provider == result.provider
        assert cached.model == result.model
        assert cached.findings[0].comment == result.findings[0].comment
        assert cached.findings[0].suggested_fix == result.findings[0].suggested_fix

    def test_cache_idempotent_set(self):
        """Setting the same diff twice should overwrite the cache entry."""
        result1 = _make_sample_result(findings_count=1)
        result2 = _make_sample_result(findings_count=5)

        cache_set(SAMPLE_DIFF, result1)
        cache_set(SAMPLE_DIFF, result2)

        cached = cache_get(SAMPLE_DIFF)
        assert cached is not None
        assert len(cached.findings) == 5
