"""Workers package — lazy re-exports for backward compatibility."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import ReviewContext
    from .pipeline_stages import PipelineError


def __getattr__(name: str) -> object:
    if name == "ReviewContext":
        from .context import ReviewContext
        return ReviewContext
    if name == "PipelineError":
        from .pipeline_stages import PipelineError
        return PipelineError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["PipelineError", "ReviewContext"]
