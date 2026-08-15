"""
Simple circuit breaker for external service resilience.

Prevents cascading failures by stopping calls to a failing dependency
(Open state) and periodically allowing test requests (Half-Open state)
to detect recovery.
"""

import logging
import time
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"  # Normal operation — requests pass through
    OPEN = "open"  # Failing — requests are rejected immediately
    HALF_OPEN = "half_open"  # Testing — one request allowed to probe recovery


class CircuitBreakerOpenError(Exception):
    """Raised when a circuit breaker is open and rejects a request."""


class CircuitBreaker:
    """Simple circuit breaker with configurable thresholds and recovery.

    Usage:
        cb = CircuitBreaker(name="github_api", failure_threshold=5, recovery_timeout=30)
        try:
            result = cb.call(api_client.make_request, arg1, arg2)
        except CircuitBreakerOpenError:
            result = fallback_value
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: float = 0.0
        self.total_calls = 0
        self.rejected_calls = 0

    def call(self, fn, *args, **kwargs):
        """Execute fn(*args, **kwargs) with circuit breaker protection."""
        self.total_calls += 1

        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                logger.info("Circuit %s: OPEN → HALF_OPEN (recovery timeout elapsed)", self.name)
                self.state = CircuitState.HALF_OPEN
            else:
                self.rejected_calls += 1
                raise CircuitBreakerOpenError(
                    "Circuit '%s' is OPEN — rejecting request (%d failures, "
                    "%ds remaining)"
                    % (
                        self.name,
                        self.failure_count,
                        int(self.recovery_timeout - (time.time() - self.last_failure_time)),
                    )
                )

        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(e)
            raise

    def _on_success(self):
        """Handle a successful call — reset state."""
        if self.state == CircuitState.HALF_OPEN:
            logger.info("Circuit %s: HALF_OPEN → CLOSED (recovery confirmed)", self.name)
        self.state = CircuitState.CLOSED
        self.failure_count = 0

    def _on_failure(self, exception: Exception):
        """Handle a failed call — increment counter, possibly open circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                logger.warning(
                    "Circuit %s: CLOSED → OPEN (%d failures in a row: %s)",
                    self.name,
                    self.failure_count,
                    exception,
                )
                self.state = CircuitState.OPEN
        else:
            logger.debug(
                "Circuit %s: %d/%d failures (%s)",
                self.name,
                self.failure_count,
                self.failure_threshold,
                exception,
            )

    def reset(self):
        """Manually reset the circuit breaker to closed state."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        logger.info("Circuit %s: manually reset to CLOSED", self.name)

    def __repr__(self):
        return "<CircuitBreaker %s: state=%s failures=%d/%d>" % (
            self.name,
            self.state.value,
            self.failure_count,
            self.failure_threshold,
        )


# Global circuit breaker instances
github_circuit_breaker = CircuitBreaker(name="github_api", failure_threshold=5, recovery_timeout=30)
llm_circuit_breaker = CircuitBreaker(name="llm_provider", failure_threshold=3, recovery_timeout=60)
