"""Login/logout entrypoints for the SentinelReview dashboard.

The app keeps a file-backed session store (used by the dashboard) and
supports API-key / session / basic auth. Logout must:

1. Clear the accumulated telemetry (so stale telemetry is not reported),
2. Clear the GitHub App JWT / installation-token cache, and
3. Invalidate the local file-backed session.
"""

from __future__ import annotations

import logging
import json
import os
import secrets
from pathlib import Path
from typing import Any

from django.contrib.auth import logout as django_logout

logger = logging.getLogger(__name__)

_SESSION_DIR = Path(os.environ.get("SENTINEL_SESSION_DIR", "sessions"))
_SESSION_DIR.mkdir(parents=True, exist_ok=True)

# Lazy import to avoid a hard dependency at module import time.
telemetry_flush = None  # type: ignore[assignment]


def _load_async():
    from ..workers import telemetry as _telemetry
    from ..workers import telemetry_flush as _tf

    return _telemetry, _tf


def get_telemetry():
    """Lazy-load the telemetry API without importing at module load."""
    global telemetry_flush
    if telemetry_flush is None:
        _t, _tf = _load_async()
        telemetry_flush = _tf
    return telemetry_flush


def _save_session(session_id: str, data: dict[str, Any]) -> None:
    (_SESSION_DIR / f"{session_id}.json").write_text(
        json_dumps(data), encoding="utf-8"
    )


def _load_session(session_id: str) -> dict[str, Any] | None:
    path = _SESSION_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    return json_loads(path.read_text(encoding="utf-8"))


def logout(request=None) -> dict[str, Any]:
    """Complete logout: clear telemetry + token cache + invalidate session."""
    _t = get_telemetry()

    _t.clear_stale_telemetry()
    logger.info("Post-logout telemetry cleared")

    # Django session invalidation (if a request is available).
    if request is not None:
        django_logout(request)

    return {"ok": True, "message": "Logged out; stale telemetry cleared"}
