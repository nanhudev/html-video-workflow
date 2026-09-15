"""The product contract: one request in, one video out.

Every entry point — GUI, CLI, Python API, REST, MCP, Agent Skill — builds the
*same* :class:`CreateVideoRequest` and hands it to
``VideoRuntime.create_video``. No entry point is allowed to grow its own
pipeline logic; if an entry point can do something the others cannot, that is
a bug in this package, not a feature of that entry point.
"""
from __future__ import annotations

from .errors import VideoErrorCode, VideoWorkflowError
from .request import (
    PLATFORM_PRESETS,
    CreateVideoRequest,
    PlatformPreset,
    SourceInput,
    VideoResult,
    resolve_output,
)

__all__ = [
    "PLATFORM_PRESETS",
    "CreateVideoRequest",
    "PlatformPreset",
    "SourceInput",
    "VideoErrorCode",
    "VideoResult",
    "VideoWorkflowError",
    "resolve_output",
]
