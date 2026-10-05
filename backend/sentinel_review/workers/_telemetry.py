"""Expose the telemetry accumulation store to the rest of the app.

Decides (on import) whether the unmount-flush is enabled. This import
happens late enough in ``wsgi.py``/``asgi.py`` that the accumulator is
not yet in use, so the atexit hook is registered before any telemetry
is recorded.
"""

from __future__ import annotations

from . import telemetry

# Register the unmount (process-exit) flush. Safe to call everywhere.
# ``telemetry.enable_unmount_flush()`` is idempotent and becomes a no-op
# once the process has already shut down.
telemetry.enable_unmount_flush()
