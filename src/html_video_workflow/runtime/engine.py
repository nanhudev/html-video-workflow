"""Workflow engine — job lifecycle, persistence and stage orchestration."""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ..config.paths import projects_dir
from ..config.settings import Settings, load_settings
from ..core.errors import VideoErrorCode, VideoWorkflowError
from ..core.request import CreateVideoRequest, VideoResult
from ..hardware.profile import HardwareProfile, probe_hardware
from ..pipeline import stages
from ..planning.pipeline_planner import PipelinePlanner
from ..planning.storyboard import StoryboardPlanner
from ..project.ir import VideoProject
from ..project.store import load_project, new_project_id, save_project, write_runtime_json
from ..sources import resolve_source
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

    def job_result(self, job_id: str) -> VideoResult | None:
        """Rebuild a VideoResult from a finished (or running) job.

        Needed because ``POST /v1/videos?wait=false`` returns only an id; the
        caller polls back and must get the *same* shape it would have received
        had it waited.
        """
        job = self.get_job(job_id)
        if job is None:
            return None
        result = VideoResult(
            job_id=job.id,
            project_id=job.project_id,
            providers={"llm": job.plan.llm or "", "tts": job.plan.tts or "",
                       "renderer": job.plan.renderer or "",
                       "subtitle": job.plan.subtitle or ""},
            fallbacks=[dict(item) for item in job.fallbacks],
            qc=job.quality,
            template=job.plan.template,
            style=job.plan.style,
            title=job.plan.title or None,
            scenes=job.plan.scenes,
            duration_sec=job.plan.duration_sec,
            narration_source=job.plan.narration_source,
            writing_preset=job.plan.writing_preset,
            reasons=list(job.plan.plan_reasons),
            warnings=list(job.plan.warnings),
        )
        video = job.outputs.get("video")
        if job.status is JobStatus.COMPLETED and video and Path(video).exists():
            result.ok = True
            result.video_path = video
            result.duration_sec = _probe_duration(Path(video))
            result.width, result.height = _probe_size(Path(video)) or (None, None)
        elif job.status is JobStatus.FAILED:
            result.ok = False
            result.error_code = VideoErrorCode.INTERNAL.value
            result.error = job.errors[-1]["message"] if job.errors else "job failed"
        result.status = job.status.value  # type: ignore[attr-defined]
        result.progress = round(job.progress, 3)  # type: ignore[attr-defined]
        result.elapsed_sec = _elapsed_seconds(job)
        return result

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

    # ------------------------------------------------------------- one-click
    def create_video(self, request: CreateVideoRequest) -> VideoResult:
        """One request in, one MP4 out. This is the only product entry point.

        The CLI, the REST API, the Python SDK, MCP and the Studio all land here.
        Anything one of them needs that the others do not is a bug in this
        method, not a feature of that entry point.
        """
        started = time.time()
        try:
            documents = resolve_source(request.source) if request.source else []
            planner = PipelinePlanner()
            plan = planner.plan(request, documents)
            script = planner.build_script(plan, request, documents)
            assert plan.template is not None and plan.style is not None
            project = StoryboardPlanner().build(
                script,
                manifest=plan.template,
                style=plan.style,
                output=plan.output,  # type: ignore[arg-type]
                request=request,
                documents=documents,
                video_type=plan.video_type,
            )
        except VideoWorkflowError as exc:
            return VideoResult.failure(exc.code.value, exc.message, **exc.detail)
        except Exception as exc:  # noqa: BLE001 - planning must not raise raw
            log.exception("planning failed")
            return VideoResult.failure(VideoErrorCode.PLANNING_FAILED.value,
                                       f"{type(exc).__name__}: {exc}")

        project_id, project_path = save_project(project)
        plan.warnings.extend(getattr(script, "warnings", []) or [])
        result = VideoResult(
            project_id=project_id,
            template=plan.template_id,
            style=plan.style_id,
            title=project.project.title,
            scenes=len(script.beats),
            duration_sec=round(script.total_duration, 2),
            providers={"llm": plan.llm or "", "tts": plan.tts or "",
                       "renderer": plan.renderer or "",
                       "subtitle": plan.subtitle or ""},
            narration_source=script.generated_by,
            writing_preset=script.writing_preset,
            reasons=plan.reasons,
            warnings=list(plan.warnings),
            artifacts={"project": str(project_path)},
        )

        if request.dry_run:
            # Explicitly not a video run. Saying so is what separates this from
            # a silent failure: ok=True with no path is only honest when the
            # caller asked for no video.
            result.ok = True
            result.warnings.append("dry_run requested: planned only, no video produced")
            result.elapsed_sec = round(time.time() - started, 2)
            return result

        overrides = request.overrides()
        if plan.renderer:
            overrides["renderer"] = plan.renderer
        job = self.create_job(project, preset=request.preset, overrides=overrides)
        # Record the product-level outcome on the job before it runs, so the
        # polled result is the same object a synchronous caller received.
        job.plan.template = plan.template_id
        job.plan.style = plan.style_id
        job.plan.scenes = len(script.beats)
        job.plan.title = project.project.title
        job.plan.duration_sec = result.duration_sec
        job.plan.narration_source = script.generated_by
        job.plan.writing_preset = script.writing_preset
        job.plan.plan_reasons = list(plan.reasons)
        job.plan.warnings = list(plan.warnings)
        result.job_id = job.id

        if not request.wait:
            self.run_job(job, project, background=True)
            result.ok = True
            result.warnings.append(
                f"job {job.id} started; poll GET /v1/videos/{job.id} for the result")
            result.elapsed_sec = round(time.time() - started, 2)
            return result

        try:
            self.run_job(job, project)
        except VideoWorkflowError as exc:
            return self._failed(job, result, exc.code.value, exc.message, started)
        except Exception as exc:  # noqa: BLE001 - a raw traceback is not a product
            log.exception("job %s failed", job.id)
            return self._failed(job, result, VideoErrorCode.INTERNAL.value,
                                f"{type(exc).__name__}: {exc}", started)

        result = self._completed(job, result, project, started, request.strict)
        if request.out_dir and result.video_path:
            # "Put it where I asked" is part of one-click. The canonical copy
            # stays in the project directory; this is a delivery convenience.
            destination = Path(request.out_dir)
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / Path(result.video_path).name
            shutil.copy2(result.video_path, target)
            result.video_path = str(target)
            result.artifacts["delivered"] = str(target)
        return result

    def _completed(self, job: Job, result: VideoResult, project: VideoProject,
                   started: float, strict: bool) -> VideoResult:
        result.job_id = job.id
        result.providers = {
            "llm": job.plan.llm or "", "tts": job.plan.tts or "",
            "renderer": job.plan.renderer or "", "subtitle": job.plan.subtitle or "",
        }
        result.fallbacks = [dict(item) for item in job.fallbacks]
        result.qc = job.quality
        result.elapsed_sec = round(time.time() - started, 2)

        video = job.outputs.get("video")
        # "Completed" is a job state, not a promise about a file. The only thing
        # that makes ok=True is a file on disk with bytes in it.
        if not video:
            result.ok = False
            result.error_code = VideoErrorCode.COMPOSE_FAILED.value
            result.error = job.errors[-1]["message"] if job.errors else "no video produced"
            return result
        path = Path(video)
        if not path.exists() or path.stat().st_size == 0:
            result.ok = False
            result.error_code = VideoErrorCode.COMPOSE_FAILED.value
            result.error = f"video file missing or empty: {video}"
            return result

        result.video_path = str(path)
        result.duration_sec = _probe_duration(path) or project.estimated_duration()
        result.width = project.output.width
        result.height = project.output.height
        result.ok = True

        if strict and job.quality and not job.quality.get("passed"):
            result.ok = False
            result.error_code = VideoErrorCode.QUALITY_FAILED.value
            result.error = f"quality gate failed: {job.quality.get('failed')}"
        return result

    def _failed(self, job: Job, result: VideoResult, code: str, message: str,
                started: float) -> VideoResult:
        result.job_id = job.id
        result.ok = False
        result.error_code = code
        result.error = message
        result.fallbacks = [dict(item) for item in job.fallbacks]
        result.qc = job.quality
        result.elapsed_sec = round(time.time() - started, 2)
        return result

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


