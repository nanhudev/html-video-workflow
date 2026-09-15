"""Runtime: job model, cache, events and stage wiring (mock providers only)."""
from __future__ import annotations

import json

from html_video_workflow.config.settings import Settings
from html_video_workflow.pipeline.router import FALLBACKS
from html_video_workflow.project.ir import VideoProject
from html_video_workflow.project.migrate import migrate
from html_video_workflow.providers.llm.mock_llm import build_mock_project
from html_video_workflow.runtime import cache, events
from html_video_workflow.runtime.engine import VideoRuntime
from html_video_workflow.runtime.models import Job, JobStatus, Step, StepStatus


def _mock_project() -> VideoProject:
    return VideoProject.model_validate(migrate(build_mock_project("测试主题", scenes=2)))


def test_job_lifecycle_fields() -> None:
    job = Job(project_id="prj_test")
    assert job.status == JobStatus.QUEUED
    assert job.progress == 0.0
    task = job.add_task("voice", "voice")
    step = Step(id="s1", name="synth")
    task.steps.append(step)
    step.start("mock_tts")
    assert step.status == StepStatus.RUNNING
    step.finish()
    assert step.status == StepStatus.COMPLETED
    assert job.progress == 1.0


def test_step_failure_records_type() -> None:
    step = Step(id="s2", name="synth")
    step.fail("boom", "ProviderTimeout")
    assert step.status == StepStatus.FAILED
    assert step.error_type == "ProviderTimeout"


def test_cache_round_trip(tmp_path) -> None:
    source = tmp_path / "art.txt"
    source.write_text("hello", encoding="utf-8")
    stored = cache.put("mock_tts", {"text": "hello"}, {"v": 1}, source)
    assert stored.exists()
    hit = cache.get("mock_tts", {"text": "hello"}, {"v": 1})
    assert hit is not None and hit.read_text(encoding="utf-8") == "hello"


def test_cache_key_includes_provider_and_config(tmp_path) -> None:
    source = tmp_path / "art.txt"
    source.write_text("hello", encoding="utf-8")
    cache.put("mock_tts", {"text": "hello"}, {"v": 1}, source)
    assert cache.get("other_tts", {"text": "hello"}, {"v": 1}) is None
    assert cache.get("mock_tts", {"text": "hello"}, {"v": 2}) is None


def test_cache_evicts_missing_files(tmp_path) -> None:
    source = tmp_path / "art.txt"
    source.write_text("hello", encoding="utf-8")
    stored = cache.put("mock_tts", {"text": "x"}, None, source)
    stored.unlink()
    assert cache.get("mock_tts", {"text": "x"}, None) is None


def test_events_are_append_only_and_readable() -> None:
    events.emit("job_test", "plan", "started", preset="fast")
    events.emit("job_test", "plan", "completed", preset="fast")
    rows = events.read_events("job_test")
    assert len(rows) == 2
    assert rows[0]["stage"] == "plan"
    assert rows[0]["event"] == "started"
    assert rows[1]["event"] == "completed"


def test_fallback_chains_end_with_a_mock() -> None:
    for stage, chain in FALLBACKS.items():
        assert chain, f"{stage} has no fallback"
        assert any("mock" in item for item in chain) or stage == "subtitle"


def test_runtime_creates_job_without_frontend() -> None:
    runtime = VideoRuntime(Settings())
    project = _mock_project()
    job = runtime.create_job(project, preset="fast")
    assert job.id.startswith("job_")
    assert job.plan.preset == "fast"
    assert runtime.get_job(job.id) is job


def test_runtime_persists_job_manifest() -> None:
    runtime = VideoRuntime(Settings())
    project = _mock_project()
    assert project.id is None, "fixture should start unsaved to prove id assignment"
    job = runtime.create_job(project, preset="fast")
    path = runtime.persist(job)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    # The manifest must be self-consistent: never the literal string "unsaved".
    assert data["project_id"] == job.project_id
    assert data["project_id"].startswith("prj_"), "unsaved projects get a real id at job creation"
    assert data["plan"]["preset"] == "fast"
    assert "plan" in data


def test_cancel_marks_job_cancelled() -> None:
    runtime = VideoRuntime(Settings())
    job = runtime.create_job(_mock_project(), preset="fast")
    assert runtime.cancel(job.id) is True
    assert runtime.get_job(job.id).status == JobStatus.CANCELLED


def test_cancel_unknown_job_returns_false() -> None:
    runtime = VideoRuntime(Settings())
    assert runtime.cancel("nope") is False


def test_saved_project_and_job_agree_on_id() -> None:
    """A project saved to disk and the job that renders it must share one id.

    Regression: `save_project()` used to return the new id without stamping it
    back onto the caller's object, so a CLI that saved an id-less project and
    then handed the same object to the runtime produced two ids. The manifest
    landed in one directory and the run's frames/audio/segments in another,
    which silently orphaned every artifact.
    """
    from html_video_workflow.project.store import save_project

    runtime = VideoRuntime(Settings())
    project = _mock_project()
    saved_id, path = save_project(project)

    assert project.id == saved_id, "save_project must stamp the id onto the object"
    assert path.parent.name == saved_id

    job = runtime.create_job(project, preset="fast")
    assert job.project_id == saved_id

    runtime.persist(job)
    from html_video_workflow.pipeline.stages import job_work_dir

    assert runtime.job_dir(job).parent.name == saved_id
    assert job_work_dir(job).parent.name == saved_id


def test_saved_project_and_job_agree_on_id() -> None:
    """A project saved to disk and the job that renders it must share one id.

    Regression: `save_project()` used to return the new id without stamping it
    back onto the caller's object, so a CLI that saved an id-less project and
    then handed the same object to the runtime produced two ids. The manifest
    landed in one directory and the run's frames/audio/segments in another,
    which silently orphaned every artifact.
    """
    from html_video_workflow.project.store import save_project

    runtime = VideoRuntime(Settings())
    project = _mock_project()
    saved_id, path = save_project(project)

    assert project.id == saved_id, "save_project must stamp the id onto the object"
    assert path.parent.name == saved_id

    job = runtime.create_job(project, preset="fast")
    assert job.project_id == saved_id

    runtime.persist(job)
    from html_video_workflow.pipeline.stages import job_work_dir

    assert runtime.job_dir(job).parent.name == saved_id
    assert job_work_dir(job).parent.name == saved_id
