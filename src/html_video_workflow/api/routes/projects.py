"""Project + job endpoints, including the SSE progress stream."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...config.settings import load_settings
from ...project.ir import VideoProject
from ...project.migrate import detect_version, migrate
from ...project.store import (
    list_projects,
    load_project,
    load_project_file,
    read_runtime_json,
    save_project,
)
from ...providers.base import LLMRequest
from ...providers.llm.mock_llm import build_mock_project
from ...pipeline.router import plan_pipeline, provider_for
from ...runtime.engine import get_runtime
from ...runtime.events import read_events, stream_events
from ...utils.logging import get_logger

log = get_logger("api.projects")

router = APIRouter(tags=["projects"])


class CreateProjectRequest(BaseModel):
    prompt: str | None = None
    script: str | None = None
    project: dict[str, Any] | None = None
    language: str = "zh-CN"
    preset: str = "auto"
    video_type: str = "explainer"
    llm: str | None = None


class GenerateRequest(BaseModel):
    preset: str = "auto"
    overrides: dict[str, str] = Field(default_factory=dict)
    background: bool = True


@router.get("/projects")
def get_projects() -> list[dict[str, Any]]:
    return list_projects()


@router.post("/projects")
def create_project(payload: CreateProjectRequest) -> dict[str, Any]:
    if payload.project:
        data = migrate(payload.project)
        data.setdefault("project", {})
        data["project"]["language"] = data["project"].get("language") or payload.language
        project = VideoProject.model_validate(data)
    else:
        source = payload.prompt or payload.script or ""
        if not source.strip():
            raise HTTPException(status_code=400, detail="prompt, script or project required")
        plan = plan_pipeline(
            language=payload.language,
            preset=payload.preset,
            overrides={"llm": payload.llm} if payload.llm else None,
        )
        llm_id = plan["selection"].get("llm")
        data = None
        if llm_id and llm_id != "mock_llm":
            try:
                provider = provider_for("llm", llm_id)
                response = provider.complete(
                    LLMRequest(
                        prompt=f"Create a short video project about: {source}",
                        system="You are a careful video editor. Return JSON only.",
                        json_mode=True,
                    )
                )
                data = json.loads(_extract_json(response.text))
            except Exception as exc:  # noqa: BLE001 - degrade to mock planner
                log.warning("LLM planning failed (%s); using mock planner", exc)
        if not data:
            data = build_mock_project(source)
        data.setdefault("project", {})
        data["project"]["title"] = data["project"].get("title") or source[:40]
        data["project"]["language"] = payload.language
        data["project"]["video_type"] = payload.video_type
        project = VideoProject.model_validate(migrate(data))

    project_id, path = save_project(project)
    return {
        "id": project_id,
        "path": str(path),
        "scenes": project.scene_count,
        "project": project.model_dump(mode="json"),
    }


@router.get("/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    try:
        project = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return project.model_dump(mode="json")


@router.post("/validate")
def validate_project_payload(payload: dict[str, Any]) -> dict[str, Any]:
    from ...project.ir import validate_project as _validate

    migrated = migrate(payload)
    project, errors = _validate(migrated)
    return {
        "valid": project is not None,
        "schema_version": detect_version(payload),
        "errors": errors,
        "scenes": project.scene_count if project else 0,
    }


@router.post("/projects/{project_id}/generate")
def generate(project_id: str, payload: GenerateRequest,
             background_tasks: BackgroundTasks) -> dict[str, Any]:
    try:
        project = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    runtime = get_runtime()
    job = runtime.create_job(project, preset=payload.preset, overrides=payload.overrides)
    if payload.background:
        background_tasks.add_task(_run, runtime, job, project)
        return {"job_id": job.id, "status": job.status.value, "mode": "background"}
    _run(runtime, job, project)
    return _job_view(runtime, job.id)


def _run(runtime, job, project) -> None:
    try:
        runtime.run_job(job, project)
    except Exception as exc:  # noqa: BLE001 - job records its own failure
        log.error("job %s failed: %s", job.id, exc)


@router.get("/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return get_runtime().list_jobs()


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    view = _job_view(get_runtime(), job_id)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown job {job_id}")
    return view


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    if not get_runtime().cancel(job_id):
        raise HTTPException(status_code=404, detail=f"unknown job {job_id}")
    return {"job_id": job_id, "status": "cancelled"}


@router.get("/jobs/{job_id}/events")
def job_events(job_id: str) -> list[dict[str, Any]]:
    return read_events(job_id)


@router.get("/jobs/{job_id}/stream")
def job_stream(job_id: str) -> StreamingResponse:
    return StreamingResponse(
        stream_events(job_id), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/jobs/{job_id}/artifacts")
def job_artifacts(job_id: str) -> list[dict[str, Any]]:
    runtime = get_runtime()
    job = runtime.get_job(job_id)
    if job is None:
        project_id = job_id
    else:
        project_id = job.project_id
    stored = read_runtime_json(project_id, "artifacts.json")
    if stored is not None:
        return stored
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job {job_id}")
    return [a.model_dump(mode="json") for step in job.all_steps() for a in step.artifacts]


def _job_view(runtime, job_id: str) -> dict[str, Any] | None:
    job = runtime.get_job(job_id)
    if job is None:
        return None
    return {
        "id": job.id,
        "project_id": job.project_id,
        "status": job.status.value,
        "progress": round(job.progress, 3),
        "preset": job.plan.preset,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "plan": {
            "preset": job.plan.preset,
            "llm": job.plan.llm,
            "tts": job.plan.tts,
            "renderer": job.plan.renderer,
            "subtitle": job.plan.subtitle,
            "reasons": job.plan.reasons,
        },
        "tasks": [
            {
                "stage": task.stage,
                "name": task.name,
                "status": task.status.value,
                "progress": round(task.progress, 3),
                "steps": [step.model_dump(mode="json") for step in task.steps],
            }
            for task in job.tasks
        ],
        "outputs": job.outputs,
        "errors": job.errors,
        "fallbacks": job.fallbacks,
        "quality": job.quality,
    }


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()
