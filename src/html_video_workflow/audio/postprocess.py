"""Audio post-processing and quality checks.

Both live in one module because they share the only dependency that matters:
FFmpeg. Neither introduces a DSP library — ``pyloudnorm``, ``librosa`` and
``soundfile`` would each add tens of megabytes and a compiled-wheel matrix to
the core install so we could compute a few numbers FFmpeg already reports.

**What post-processing may not do** is hide a problem. Trimming silence is a
style choice; deleting the evidence that a scene produced no speech is not. So
the processor reports what it changed, and the quality checker runs against the
result rather than assuming it worked.
"""
from __future__ import annotations

import re
import subprocess
import wave
from pathlib import Path

from ..ffmpeg.service import FFmpegService
from ..providers.tts.contract import AudioQualityReport
from ..utils.logging import get_logger

log = get_logger("audio.postprocess")


class AudioPostProcessor:
    """FFmpeg-backed narration clean-up."""

    def __init__(self, ffmpeg: FFmpegService | None = None) -> None:
        self.ffmpeg = ffmpeg or FFmpegService()

    # ------------------------------------------------------------- trims
    def trim_silence(
        self,
        source: str | Path,
        output: str | Path,
        *,
        threshold_db: float = -50.0,
        min_silence_sec: float = 0.35,
        keep_sec: float = 0.08,
    ) -> Path | None:
        """Remove leading/trailing silence, keeping a short natural lead-in.

        Returns ``None`` when the result would be empty — a fully silent clip is
        a failed synthesis, and returning a 0-byte file would turn that into a
        mysterious downstream failure.
        """
        source, output = Path(source), Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        filters = ",".join(
            [
                f"silenceremove=start_periods=1:start_silence={keep_sec}"
                f":start_threshold={threshold_db}dB",
                f"areverse",
                f"silenceremove=start_periods=1:start_silence={keep_sec}"
                f":start_threshold={threshold_db}dB",
                f"areverse",
            ]
        )
        try:
            self.ffmpeg.run_audio_filter(source, output, filters)
        except Exception as exc:
            log.warning("silence trim failed for %s: %s", source.name, exc)
            return None
        if not output.exists() or output.stat().st_size == 0:
            return None
        if (self._duration(output) or 0.0) < 0.05:
            return None
        return output

    # ---------------------------------------------------------- loudness
    def normalize_loudness(
        self,
        source: str | Path,
        output: str | Path,
        *,
        target_lufs: float = -16.0,
        true_peak_dbtp: float = -1.5,
        loudness_range_lu: float = 11.0,
    ) -> Path:
        """EBU R128 normalisation. Falls back to a copy when measurement fails."""
        source, output = Path(source), Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            return self.ffmpeg.normalize_loudness(
                source,
                output,
                target_lufs=target_lufs,
                true_peak=true_peak_dbtp,
                loudness_range=loudness_range_lu,
            )
        except Exception as exc:
            log.warning("loudness normalisation failed, copying source: %s", exc)
            output.write_bytes(source.read_bytes())
            return output

    # -------------------------------------------------------------- fades
    def add_fades(
        self,
        source: str | Path,
        output: str | Path,
        *,
        fade_in_sec: float = 0.06,
        fade_out_sec: float = 0.12,
    ) -> Path:
        source, output = Path(source), Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        duration = self._duration(source) or 0.0
        fade_out_sec = min(fade_out_sec, max(0.0, duration / 3))
        filters = ",".join(
            [
                f"afade=t=in:st=0:d={fade_in_sec}",
                f"afade=t=out:st={max(0.0, duration - fade_out_sec):.3f}:d={fade_out_sec}",
            ]
        )
        self.ffmpeg.run_audio_filter(source, output, filters)
        return output

    # ------------------------------------------------------------ resample
    def resample(
        self,
        source: str | Path,
        output: str | Path,
        *,
        sample_rate: int = 24000,
        channels: int = 1,
    ) -> Path:
        source, output = Path(source), Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        aformat = "mono" if channels == 1 else "stereo"
        filters = f"aresample={sample_rate},aformat=channel_layouts={aformat}"
        self.ffmpeg.run_audio_filter(source, output, filters)
        return output

    # --------------------------------------------------------------- bits
    def _duration(self, path: Path) -> float | None:
        try:
            return self.ffmpeg.duration(path)
        except Exception:
            return None