def _elapsed_seconds(job: Job) -> float | None:
    """Wall-clock duration of a finished job, from its own timestamps.

    Returns ``None`` rather than ``0`` when the job never started: "took no
    time" and "we do not know" are different statements, and a UI that prints
    0.0 seconds for a missing measurement is lying by formatting.
    """
    from datetime import datetime

    if not job.started_at or not job.ended_at:
        return None
    try:
        started = datetime.fromisoformat(job.started_at)
        ended = datetime.fromisoformat(job.ended_at)
    except ValueError:
        return None
    return round((ended - started).total_seconds(), 2)


def _probe_size(path: Path) -> tuple[int, int] | None:
    try:
        from ..ffmpeg.service import get_service

        service = get_service()
        if not service.available():
            return None
        info = service.probe(path)
    except Exception:  # noqa: BLE001
        return None
    for stream in info.get("streams") or []:
        if stream.get("codec_type") == "video":
            width, height = stream.get("width"), stream.get("height")
            if width and height:
                return int(width), int(height)
    return None


def _probe_duration(path: Path) -> float | None:
    """Ask ffprobe, not the project file.

    The IR's estimate is a plan; ffprobe on the artefact is a measurement. When
    they disagree the measurement is right, and reporting the plan as fact is
    exactly the kind of convenient lie this project refuses to tell.
    """
    try:
        from ..ffmpeg.service import get_service

        service = get_service()
        if not service.available():
            return None
        return float(service.duration(path))
    except Exception:  # noqa: BLE001 - a probe failure must not fail the result
        log.debug("duration probe failed for %s", path)
        return None


_runtime: VideoRuntime | None = None
_runtime_lock = threading.RLock()


def get_runtime(settings: Settings | None = None) -> VideoRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = VideoRuntime(settings)
        return _runtime
