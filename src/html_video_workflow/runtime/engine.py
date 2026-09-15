"""Workflow engine — job lifecycle, persistence and stage orchestration."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ..config.paths import projects_dir
from ..config.settings import Settings, load_settings
from ..hardware.profile import HardwareProfile, probe_hardware
from ..pipeline import stages
from ..project.ir import VideoProject
from ..project.store import load_project, new_project_id, write_runtime_json
from ..utils.logging import attach_job_log, detach_job_log, get_logger
from .events import emit, read_events
from .models import Job, JobStatus

log = get_logger("runtime.engine")


class RuntimeError_(RuntimeError):
    pass


class VideoRuntime:
    """Runs a project through the pipeline. Works with no frontend attached."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self._jobs: dict[str, Job] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.RLock()

    # ------------------------------------------------------------- hardware
    def hardware(self, refresh: bool = False) -> HardwareProfile:
        return probe_hardware(use_cache=not refresh)

    # ------------------------------------------------------------ job index
    def job_dir(self, job: Job) -> Path:
        path = projects_dir() / job.project_id / "runtime"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def persist(self, job: Job) -> Path:
        # Keep the manifest truthful even if the caller persisted before
        # planning ran: the preset is known at creation time.
        if job.plan.preset != job.preset:
            job.plan.preset = job.preset
        path = self.job_dir(job) / "job.json"
        path.write_text(json.dumps(job.model_dump(mode="json"), ensure_ascii=False,
                                   indent=2, default=str), encoding="utf-8")
        write_runtime_json(job.project_id, "artifacts.json",
                           [a.model_dump(mode="json")
                            for step in job.all_steps() for a in step.artifacts])
        write_runtime_json(job.project_id, "providers.json", {
            "selected": {
                "llm": job.plan.llm,
                "tts": job.plan.tts,
                "renderer": job.plan.renderer,
                "subtitle": job.plan.subtitle,
            },
            "preset": job.plan.preset,
        })
        return path

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": job.id,
                    "project_id": job.project_id,
                    "status": job.status.value,
                    "progress": round(job.progress, 3),
                    "preset": job.plan.preset,
                    "created_at": job.created_at,
                    "updated_at": job.updated_at,
                    "outputs": job.outputs,
                }
                for job in self._jobs.values()
            ]

    def job_events(self, job_id: str) -> list[dict[str, Any]]:
        return read_events(job_id)

    # ---------------------------------------------------------------- run
    def create_job(self, project: VideoProject | str, preset: str | None = None,
                   overrides: dict[str, str] | None = None) -> Job:
        if isinstance(project, str):
            project = load_project(project)
        # An unsaved project gets an id now, so the manifest, the job directory
        # and the artifacts all agree on one identity. "unsaved" is only a
        # fallback for a project that could not be named at all.
        if not project.id:
            project = project.model_copy(update={"id": new_project_id()})
        job = Job(project_id=project.id or "unsaved",
                  preset=preset or self.settings.routing.preset)
        # The plan is the record of what we decided; it must carry the preset
        # even before planning runs, or a `--preset fast` request looks like
        # `auto` to anyone reading the manifest.
        job.plan.preset = job.preset
        if overrides:
            self.settings.routing.locked_providers.update(overrides)
        with self._lock:
            self._jobs[job.id] = job
        emit(job.id, "job", "created", project=project.project.title, preset=job.preset)
        return job

    def run_job(
        self,
        job: Job,
        project: VideoProject,
        *,
        background: bool = False,
        on_event: Callable[..., Any] | None = None,
    ) -> Job:
        if background:
            thread = threading.Thread(
                target=self._execute, args=(job, project, on_event), daemon=True
            )
            self._threads[job.id] = thread
            thread.start()
            return job
        return self._execute(job, project, on_event)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            self._cancelled.add(job_id)
            job.status = JobStatus.CANCELLED
            job.touch()
            self.persist(job)
        emit(job_id, "job", "cancelled")
        return True

    # ------------------------------------------------------------ internals
    def _execute(self, job: Job, project: VideoProject,
                 on_event: Callable[..., Any] | None = None) -> Job:
        handler = attach_job_log(job.id)
        try:
            job.status = JobStatus.PLANNING
            job.started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            emit(job.id, "job", "started")

            ctx = stages.StageContext(
                job=job,
                project=project,
                settings=self.settings,
                hardware=self.hardware(),
                work_path=stages.job_work_dir(job),
                on_event=on_event,
            )
            job.status = JobStatus.RUNNING
            stages.stage_plan(ctx)
            self.persist(job)

            audios = stages.stage_voice(ctx)
            self.persist(job)
            images = stages.stage_render(ctx)
            self.persist(job)
            subtitles = stages.stage_caption(ctx, audios)
            video = stages.stage_compose(ctx, images, audios, subtitles)
            self.persist(job)
            stages.stage_quality(ctx, video)
            self.persist(job)

            job.status = JobStatus.COMPLETED
            job.ended_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            job.touch()
            emit(job.id, "job", "completed", video=str(video))
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.ended_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            job.errors.append({"type": type(exc).__name__, "message": str(exc)[:500]})
            job.touch()
            emit(job.id, "job", "failed", error=str(exc)[:500])
            log.exception("job %s failed", job.id)
            self.persist(job)
            raise
        finally:
            self.persist(job)
            detach_job_log(handler)
        return job


_runtime: VideoRuntime | None = None
_runtime_lock = threading.RLock()


def get_runtime(settings: Settings | None = None) -> VideoRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = VideoRuntime(settings)
        return _runtime
