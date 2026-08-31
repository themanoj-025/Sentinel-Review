"""
Circuit breaker simulated-outage integration test.

Exercises the full state machine (CLOSED → OPEN → HALF_OPEN → CLOSED)
simulating consecutive 5xx responses from an external dependency.
"""

from __future__ import annotations

import time

import pytest
from sentinel_review.workers.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
)


class TestCircuitBreakerStateMachine:
    """Full state machine: CLOSED → OPEN → HALF_OPEN → CLOSED."""

    def setup_method(self) -> None:
        """Create a fresh breaker with low thresholds for fast tests."""
        self.cb = CircuitBreaker(
            name="test_breaker",
            failure_threshold=3,
            recovery_timeout=0.05,  # 50ms cooldown for fast testing
        )

    def test_closed_accepts_requests(self) -> None:
        """In CLOSED state, requests pass through normally."""
        result = self.cb.call(lambda: "success")
        assert result == "success"
        assert self.cb.state == CircuitState.CLOSED
        assert self.cb.total_calls == 1

    def test_consecutive_failures_open_circuit(self) -> None:
        """Crossing failure_threshold transitions from CLOSED to OPEN."""
        call_count = [0]

        def failing_fn() -> None:
            call_count[0] += 1
            raise ConnectionError("Simulated 5xx")

        for _i in range(3):
            with pytest.raises(ConnectionError):
                self.cb.call(failing_fn)

        assert call_count[0] == 3
        assert self.cb.state == CircuitState.OPEN
        assert self.cb.failure_count == 3

    def test_open_rejects_fast(self) -> None:
        """In OPEN state, requests are rejected immediately (no fn call)."""
        for _ in range(3):
            with pytest.raises(ConnectionError):
                self.cb.call(lambda: (_ for _ in ()).throw(ConnectionError("fail")))

        assert self.cb.state == CircuitState.OPEN

        # Track whether fn was called — it shouldn't be when OPEN
        fn_called = [False]

        def should_not_be_called() -> None:
            fn_called[0] = True
            return "should not reach"

        with pytest.raises(CircuitBreakerOpenError):
            self.cb.call(should_not_be_called)

        assert fn_called[0] is False, "Function should not be called when circuit is OPEN"

    def test_recovery_timeout_transitions_to_half_open(self) -> None:
        """After recovery_timeout, OPEN state transitions to HALF_OPEN on next call."""
        for _ in range(3):
            with pytest.raises(ConnectionError):
                self.cb.call(lambda: (_ for _ in ()).throw(ConnectionError("fail")))

        assert self.cb.state == CircuitState.OPEN

        # Wait for cooldown to elapse
        time.sleep(0.06)

        # The next call should transition to HALF_OPEN and attempt the function
        with pytest.raises(ConnectionError):
            self.cb.call(lambda: (_ for _ in ()).throw(ConnectionError("still failing")))

        # After the cooldown, the circuit should have tried HALF_OPEN
        # (We can't easily assert HALF_OPEN since it transitions immediately)
        assert self.cb.state == CircuitState.OPEN, "Should stay OPEN if HALF_OPEN probe also fails"
        assert self.cb.failure_count == 4

    def test_half_open_success_closes_circuit(self) -> None:
        """A successful call in HALF_OPEN transitions to CLOSED."""
        # Open the circuit first
        for _ in range(3):
            with pytest.raises(ConnectionError):
                self.cb.call(lambda: (_ for _ in ()).throw(ConnectionError("fail")))

        assert self.cb.state == CircuitState.OPEN

        # Wait for cooldown
        time.sleep(0.06)

        # HALF_OPEN probe succeeds
        result = self.cb.call(lambda: "recovered")
        assert result == "recovered"
        assert self.cb.state == CircuitState.CLOSED
        assert self.cb.failure_count == 0

    def test_fast_fail_no_outbound_calls_when_open(self) -> None:
        """When circuit is OPEN, no outbound calls are made."""
        for _ in range(3):
            with pytest.raises(ConnectionError):
                self.cb.call(lambda: (_ for _ in ()).throw(ConnectionError("fail")))

        outbound_count = [0]

        def track_outbound() -> None:
            outbound_count[0] += 1
            return "data"

        with pytest.raises(CircuitBreakerOpenError):
            self.cb.call(track_outbound)

        assert outbound_count[0] == 0, "Zero outbound calls should be made when circuit is OPEN"

    def test_reset_recovers_immediately(self) -> None:
        """Manual reset transitions from OPEN to CLOSED immediately."""
        for _ in range(3):
            with pytest.raises(ConnectionError):
                self.cb.call(lambda: (_ for _ in ()).throw(ConnectionError("fail")))

        assert self.cb.state == CircuitState.OPEN

        self.cb.reset()
        assert self.cb.state == CircuitState.CLOSED
        assert self.cb.failure_count == 0

        # Subsequent call should work
        result = self.cb.call(lambda: "recovered after reset")
        assert result == "recovered after reset"
