"""Telemetry accumulation with flush-on-unmount and clear-on-logout.

SentinelReview accumulates telemetry (installation states, review outcomes,
token usage, error counts) in memory while a worker/process is alive. To
avoid reporting stale telemetry after a restart, deploy, or logout the
accumulated telemetry is:

1. Flushed to persistent append storage on process unmount (Python exit),
   and
2. Cleared on logout (Django ``user_logged_out`` signal) so stale
   telemetry is never reported again.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Mutable accumulator owned by the app/worker process.
_accumulated: dict[str, Any] = {}
_accumulated_lock = threading.Lock()

# Persistent append-only storage (gitignored in deployments).
_STORE_PATH = Path(os.environ.get("SENTINEL_TELEMETRY_STORE", "sentinel_telemetry_store.jsonl"))
_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _append_to_store(payload: dict[str, Any]) -> None:
    """Append a single telemetry record to the persistent store."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    try:
        with open(_STORE_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:  # pragma: no cover - storage is best-effort
        logger.warning("Telemetry flush failed: %s", exc)


def flush() -> int:
    """Flush accumulated telemetry to persistent storage and clear the accumulator.

    Safe to call multiple times; each call drains the current accumulator.
    Returns the number of records flushed.
    """
    with _accumulated_lock:
        records = list(_accumulated.items())
        _accumulated.clear()

    for _key, payload in records:
        _append_to_store(payload)

    logger.info("Telemetry flushed to storage (%d record(s))", len(records))
    return len(records)


def clear() -> int:
    """Clear the in-memory telemetry accumulator (logout path)."""
    with _accumulated_lock:
        count = len(_accumulated)
        _accumulated.clear()
    logger.info("Telemetry accumulator cleared (%d entry/entries)", count)
    return count


def record(key: str, payload: dict[str, Any]) -> None:
    """Accumulate a telemetry entry. Overwrites an existing entry with the same key."""
    with _accumulated_lock:
        _accumulated[key] = payload


def accumulated() -> dict[str, Any]:
    """Return a snapshot of the current accumulator (read-only)."""
    with _accumulated_lock:
        return dict(_accumulated)


# ---------------------------------------------------------------------------
# Process-unmount hook: must run after ``flush`` is registered.
# ---------------------------------------------------------------------------

_finished = False


def _unmount_handler() -> None:
    global _finished
    if _finished:
        return
    _finished = True
    flush()


def enable_unmount_flush() -> None:
    """Register the unmount handler (WSGI/ASGI process exit)."""
    if _finished:
        return
    atexit.register(_unmount_handler)


def is_flushed_on_unmount() -> bool:
    """Return True once the unmount flush has been registered."""
    return not _finished
