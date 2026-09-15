"""Failure vocabulary shared by every entry point.

Errors carry a stable ``code`` so the CLI can pick an exit status, the REST API
a status code, and the MCP server a structured payload — all from one place,
without any entry point re-deriving meaning from a message string.
"""
from __future__ import annotations

from enum import Enum


class VideoErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    NO_SOURCE = "no_source"
    SOURCE_UNREADABLE = "source_unreadable"
    NO_TEMPLATE = "no_template"
    JOB_NOT_FOUND = "job_not_found"
    NO_PROVIDER = "no_provider"
    PLANNING_FAILED = "planning_failed"
    RENDER_FAILED = "render_failed"
    TTS_FAILED = "tts_failed"
    COMPOSE_FAILED = "compose_failed"
    QUALITY_FAILED = "quality_failed"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


#: HTTP status each code maps to. Kept here so the REST layer stays a transport.
HTTP_STATUS: dict[str, int] = {
    VideoErrorCode.INVALID_REQUEST.value: 422,
    VideoErrorCode.NO_SOURCE.value: 400,
    VideoErrorCode.SOURCE_UNREADABLE.value: 400,
    # A named template that does not exist is a missing *resource*, not a
    # malformed request — 422 is reserved for input the server cannot parse or
    # validate. Callers distinguish "you asked badly" from "that isn't there".
    VideoErrorCode.NO_TEMPLATE.value: 404,
    # Same rule as NO_TEMPLATE: a job id that was never issued is a missing
    # resource. Returning 422 here would tell the caller their request was
    # malformed when in fact they simply asked for something that isn't there.
    VideoErrorCode.JOB_NOT_FOUND.value: 404,
    VideoErrorCode.NO_PROVIDER.value: 503,
    VideoErrorCode.PLANNING_FAILED.value: 500,
    VideoErrorCode.RENDER_FAILED.value: 500,
    VideoErrorCode.TTS_FAILED.value: 500,
    VideoErrorCode.COMPOSE_FAILED.value: 500,
    VideoErrorCode.QUALITY_FAILED.value: 500,
    VideoErrorCode.CANCELLED.value: 409,
    VideoErrorCode.INTERNAL.value: 500,
}


class VideoWorkflowError(RuntimeError):
    """A failed one-click run. Always carries a machine-readable code."""

    def __init__(self, code: VideoErrorCode | str, message: str,
                 detail: dict | None = None) -> None:
        super().__init__(message)
        self.code = VideoErrorCode(code) if isinstance(code, str) else code
        self.message = message
        self.detail = detail or {}

    @property
    def http_status(self) -> int:
        return HTTP_STATUS.get(self.code.value, 500)

    def to_dict(self) -> dict:
        return {
            "code": self.code.value,
            "message": self.message,
            "detail": self.detail,
        }
