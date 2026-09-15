"""Pipeline stages.

Each stage is a pure-ish function that:
  1. emits events,
  2. writes artifacts into the job work directory,
  3. records artifacts on the Job so a later run can resume.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..audio.postprocess import AudioPostProcessor, AudioQualityChecker
from ..config.paths import outputs_dir, work_dir
from ..config.settings import RenderSettings, Settings
from ..ffmpeg.service import FFmpegService
from ..hardware.profile import HardwareProfile
from ..project.ir import VideoProject
from ..providers.base import (
    NarrationSpec,
    RenderSceneRequest,
    RendererProvider,
    TTSProvider,
    TTSRequest,
)
from ..quality.engine import QualityEngine
from ..runtime.cache import get as cache_get, put as cache_put
from ..runtime.events import emit
from ..runtime.models import Artifact, Job, new_step
from ..utils.audio import estimate_speech_seconds, wav_duration
from ..utils.hashing import hash_file
from ..utils.logging import get_logger
from .prosody import ProsodyPlanner, ProsodySettings
from .router import plan_pipeline, provider_for

log = get_logger("pipeline.stages")

STAGES = ("plan", "voice", "render", "caption", "compose", "quality")


@dataclass
class StageContext:
    job: Job
    project: VideoProject
    settings: Settings
    hardware: HardwareProfile
    work_path: Path
    ffmpeg: FFmpegService = field(default_factory=FFmpegService)
    quality: QualityEngine = field(default_factory=QualityEngine)
    on_event: Callable[..., dict] | None = None

    def event(self, stage: str, event: str, **payload: Any) -> None:
        emit(self.job.id, stage, event, **payload)
        if self.on_event:
            self.on_event(stage, event, **payload)

    def step(self, task_stage: str, name: str):
        task = self.job.find_task(task_stage)
        if task is None:
            task = self.job.add_task(task_stage, task_stage)
        step = new_step(name)
        task.steps.append(step)
        return step

    def artifact(self, step, name: str, path: Path, kind: str = "file",
                 **metadata: Any) -> Artifact:
        artifact = Artifact(
            name=name,
            path=str(path),
            kind=kind,
            sha256=hash_file(path) if Path(path).exists() else None,
            size_bytes=Path(path).stat().st_size if Path(path).exists() else None,
            metadata=metadata,
        )
        step.artifacts.append(artifact)
        return artifact


def job_work_dir(job: Job) -> Path:
    path = work_dir() / job.project_id / job.id
    for name in ("scenes", "audio", "segments", "captions"):
        (path / name).mkdir(parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------------- plan
def stage_plan(ctx: StageContext) -> dict[str, Any]:
    step = ctx.step("plan", "Select provider pipeline")
    step.start("pipeline_planner")
    ctx.event("plan", "started", preset=ctx.job.preset)
    plan = plan_pipeline(
        language=ctx.project.project.language,
        preset=ctx.job.preset,
        hardware=ctx.hardware,
        routing=ctx.settings.routing,
    )
    ctx.job.plan.preset = plan["preset"]
    ctx.job.plan.llm = plan["selection"].get("llm")
    ctx.job.plan.tts = plan["selection"].get("tts")
    ctx.job.plan.renderer = plan["selection"].get("renderer")
    ctx.job.plan.subtitle = plan["selection"].get("subtitle")
    ctx.job.plan.reasons = {
        stage: reasons.get("candidates", []) and
        next(
            (c["reason"] for c in reasons["candidates"] if c.get("chosen")),
            ["no provider available"],
        )
        for stage, reasons in plan["reasons"].items()
    }
    ctx.job.plan.candidates = [
        {"stage": stage, **item}
        for stage, reasons in plan["reasons"].items()
        for item in reasons["candidates"]
    ]
    step.metrics = {"preset": plan["preset"], "selection": plan["selection"]}
    step.finish()
    ctx.event("plan", "completed", preset=plan["preset"],
              selection=plan["selection"])
    return plan


# -------------------------------------------------------------------- voice
def stage_voice(ctx: StageContext) -> list[Path]:
    scenes = ctx.project.scenes
    if not scenes:
        return []
    selected = ctx.job.plan.tts
    step = ctx.step("voice", f"Narration ({selected or 'auto'})")
    step.start(selected)
    ctx.event("voice", "started", provider=selected, scenes=len(scenes))

    planner = ProsodyPlanner(
        ProsodySettings(pause_scale=ctx.settings.audio.pause_scale)
    )
    checker = AudioQualityChecker(ctx.ffmpeg)
    processor = AudioPostProcessor(ctx.ffmpeg)
    render = RenderSettings(**ctx.settings.render.model_dump())

    audios: list[Path] = []
    for index, scene in enumerate(scenes, start=1):
        narration = scene.narration
        text = (narration.text or "").strip()
        target = ctx.work_path / "audio" / f"scene-{index:03d}.wav"
        if not text:
            step.notes.append(f"scene {index}: empty narration, skipped")
            audios.append(target)
            continue

        # Prosody first: the plan decides pauses and emphasis, and the provider
        # is asked to honour what it can. Doing this before synthesis is what
        # separates narration from a robot reading a paragraph.
        plan = planner.plan(
            text, language=narration.language, emotion=narration.emotion
        )
        step.metrics[f"prosody_scene_{index}"] = {
            "segments": len(plan.segments),
            "pause_ms": plan.total_pause_ms,
        }
        ctx.event(
            "voice", "prosody", scene=index, segments=len(plan.segments),
            pause_ms=plan.total_pause_ms,
        )

        spec = NarrationSpec(
            text=text,
            speaker=narration.speaker,
            language=narration.language,
            voice=narration.voice,
            emotion=narration.emotion,
            pace=narration.pace or _mean_pace(plan),
            pitch=narration.pitch,
            energy=narration.energy,
            pause_after_ms=narration.pause_after_ms,
            emphasis=list(narration.emphasis) or _plan_emphasis(plan),
            pronunciation=dict(narration.pronunciation),
            style=narration.style,
        )
        cached = cache_get(selected or "tts", spec.model_dump(), {"scene": index})
        if cached and cached.exists():
            target.write_bytes(cached.read_bytes())
            step.notes.append(f"scene {index}: tts cache hit")
        else:
            provider: TTSProvider = provider_for("tts", selected)  # type: ignore[assignment]
            try:
                response = provider.synthesize(
                    TTSRequest(narration=spec, output_path=str(target))
                )
            except Exception as exc:  # typed provider failure → fallback
                fallback = _next_fallback(ctx, "tts", selected)
                if not fallback:
                    step.fail(f"{type(exc).__name__}: {exc}", type(exc).__name__)
                    raise
                ctx.job.fallbacks.append(
                    {"stage": "tts", "from": selected or "", "to": fallback.id,
                     "reason": str(exc)[:200]}
                )
                provider = fallback  # type: ignore[assignment]
                response = provider.synthesize(
                    TTSRequest(narration=spec, output_path=str(target))
                )
                selected = fallback.id
                ctx.job.plan.tts = fallback.id
            cache_put(selected or "tts", spec.model_dump(), {"scene": index}, target)

        # Post-process and verify. A silent or clipped clip is a real failure
        # that a duration check alone would wave through.
        _polish_audio(ctx, processor, target, spec, step, index)

        report = checker.check(
            target,
            expected_duration_sec=estimate_speech_seconds(text),
            expected_sample_rate=spec_sample_rate(ctx),
        )
        # Audio QC rides on the step, like every other measurement, so it lands
        # in job.json without needing a second place to look.
        step.metrics.setdefault("audio_quality", {})[f"scene_{index}"] = (
            report.model_dump()
        )
        if not report.ok:
            step.notes.append(f"scene {index}: audio QC failed — {report.failures}")
            ctx.event("voice", "audio_failed", scene=index,
                      failures=report.failures)
        elif report.warnings:
            step.notes.append(f"scene {index}: audio warnings — {report.warnings}")

        duration = wav_duration(target)
        scene.narration.emphasis = spec.emphasis
        ctx.artifact(step, f"audio-{index:03d}", target, "audio",
                     duration=duration, scene=scene.id,
                     prosody_segments=len(plan.segments))
        audios.append(target)
        step.progress = index / len(scenes)
        ctx.event("voice", "scene", index=index, total=len(scenes), duration=duration)

    step.finish()
    ctx.event("voice", "completed", files=len(audios))
    return audios


def _mean_pace(plan) -> float | None:
    """Duration-weighted mean pace, so a long slow clause is not outvoted."""
    if not plan.segments:
        return None
    weights = [len(segment.text) or 1 for segment in plan.segments]
    total = sum(weights)
    if not total:
        return None
    return round(
        sum(segment.pace * weight for segment, weight in zip(plan.segments, weights))
        / total,
        4,
    )


def _plan_emphasis(plan) -> list[str]:
    seen: list[str] = []
    for segment in plan.segments:
        for cue in segment.emphasis:
            if cue not in seen:
                seen.append(cue)
    return seen


def _polish_audio(
    ctx: StageContext,
    processor,
    target: Path,
    spec: NarrationSpec,
    step,
    index: int,
) -> None:
    """Trim dead air, then apply the prosody plan's pauses as real silence.

    The pauses matter: an engine reading 「……。」 at speed produces almost no gap,
    and a narration with no gaps between sentences is the single strongest
    "this is a machine" cue. Padding them in gives the plan back its rhythm.
    """
    try:
        trimmed = processor.trim_silence(
            target, target.with_name(f"scene-{index:03d}.trim.wav")
        )
        if trimmed is not None and trimmed.exists():
            target.write_bytes(trimmed.read_bytes())
            trimmed.unlink(missing_ok=True)
        else:
            step.notes.append(f"scene {index}: silence trim skipped (no speech detected)")
    except Exception as exc:  # post-processing must never fail a render
        step.notes.append(f"scene {index}: silence trim error — {exc}")

    lead = max(0, spec.pause_before_ms)
    tail = max(0, spec.pause_after_ms)
    if not lead and not tail:
        return
    try:
        padded = target.with_name(f"scene-{index:03d}.pad.wav")
        ctx.ffmpeg.run_audio_filter(
            target,
            padded,
            ",".join(
                [
                    f"adelay={lead}|{lead}" if lead else "anull",
                    f"apad=pad_dur={tail / 1000.0:.3f}" if tail else "anull",
                ]
            ),
        )
        if padded.exists() and padded.stat().st_size:
            target.write_bytes(padded.read_bytes())
            padded.unlink(missing_ok=True)
    except Exception as exc:
        step.notes.append(f"scene {index}: prosody padding error — {exc}")


def spec_sample_rate(ctx: StageContext) -> int | None:
    """Narration sample rate from settings, when the project pins one."""
    value = ctx.settings.audio.narration_sample_rate
    return int(value) if value else None


# ------------------------------------------------------------------- render
def stage_render(ctx: StageContext) -> list[Path]:
    scenes = ctx.project.scenes
    if not scenes:
        return []
    selected = ctx.job.plan.renderer
    step = ctx.step("render", f"Render scenes ({selected or 'auto'})")
    step.start(selected)
    ctx.event("render", "started", provider=selected, scenes=len(scenes))

    meta = {
        "title": ctx.project.project.title,
        "subtitle": ctx.project.project.subtitle,
        "brand": ctx.project.brand.name,
    }
    out = ctx.work_path / "scenes"
    images: list[Path] = []
    theme = ctx.project.project.theme or "academic-blue"
    for index, scene in enumerate(scenes, start=1):
        shot = scene.shots[0] if scene.shots else None
        payload = {
            "layers": [layer.model_dump() for layer in (shot.layers if shot else [])],
            "intent": scene.intent,
            "title": scene.title,
            "body": scene.body,
            "eyebrow": scene.eyebrow,
            "tags": scene.tags,
            "metric": scene.metric,
            "metric_label": scene.metric_label,
        }
        target = out / f"scene-{index:03d}.png"
        request = RenderSceneRequest(
            scene=payload,
            project_meta=meta,
            theme=theme,
            width=ctx.project.output.width,
            height=ctx.project.output.height,
            out_dir=str(out),
            index=index,
            total=len(scenes),
        )
        cached = cache_get(selected or "renderer", request.model_dump())
        if cached and cached.exists():
            target.write_bytes(cached.read_bytes())
            step.notes.append(f"scene {index}: render cache hit")
        else:
            provider: RendererProvider = provider_for("renderer", selected)  # type: ignore
            try:
                response = provider.render_scene(request)
            except Exception as exc:
                fallback = _next_fallback(ctx, "renderer", selected)
                if not fallback:
                    step.fail(f"{type(exc).__name__}: {exc}", type(exc).__name__)
                    raise
                ctx.job.fallbacks.append(
                    {"stage": "render", "from": selected or "", "to": fallback.id,
                     "reason": str(exc)[:200]}
                )
                response = fallback.render_scene(request)  # type: ignore[union-attr]
                selected = fallback.id
                ctx.job.plan.renderer = fallback.id
            cache_put(selected or "renderer", request.model_dump(), None, target)
        images.append(target)
        ctx.artifact(step, f"frame-{index:03d}", target, "image", scene=scene.id)
        step.progress = index / len(scenes)
        ctx.event("render", "scene", index=index, total=len(scenes))

    step.finish()
    ctx.event("render", "completed", files=len(images))
    return images


# ------------------------------------------------------------------ caption
def stage_caption(ctx: StageContext, audios: list[Path]) -> Path | None:
    if ctx.project.output.captions.mode == "none":
        return None
    step = ctx.step("caption", "Build captions")
    step.start(ctx.job.plan.subtitle)
    cues: list[dict[str, Any]] = []
    clock = 0.0
    for index, scene in enumerate(ctx.project.scenes, start=1):
        audio = audios[index - 1] if index - 1 < len(audios) else None
        duration = wav_duration(audio) if audio and audio.exists() else (
            scene.duration_hint_sec or 4.0
        )
        duration = float(duration or 4.0) + (scene.narration.pause_after_ms or 0) / 1000.0
        text = scene.narration.text or scene.title or ""
        if text:
            cues.append({"start": clock, "end": clock + duration, "text": text})
        clock += duration
    if not cues:
        step.finish()
        return None
    output = ctx.work_path / "captions" / "subtitles.srt"
    from ..providers.base import ProviderType
    from ..providers.registry import available

    writer = None
    for candidate in available(ProviderType.SUBTITLE):
        writer = candidate
        break
    if writer is None:
        step.fail("no subtitle provider available")
        return None
    writer.write({"cues": cues, "output_path": str(output)})  # type: ignore[attr-defined]
    ctx.artifact(step, "subtitles", output, "subtitle", cues=len(cues))
    step.finish()
    ctx.event("caption", "completed", cues=len(cues))
    return output


# ------------------------------------------------------------------ compose
def stage_compose(ctx: StageContext, images: list[Path], audios: list[Path],
                  subtitles: Path | None) -> Path:
    step = ctx.step("compose", "Compose final video")
    step.start("ffmpeg")
    ctx.event("compose", "started", scenes=len(images))
    ffmpeg = ctx.ffmpeg
    ffmpeg.require()

    output_spec = ctx.project.output
    segments: list[Path] = []
    for index, (image, audio) in enumerate(zip(images, audios), start=1):
        if not image.exists() or not audio.exists():
            step.notes.append(f"scene {index}: missing inputs, skipped")
            continue
        segment = ctx.work_path / "segments" / f"segment-{index:03d}.mp4"
        duration = wav_duration(audio) or 4.0
        ffmpeg.image_with_audio(
            image,
            audio,
            segment,
            width=output_spec.width,
            height=output_spec.height,
            fps=output_spec.fps,
            duration=duration + 0.35,
            audio_bitrate_kbps=ctx.settings.render.audio_bitrate_kbps,
        )
        segments.append(segment)
        step.progress = 0.6 * index / max(1, len(images))

    if not segments:
        step.fail("no segments were produced")
        raise RuntimeError("compose failed: no segments")

    raw = ctx.work_path / "raw.mp4"
    ffmpeg.concat(segments, raw)
    step.progress = 0.75

    normalized = ctx.work_path / "normalized.mp4"
    try:
        ffmpeg.normalize_loudness(
            raw, normalized,
            target_lufs=ctx.settings.audio.loudness_target_lufs,
            true_peak=ctx.settings.audio.true_peak_dbtp,
        )
    except Exception as exc:  # normalisation is best-effort, never fatal
        step.notes.append(f"loudness normalisation skipped: {exc}")
        normalized = raw
    step.progress = 0.9

    final_name = f"{ctx.project.project.title or 'video'}-{ctx.job.id}.mp4"
    final = outputs_dir() / _safe_name(final_name)
    if subtitles and subtitles.exists() and ctx.project.output.captions.mode in {
        "burn_in", "both"
    }:
        try:
            ffmpeg.burn_subtitles(normalized, subtitles, final)
        except Exception as exc:
            step.notes.append(f"burn-in failed ({exc}); copying without captions")
            final.write_bytes(normalized.read_bytes())
    else:
        final.write_bytes(normalized.read_bytes())

    ctx.artifact(step, "video", final, "video",
                 duration=ffmpeg.duration(final))
    if subtitles and subtitles.exists():
        ctx.artifact(step, "subtitles_sidecar", subtitles, "subtitle")
    try:
        thumbnail = outputs_dir() / f"{final.stem}.jpg"
        ffmpeg.thumbnail(final, thumbnail)
        ctx.artifact(step, "thumbnail", thumbnail, "image")
    except Exception as exc:  # pragma: no cover - optional
        step.notes.append(f"thumbnail failed: {exc}")

    ctx.job.outputs["video"] = str(final)
    step.finish()
    ctx.event("compose", "completed", video=str(final))
    return final


# ------------------------------------------------------------------ quality
def stage_quality(ctx: StageContext, video: Path) -> dict[str, Any]:
    step = ctx.step("quality", "Quality checks")
    step.start("quality_engine")
    expected = ctx.project.estimated_duration()
    report = ctx.quality.check_video(
        video,
        expected_duration=expected,
        expected_width=ctx.project.output.width,
        expected_height=ctx.project.output.height,
    )
    step.metrics = {
        "passed": report["passed"],
        "failed": report["failed"],
        "warned": report["warned"],
    }
    ctx.job.quality = report
    step.finish()
    ctx.event("quality", "completed", passed=report["passed"],
              failed=report["failed"], warned=report["warned"])
    return report


# ----------------------------------------------------------------- fallback
def _next_fallback(ctx: StageContext, stage: str, current: str | None):
    """Walk the declared fallback chain and return the next usable provider."""
    from .router import FALLBACKS

    chain = FALLBACKS.get(stage, [])
    used = {entry.get("from") for entry in ctx.job.fallbacks if entry["stage"] == stage}
    for candidate in chain:
        if candidate == current or candidate in used:
            continue
        try:
            provider = provider_for(stage, candidate)
        except Exception:
            continue
        if provider.probe().available:
            return provider
    return None


def _safe_name(name: str) -> str:
    return "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip() or "video.mp4"
