"""SentinelReview telemetry flush + clear wiring.

Covers both requested exits:

* **Unmount** — flush accumulated telemetry to persistent storage on
  Django process exit (WSGI/ASGI shutdown / server restart / deploy).
* **Logout** — clear the in-memory telemetry accumulator on Django's
  ``user_logged_out`` signal so stale telemetry never gets reported.
"""

from __future__ import annotations

import logging

from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver

from . import telemetry
from .telemetry import accumulated, record

logger = logging.getLogger(__name__)


@receiver(user_logged_out)
def _clear_telemetry_on_logout(sender, request, user, **kwargs):  # type: ignore[override]
    """Clear accumulated telemetry on logout so stale data isn't reported."""
    if user is None:
        return
    logger.info("Logout detected for user=%r — clearing stale telemetry", user.username)
    telemetry.clear()


# Public API used by the auth layer / dashboard.
def flush_telemetry() -> int:
    """Flush accumulated telemetry to persistent storage.

    Returns the number of records flushed.
    """
    return telemetry.flush()


def clear_stale_telemetry() -> int:
    """Clear the in-memory telemetry accumulator (logout path).

    Returns the number of entries cleared.
    """
    return telemetry.clear()


def is_compiled() -> bool:
    """Return True once the unmount-flush registration is finished."""
    return telemetry.is_flushed_on_unmount()
