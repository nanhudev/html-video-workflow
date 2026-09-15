"""End-to-end smoke test: project → voice → render → compose → QC.

Uses mock providers plus real ffmpeg when available, so it proves the *runtime*
works without downloading a single model.
"""
from __future__ import annotations

import shutil

import pytest

from html_video_workflow.config.settings import Settings
from html_video_workflow.ffmpeg.service import FFmpegService
from html_video_workflow.pipeline.stages import StageContext, job_work_dir, stage_compose, stage_quality, stage_render, stage_voice
from html_video_workflow.project.ir import VideoProject
from html_video_workflow.project.migrate import migrate
from html_video_workflow.providers.llm.mock_llm import build_mock_project
from html_video_workflow.quality.engine import QualityEngine
from html_video_workflow.runtime.engine import VideoRuntime
from html_video_workflow.runtime.models import Job

ffmpeg_available = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
requires_ffmpeg = pytest.mark.skipif(not ffmpeg_available, reason="ffmpeg/ffprobe not installed")


def _project() -> VideoProject:
    return VideoProject.model_validate(migrate(build_mock_project("本地优先视频运行时", scenes=3)))


def _context(project: VideoProject, preset: str = "fast") -> StageContext:
    from html_video_workflow.pipeline.router import plan_pipeline

    job = Job(project_id=project.id or "prj_smoke", preset=preset)
    plan = plan_pipeline(language=project.project.language, preset=preset)
    job.plan.preset = plan["preset"]
    job.plan.llm = plan["selection"].get("llm")
    job.plan.tts = plan["selection"].get("tts")
    job.plan.renderer = plan["selection"].get("renderer")
    job.plan.subtitle = plan["selection"].get("subtitle")
    return StageContext(
        job=job,
        project=project,
        settings=Settings(),
        hardware=VideoRuntime(Settings()).hardware(),
        work_path=job_work_dir(job),
        quality=QualityEngine(),
    )


def test_mock_voice_stage_produces_audio() -> None:
    ctx = _context(_project())
    audios = stage_voice(ctx)
    assert audios
    for audio in audios:
        assert audio.exists(), f"missing audio {audio}"
        assert audio.stat().st_size > 44  # more than a WAV header


def test_mock_render_stage_produces_png() -> None:
    ctx = _context(_project())
    images = stage_render(ctx)
    assert images
    for image in images:
        assert image.exists()
        assert image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_stage_falls_back_when_browser_missing(monkeypatch) -> None:
    """If the browser disappears mid-run, the renderer must fall back, not crash.

    This is the *mid-run* case, not the planning case: the job was planned while
    Edge/Chrome existed, so `legacy_html` is already pinned in the plan. It then
    fails at execution time, and the stage must transparently degrade to
    `mock_renderer` while recording the substitution.
    """
    import html_video_workflow.hardware.profile as profile_module
    import html_video_workflow.providers.renderer.legacy_html as legacy_module
    from html_video_workflow.hardware.profile import ToolInfo

    ctx = _context(_project())
    # Pin the plan to the real renderer, as if the browser had been present.
    ctx.job.plan.renderer = "legacy_html"
    assert hasattr(legacy_module, "_resolve_browser"), "renderer must not import the probe directly"

    monkeypatch.setattr(
        profile_module,
        "resolve_browser",
        lambda: ToolInfo(name="none", path=None, available=False, version=None),
    )
    images = stage_render(ctx)
    assert images
    assert any(image.exists() for image in images)
    assert ctx.job.fallbacks, "fallback must be recorded in the job manifest"
    assert ctx.job.fallbacks[0]["stage"] == "render"
    assert ctx.job.fallbacks[0]["from"] == "legacy_html"
    assert ctx.job.fallbacks[0]["to"] == "mock_renderer"
    assert ctx.job.plan.renderer == "mock_renderer", "job must record the real renderer used"


@requires_ffmpeg
def test_smoke_video_composes_and_passes_quality() -> None:
    ctx = _context(_project())
    audios = stage_voice(ctx)
    images = stage_render(ctx)
    video = stage_compose(ctx, images, audios, None)
    assert video.exists()
    assert video.stat().st_size > 10_000

    report = stage_quality(ctx, video)
    assert report["passed"], f"quality failed: {report['failed']}"
    assert report["checks"]

    info = FFmpegService().probe(video)
    kinds = {stream["codec_type"] for stream in info["streams"]}
    assert "video" in kinds
    assert "audio" in kinds


@requires_ffmpeg
def test_quality_engine_detects_a_broken_file(tmp_path) -> None:
    bogus = tmp_path / "broken.mp4"
    bogus.write_bytes(b"not a video")
    report = QualityEngine().check_video(bogus)
    assert report["passed"] is False


@requires_ffmpeg
def test_gentle_push_in_does_not_rescale_the_still(tmp_path) -> None:
    """A gentle push-in must stay gentle for the whole scene.

    Regression: the zoompan filter was given `d=<segment frames>`. Because the
    image input is looped and `-t` already bounds the segment, zoompan emitted
    `<frames>` outputs per input frame while still re-evaluating
    `z='min(zoom+0.00035,1.04)'` every time, so the zoom raced past its cap and
    aggressively rescaled the still for the rest of the scene. On screen this
    looked like washed-out, blurry text in the middle of a shot.

    We measure it with PSNR between two mid-scene frames, which needs no image
    library and is a direct statement of intent: a 4% push-in should leave
    consecutive frames nearly identical (>40 dB), whereas the buggy overshoot
    replaced the image outright (~11 dB in practice).
    """
    import re
    import subprocess

    from html_video_workflow.ffmpeg.service import FFmpegService

    ffmpeg = FFmpegService()
    if not ffmpeg.available():
        pytest.skip("ffmpeg not available")

    # A high-frequency card, so any rescaling destroys visible detail.
    card = tmp_path / "card.png"
    ffmpeg._run([
        ffmpeg.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
        "testsrc2=size=1280x720:rate=1,format=rgb24,drawgrid=w=8:h=8:t=1:c=black@0.9",
        "-frames:v", "1", str(card),
    ])
    audio = tmp_path / "silence.wav"
    ffmpeg._run([
        ffmpeg.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
        "anullsrc=r=44100:cl=mono", "-t", "4", str(audio),
    ])

    segment = tmp_path / "segment.mp4"
    ffmpeg.image_with_audio(card, audio, segment, width=1280, height=720,
                            fps=30, duration=4.0)

    def frame_at(seconds: str):
        out = tmp_path / f"f{seconds}.png"
        ffmpeg._run([ffmpeg.ffmpeg, "-y", "-v", "error", "-ss", seconds,
                     "-i", str(segment), "-frames:v", "1", str(out)])
        return out

    # 0.6s and 3.6s sit outside the 0.25s/0.3s fades, so only the zoom differs.
    early, late = frame_at("0.6"), frame_at("3.6")
    result = subprocess.run(
        [ffmpeg.ffmpeg, "-hide_banner", "-i", str(early), "-i", str(late),
         "-lavfi", "psnr", "-f", "null", "-"],
        capture_output=True, text=True, errors="replace",
    )
    match = re.search(r"average:([0-9.]+|inf)", result.stderr)
    assert match, "could not measure PSNR: " + result.stderr[-400:]
    raw = match.group(1)
    psnr = 99.0 if raw == "inf" else float(raw)

    assert psnr > 35.0, (
        f"mid-scene frames differ far too much (PSNR {psnr:.1f} dB) — the zoom "
        "filter is probably rescaling the still instead of nudging it"
    )
