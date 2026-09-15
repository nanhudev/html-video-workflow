"""QualityEngine — decide whether an output is acceptable.

Checks are evidence based: file presence, real duration, stream layout, audio
level, black frames, silence. Nothing here silently "fixes" a project.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..ffmpeg.service import FFmpegService
from ..utils.logging import get_logger

log = get_logger("quality.engine")


@dataclass
class CheckResult:
    name: str
    status: str  # pass | warn | fail
    detail: str = ""
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QualityEngine:
    def __init__(self, ffmpeg: FFmpegService | None = None) -> None:
        self.ffmpeg = ffmpeg or FFmpegService()

    # ------------------------------------------------------------------ API
    def check_video(
        self,
        path: str | Path,
        *,
        expected_duration: float | None = None,
        expected_width: int | None = None,
        expected_height: int | None = None,
        duration_tolerance: float = 2.5,
    ) -> dict[str, Any]:
        checks: list[CheckResult] = []
        path = Path(path)

        if not path.exists() or path.stat().st_size == 0:
            checks.append(CheckResult("file_exists", "fail", f"missing or empty: {path}"))
            return _report(path, checks)

        checks.append(
            CheckResult("file_exists", "pass", f"{path.stat().st_size} bytes")
        )

        try:
            info = self.ffmpeg.probe(path)
        except Exception as exc:
            checks.append(CheckResult("probe", "fail", str(exc)[:300]))
            return _report(path, checks)

        fmt = info.get("format", {}) or {}
        duration = float(fmt.get("duration") or 0.0)
        checks.append(
            CheckResult(
                "duration",
                "pass" if duration > 0.2 else "fail",
                f"{duration:.2f}s",
                {"duration": duration},
            )
        )
        if expected_duration:
            delta = abs(duration - expected_duration)
            status = "pass" if delta <= duration_tolerance else "warn"
            checks.append(
                CheckResult(
                    "duration_match",
                    status,
                    f"expected ~{expected_duration:.2f}s, got {duration:.2f}s "
                    f"(Δ{delta:.2f}s)",
                    {"expected": expected_duration, "actual": duration, "delta": delta},
                )
            )

        streams = info.get("streams", []) or []
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        checks.append(CheckResult("video_stream", "pass" if video else "fail",
                                  video.get("codec_name", "") if video else "no video stream"))
        checks.append(CheckResult("audio_stream", "pass" if audio else "warn",
                                  audio.get("codec_name", "") if audio else "no audio stream"))

        if video:
            width, height = int(video.get("width", 0)), int(video.get("height", 0))
            data = {"width": width, "height": height}
            status = "pass"
            if expected_width and expected_height and (width, height) != (
                expected_width,
                expected_height,
            ):
                status = "warn"
            checks.append(
                CheckResult("resolution", status, f"{width}x{height}", data)
            )
            fps = _fps_of(video)
            checks.append(CheckResult("fps", "pass" if fps else "warn", f"{fps or '?'} fps",
                                      {"fps": fps}))

        checks.append(self._audio_level(path))
        if video:
            checks.append(self._black_frames(path))
            checks.append(self._silence(path))

        return _report(path, checks)

    # -------------------------------------------------------------- checks
    def _audio_level(self, path: Path) -> CheckResult:
        if not self.ffmpeg.ffmpeg:
            return CheckResult("audio_level", "warn", "ffmpeg unavailable")
        cmd = [
            self.ffmpeg.ffmpeg, "-v", "info", "-i", str(path),
            "-af", "volumedetect", "-f", "null", "-",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=300)
        except (OSError, subprocess.SubprocessError) as exc:
            return CheckResult("audio_level", "warn", f"volumedetect failed: {exc}")
        text = result.stderr or ""
        mean = _search(r"mean_volume:\s*([-\d.]+)\s*dB", text)
        maximum = _search(r"max_volume:\s*([-\d.]+)\s*dB", text)
        if mean is None:
            return CheckResult("audio_level", "warn", "no audio statistics")
        data = {"mean_volume_db": mean, "max_volume_db": maximum}
        if maximum is not None and maximum > -0.5:
            return CheckResult("audio_level", "fail",
                               f"possible clipping (max {maximum} dB)", data)
        if mean < -45:
            return CheckResult("audio_level", "warn",
                               f"very quiet (mean {mean} dB)", data)
        return CheckResult("audio_level", "pass",
                           f"mean {mean} dB, peak {maximum} dB", data)

    def _black_frames(self, path: Path, min_duration: float = 0.6) -> CheckResult:
        if not self.ffmpeg.ffmpeg:
            return CheckResult("black_frames", "warn", "ffmpeg unavailable")
        cmd = [
            self.ffmpeg.ffmpeg, "-v", "info", "-i", str(path),
            "-vf", f"blackdetect=d={min_duration}:pix_th=0.10",
            "-an", "-f", "null", "-",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=600)
        except (OSError, subprocess.SubprocessError) as exc:
            return CheckResult("black_frames", "warn", f"blackdetect failed: {exc}")
        hits = re.findall(r"blackdetect:.*?black_start:([\d.]+)", result.stderr or "")
        if hits:
            return CheckResult(
                "black_frames", "warn",
                f"{len(hits)} black segment(s) ≥ {min_duration}s",
                {"count": len(hits)},
            )
        return CheckResult("black_frames", "pass", "no long black segments")

    def _silence(self, path: Path, min_duration: float = 3.0) -> CheckResult:
        if not self.ffmpeg.ffmpeg:
            return CheckResult("silence", "warn", "ffmpeg unavailable")
        cmd = [
            self.ffmpeg.ffmpeg, "-v", "info", "-i", str(path),
            "-af", f"silencedetect=n=-45dB:d={min_duration}", "-f", "null", "-",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=600)
        except (OSError, subprocess.SubprocessError) as exc:
            return CheckResult("silence", "warn", f"silencedetect failed: {exc}")
        starts = re.findall(r"silence_start:\s*([\d.]+)", result.stderr or "")
        if starts:
            return CheckResult(
                "silence", "warn",
                f"{len(starts)} silent gap(s) ≥ {min_duration}s",
                {"count": len(starts)},
            )
        return CheckResult("silence", "pass", "no long silent gaps")


def _search(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _fps_of(stream: dict[str, Any]) -> float | None:
    raw = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or ""
    if "/" in raw:
        num, _, den = raw.partition("/")
        try:
            return round(float(num) / float(den), 3) if float(den) else None
        except ValueError:
            return None
    try:
        return float(raw)
    except ValueError:
        return None


def _report(path: Path, checks: list[CheckResult]) -> dict[str, Any]:
    failed = [c.name for c in checks if c.status == "fail"]
    warned = [c.name for c in checks if c.status == "warn"]
    return {
        "path": str(path),
        "passed": not failed,
        "failed": failed,
        "warned": warned,
        "checks": [c.to_dict() for c in checks],
    }
