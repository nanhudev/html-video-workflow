"""FFmpegService — the single place that shells out to ffmpeg/ffprobe.

Everything encoding-related goes through here: probe, segment encode, concat,
mix, loudness normalisation, thumbnails. No other module builds ffmpeg argv.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..config.paths import cache_dir
from ..utils.logging import get_logger

log = get_logger("ffmpeg.service")


class FFmpegMissing(RuntimeError):
    pass


class FFmpegError(RuntimeError):
    pass


class FFmpegService:
    def __init__(self) -> None:
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")

    # ------------------------------------------------------------ probing
    def available(self) -> bool:
        return bool(self.ffmpeg and self.ffprobe)

    def require(self) -> None:
        if not self.ffmpeg:
            raise FFmpegMissing("ffmpeg not found on PATH")
        if not self.ffprobe:
            raise FFmpegMissing("ffprobe not found on PATH")

    def version(self) -> str | None:
        if not self.ffmpeg:
            return None
        result = subprocess.run(
            [self.ffmpeg, "-version"], capture_output=True, text=True, timeout=30
        )
        line = (result.stdout or "").splitlines()
        return line[0].strip() if line else None

    def probe(self, path: str | Path) -> dict[str, Any]:
        """Return ffprobe stream/format information as a dict."""
        self.require()
        assert self.ffprobe  # for type checkers
        cmd = [
            self.ffprobe,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise FFmpegError(f"ffprobe failed: {(result.stderr or '').strip()[:300]}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise FFmpegError("ffprobe returned invalid JSON") from exc

    def duration(self, path: str | Path) -> float:
        info = self.probe(path)
        try:
            return float(info["format"]["duration"])
        except (KeyError, TypeError, ValueError):
            for stream in info.get("streams", []):
                if stream.get("duration"):
                    return float(stream["duration"])
            return 0.0

    # ---------------------------------------------------------- rendering
    def image_with_audio(
        self,
        image: str | Path,
        audio: str | Path,
        output: str | Path,
        *,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        duration: float | None = None,
        crf: int = 19,
        audio_bitrate_kbps: int = 160,
        zoom: bool = True,
    ) -> Path:
        """Build one scene segment: still image + narration + gentle motion."""
        self.require()
        assert self.ffmpeg
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        if duration is None:
            duration = self.duration(audio) + 0.35
        filter_parts = [
            f"scale={width}:{height}:force_original_aspect_ratio=decrease",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "format=yuv420p",
        ]
        if zoom:
            # `d=1` is load-bearing. With `-loop 1` the input is an endless frame
            # stream and `-t` already bounds the segment, so zoompan must emit
            # exactly one output frame per input frame. Setting `d=<frames>`
            # instead makes zoompan hold each input frame for the whole segment
            # AND keep evaluating `z='min(zoom+...)` on every emitted frame; the
            # zoom races past its 1.04 cap and resamples the still into a washed
            # out, blurry image for the rest of the scene.
            #
            # `x`/`y` are pinned to the centre so the push-in stays centred;
            # without them zoompan anchors at the top-left corner.
            filter_parts.insert(
                2,
                f"zoompan=z='min(zoom+0.00035,1.04)':d=1"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":s={width}x{height}:fps={fps}",
            )
        filter_parts += [
            "fade=t=in:st=0:d=0.25",
            f"fade=t=out:st={max(0.1, duration - 0.3):.3f}:d=0.3",
        ]
        cmd = [
            self.ffmpeg, "-y", "-v", "error",
            "-loop", "1", "-i", str(image),
            "-i", str(audio),
            "-vf", ",".join(filter_parts),
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k",
            "-shortest",
            str(output),
        ]
        self._run(cmd)
        return output

    def run_audio_filter(
        self,
        input_path: str | Path,
        output_path: str | Path,
        filters: str,
        *,
        codec: str = "pcm_s16le",
        extra_args: list[str] | None = None,
    ) -> Path:
        """Apply an FFmpeg audio filter chain and write a WAV.

        Processed narration stays PCM until composition, so a chain of trims,
        fades and resamples costs nothing in generation loss. Routing this
        through AAC at every step would stack artefacts before the final encode.
        """
        self.require()
        assert self.ffmpeg
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.ffmpeg, "-y", "-v", "error",
            "-i", str(input_path),
            "-af", filters,
            "-c:a", codec,
            *(extra_args or []),
            str(output_path),
        ]
        self._run(cmd)
        return output_path

    def concat(self, segments: list[str | Path], output: str | Path) -> Path:
        """Concatenate segments with the concat demuxer (stream copy)."""
        self.require()
        assert self.ffmpeg
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        list_path = output.with_suffix(".concat.txt")
        list_path.write_text(
            "\n".join(f"file '{Path(s).resolve().as_posix()}'" for s in segments),
            encoding="utf-8",
        )
        cmd = [
            self.ffmpeg, "-y", "-v", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-c", "copy", str(output),
        ]
        self._run(cmd)
        return output

    def normalize_loudness(
        self,
        input_path: str | Path,
        output: str | Path,
        *,
        target_lufs: float = -16.0,
        true_peak: float = -1.5,
        loudness_range: float | None = None,
    ) -> Path:
        """EBU R128 two-pass loudness normalisation.

        The output codec follows the output extension. An earlier version always
        wrote AAC, which meant normalising narration produced ``.wav`` files
        holding AAC streams — a combination most tools cannot read, and one that
        silently changed the codec of an audio-only step. PCM is the right answer
        for a ``.wav`` target; the caller does not have to know this.
        """
        self.require()
        assert self.ffmpeg
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        audio_args = self._audio_codec_args(output)
        lra_clause = f":LRA={loudness_range}" if loudness_range is not None else ""
        measure = subprocess.run(
            [
                self.ffmpeg, "-v", "error", "-i", str(input_path),
                "-af",
                f"loudnorm=I={target_lufs}:TP={true_peak}{lra_clause}:print_format=json",
                "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=600,
        )
        measured: dict[str, Any] = {}
        tail = (measure.stderr or "").strip().splitlines()
        if tail:
            try:
                measured = json.loads(tail[-1])
            except json.JSONDecodeError:
                measured = {}
        filters = [f"loudnorm=I={target_lufs}:TP={true_peak}{lra_clause}"]
        if measured:
            filters = [
                "loudnorm="
                f"I={target_lufs}:TP={true_peak}{lra_clause}"
                f":measured_I={measured.get('input_i', target_lufs)}"
                f":measured_TP={measured.get('input_tp', true_peak)}"
                f":measured_LRA={measured.get('input_lra', 7.0)}"
                f":measured_thresh={measured.get('input_thresh', -30.0)}"
                ":linear=true"
            ]
        cmd = [
            self.ffmpeg, "-y", "-v", "error", "-i", str(input_path),
            "-af", ",".join(filters),
            *audio_args,
            str(output),
        ]
        self._run(cmd)
        return output

    @staticmethod
    def _audio_codec_args(output: Path) -> list[str]:
        """Pick audio codec arguments that match the output container.

        A WAV container with an AAC stream is technically expressible and
        practically unusable: ``wave`` cannot open it, and it changes the codec of
        a step that was supposed to be lossless.
        """
        suffix = output.suffix.lower()
        if suffix in {".wav", ".wave"}:
            return ["-c:a", "pcm_s16le"]
        if suffix == ".flac":
            return ["-c:a", "flac"]
        if suffix in {".m4a", ".mp4", ".mov", ".mkv"}:
            return ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
        return ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]

    def mix_bgm(
        self,
        video: str | Path,
        bgm: str | Path,
        output: str | Path,
        *,
        bgm_gain_db: float = -18.0,
        duck: bool = True,
    ) -> Path:
        """Mix background music under narration with optional ducking."""
        self.require()
        assert self.ffmpeg
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        if duck:
            filter_complex = (
                f"[1:a]volume={bgm_gain_db}dB[bg];"
                "[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2,"
                "dynaudnorm=p=0.9:m=6[out]"
            )
        else:
            filter_complex = (
                f"[1:a]volume={bgm_gain_db}dB[bg];"
                "[0:a][bg]amix=inputs=2:duration=first[out]"
            )
        cmd = [
            self.ffmpeg, "-y", "-v", "error",
            "-i", str(video), "-i", str(bgm),
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[out]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(output),
        ]
        self._run(cmd)
        return output

    def burn_subtitles(self, video: str | Path, subtitles: str | Path,
                       output: str | Path) -> Path:
        self.require()
        assert self.ffmpeg
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        sub = str(Path(subtitles).resolve()).replace("\\", "/").replace(":", "\\:")
        cmd = [
            self.ffmpeg, "-y", "-v", "error", "-i", str(video),
            "-vf", f"subtitles='{sub}'",
            "-c:a", "copy", str(output),
        ]
        self._run(cmd)
        return output

    def thumbnail(self, video: str | Path, output: str | Path,
                  timestamp: float = 1.0) -> Path:
        self.require()
        assert self.ffmpeg
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.ffmpeg, "-y", "-v", "error", "-ss", f"{timestamp:.2f}",
            "-i", str(video), "-frames:v", "1", "-q:v", "2", str(output),
        ]
        self._run(cmd)
        return output

    # -------------------------------------------------------------- internals
    def _run(self, cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
        self.require()
        log.debug("ffmpeg: %s", " ".join(str(c) for c in cmd[:6]) + " …")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise FFmpegError(f"ffmpeg failed (rc={result.returncode}): "
                              f"{(result.stderr or '').strip()[-400:]}")
        return result


_service: FFmpegService | None = None


def get_service() -> FFmpegService:
    global _service
    if _service is None:
        _service = FFmpegService()
    return _service


def benchmark_dir() -> Path:
    path = cache_dir() / "ffmpeg"
    path.mkdir(parents=True, exist_ok=True)
    return path
