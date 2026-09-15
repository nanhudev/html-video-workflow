"""Versioned public API — ``/v1``.

This is a transport. Every handler builds a ``CreateVideoRequest`` and calls
``VideoRuntime.create_video``; there is no pipeline logic here, and adding any
would put the REST API out of step with the CLI and the SDK.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ...core.errors import VideoErrorCode
from ...core.request import (
    PLATFORM_PRESETS,
    CreateVideoRequest,
    VideoResult,
)
from ...planning.topic_planner import TopicPlanner
from ...runtime.engine import get_runtime
from ...templates.registry import get_registry

router = APIRouter(prefix="/v1", tags=["v1"])


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


def _raise(code: VideoErrorCode, message: str, detail: dict | None = None) -> None:
    from ...core.errors import HTTP_STATUS

    raise HTTPException(status_code=HTTP_STATUS.get(code.value, 500),
                        detail=ErrorBody(code=code.value, message=message,
                                         detail=detail or {}).model_dump())


# --------------------------------------------------------------------- videos
@router.post("/videos", response_model=VideoResult, status_code=200)
def create_video(request: CreateVideoRequest,
                 wait: bool | None = Query(
                     default=None,
                     description="Wait for the MP4. Defaults to the body's `wait`."),
                 ) -> VideoResult:
    """One call, one video.

    ``wait=true`` (default) blocks until the MP4 exists and returns it.
    ``wait=false`` returns immediately with ``job_id`` and ``status``; poll
    ``GET /v1/videos/{job_id}``.
    """
    runtime = get_runtime()
    effective = request.model_copy(update={"wait": wait if wait is not None
                                           else request.wait})
    result = runtime.create_video(effective)
    if not result.ok and result.error_code in {
            VideoErrorCode.INVALID_REQUEST.value,
            VideoErrorCode.NO_SOURCE.value,
            VideoErrorCode.SOURCE_UNREADABLE.value,
            VideoErrorCode.NO_TEMPLATE.value,
    }:
        _raise(VideoErrorCode(result.error_code), result.error or "request failed")
    return result


@router.get("/videos", response_model=list[dict[str, Any]])
def list_videos() -> list[dict[str, Any]]:
    return get_runtime().list_jobs()


@router.get("/videos/{job_id}", response_model=VideoResult)
def get_video(job_id: str) -> VideoResult:
    result = get_runtime().job_result(job_id)
    if result is None:
        _raise(VideoErrorCode.JOB_NOT_FOUND, f"unknown job: {job_id}")
    return result


@router.get("/videos/{job_id}/events")
def get_video_events(job_id: str) -> list[dict[str, Any]]:
    # An empty list is the answer for a job that exists and has not started.
    # For one that was never issued, saying "no events" would be a lie.
    if get_runtime().job_result(job_id) is None:
        _raise(VideoErrorCode.JOB_NOT_FOUND, f"unknown job: {job_id}")
    return get_runtime().job_events(job_id)


@router.delete("/videos/{job_id}")
def cancel_video(job_id: str) -> dict[str, Any]:
    return {"cancelled": get_runtime().cancel(job_id), "job_id": job_id}


# ------------------------------------------------------------------ catalogue
@router.get("/templates")
def list_templates() -> list[dict[str, Any]]:
    """Every template manifest, verbatim. Readable by an agent."""
    return [manifest.model_dump(mode="json") for manifest in get_registry().templates()]


@router.get("/templates/{template_id}")
def get_template(template_id: str) -> dict[str, Any]:
    registry = get_registry()
    manifest = registry.find(template_id)
    if manifest is None:
        _raise(VideoErrorCode.NO_TEMPLATE, f"unknown template: {template_id}")
    assert manifest is not None
    return manifest.model_dump(mode="json")


@router.get("/styles")
def list_styles() -> list[dict[str, Any]]:
    return [style.model_dump(mode="json") for style in get_registry().styles()]


@router.get("/presets")
def list_presets() -> list[dict[str, Any]]:
    """Writing presets: who is talking, to whom, and under which rules."""
    return [preset.model_dump(mode="json") for preset in get_registry().presets()]


@router.get("/presets/{preset_id}")
def get_preset(preset_id: str) -> dict[str, Any]:
    preset = get_registry().find_preset(preset_id)
    if preset is None:
        _raise(VideoErrorCode.NO_TEMPLATE, f"unknown writing preset: {preset_id}")
    assert preset is not None
    return preset.model_dump(mode="json")


@router.get("/platforms")
def list_platforms() -> list[dict[str, Any]]:
    return [preset.model_dump(mode="json") for preset in PLATFORM_PRESETS.values()]


@router.get("/topics/suggest")
def suggest_topics(prompt: str = Query(default=""), count: int = Query(default=5,
                                                                      ge=1, le=12),
                   ) -> list[dict[str, Any]]:
    """Candidate angles for a half-formed idea. Offline and deterministic."""
    if not prompt.strip():
        _raise(VideoErrorCode.INVALID_REQUEST, "prompt is required")
    suggestions = TopicPlanner().suggest(CreateVideoRequest(prompt=prompt),
                                         count=count)
    return [item.model_dump(mode="json") for item in suggestions]