class AudioQualityChecker:
    """Automated audio checks.

    Every absent measurement is reported as ``None`` rather than ``0``. A peak
    of 0 dBFS means clipping; an *unknown* peak means FFmpeg could not measure a
    file, which is a different problem and deserves a different message.
    """

    def __init__(self, ffmpeg: FFmpegService | None = None) -> None:
        self.ffmpeg = ffmpeg or FFmpegService()

    def check(
        self,
        path: str | Path,
        *,
        expected_duration_sec: float | None = None,
        expected_sample_rate: int | None = None,
        max_silence_sec: float = 3.0,
        duration_tolerance: float = 1.5,
    ) -> AudioQualityReport:
        path = Path(path)
        report = AudioQualityReport(path=str(path))

        if not path.exists() or path.stat().st_size == 0:
            report.ok = False
            report.failures.append("audio file missing or empty")
            return report

        fmt = self._wav_header(path)
        if fmt is None:
            report.failures.append("not a readable WAV container")
            report.ok = False
            return report
        rate, channels, duration = fmt
        report.sample_rate = rate
        report.channels = channels
        report.duration_ms = int(duration * 1000)

        if duration <= 0.05:
            report.failures.append(f"duration too short ({duration:.3f}s)")
        if expected_duration_sec is not None:
            delta = abs(duration - expected_duration_sec)
            if delta > duration_tolerance:
                report.warnings.append(
                    f"duration {duration:.2f}s differs from expected "
                    f"{expected_duration_sec:.2f}s by {delta:.2f}s"
                )
        if expected_sample_rate and rate != expected_sample_rate:
            report.warnings.append(
                f"sample rate {rate} Hz, expected {expected_sample_rate} Hz"
            )

        volumes = self._volumedetect(path)
        report.peak_db = volumes.get("max")
        report.mean_db = volumes.get("mean")
        if report.peak_db is not None and report.peak_db >= -0.1:
            report.clipping = True
            report.failures.append(f"clipping (peak {report.peak_db:.1f} dBFS)")
        elif report.peak_db is not None and report.peak_db >= -1.0:
            report.warnings.append(
                f"peak close to full scale ({report.peak_db:.1f} dBFS)"
            )
        if report.mean_db is not None and report.mean_db < -50:
            report.warnings.append(
                f"very quiet (mean {report.mean_db:.1f} dBFS) — narration may be inaudible"
            )

        loudness = self._loudnorm_measure(path)
        report.lufs_integrated = loudness.get("input_i")
        report.true_peak_db = loudness.get("input_tp")
        if report.lufs_integrated is not None and report.lufs_integrated < -30:
            report.warnings.append(
                f"integrated loudness {report.lufs_integrated:.1f} LUFS is very low"
            )

        report.long_silences = self._silences(path, max_silence_sec)
        if report.long_silences:
            report.warnings.append(
                f"{len(report.long_silences)} silent gap(s) ≥ {max_silence_sec}s"
            )

        report.ok = not report.failures
        return report

    # -------------------------------------------------------------- probes
    @staticmethod
    def _wav_header(path: Path) -> tuple[int, int, float] | None:
        try:
            with wave.open(str(path), "rb") as handle:
                rate = handle.getframerate()
                channels = handle.getnchannels()
                frames = handle.getnframes()
        except (wave.Error, OSError, EOFError):
            return None
        if not rate:
            return None
        return rate, channels, frames / float(rate)

    def _volumedetect(self, path: Path) -> dict[str, float]:
        if not self.ffmpeg.ffmpeg:
            return {}
        cmd = [
            self.ffmpeg.ffmpeg, "-v", "info", "-i", str(path),
            "-af", "volumedetect", "-f", "null", "-",
        ]
        completed = self._run(cmd)
        if completed is None:
            return {}
        text = completed.stderr or ""
        out: dict[str, float] = {}
        mean = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", text)
        peak = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", text)
        if mean:
            out["mean"] = float(mean.group(1))
        if peak:
            out["max"] = float(peak.group(1))
        return out

    def _loudnorm_measure(self, path: Path) -> dict[str, float]:
        """First-pass loudnorm measurement. Values are ``None`` when unavailable."""
        if not self.ffmpeg.ffmpeg:
            return {}
        cmd = [
            self.ffmpeg.ffmpeg, "-v", "info", "-i", str(path),
            "-af", "loudnorm=print_format=json", "-f", "null", "-",
        ]
        completed = self._run(cmd)
        if completed is None:
            return {}
        text = completed.stderr or ""
        # loudnorm prints its JSON last; find the final balanced object.
        match = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", text, re.DOTALL)
        if not match:
            return {}
        import json

        try:
            data = json.loads(match[-1])
        except json.JSONDecodeError:
            return {}
        out: dict[str, float] = {}
        for key, target in (("input_i", "input_i"), ("input_tp", "input_tp")):
            try:
                value = float(data[target])
            except (KeyError, TypeError, ValueError):
                continue
            # loudnorm reports -inf for digital silence as the string "-inf".
            if value == float("-inf") or value < -99:
                continue
            out[key] = value
        return out

    def _silences(self, path: Path, min_duration: float) -> list[dict[str, float]]:
        if not self.ffmpeg.ffmpeg:
            return []
        cmd = [
            self.ffmpeg.ffmpeg, "-v", "info", "-i", str(path),
            "-af", f"silencedetect=n=-45dB:d={min_duration}", "-f", "null", "-",
        ]
        completed = self._run(cmd)
        if completed is None:
            return []
        text = completed.stderr or ""
        starts = [float(v) for v in re.findall(r"silence_start:\s*(-?[\d.]+)", text)]
        ends = [float(v) for v in re.findall(r"silence_end:\s*(-?[\d.]+)", text)]
        gaps: list[dict[str, float]] = []
        for index, start in enumerate(starts):
            end = ends[index] if index < len(ends) else start
            gaps.append({"start": start, "end": end, "duration": round(end - start, 3)})
        return gaps

    @staticmethod
    def _run(cmd: list[str]) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("audio probe failed: %s", exc)
            return None
