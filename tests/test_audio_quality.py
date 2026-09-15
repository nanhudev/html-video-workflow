"""Audio post-processing and quality-check tests.

These exercise real FFmpeg when it is present, because a mocked filter chain
proves nothing about whether the filter names are valid. When FFmpeg is missing
the tests skip rather than pass — a skipped test is honest, a passing test that
never ran is not.
"""
from __future__ import annotations

import math
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from html_video_workflow.audio import AudioPostProcessor, AudioQualityChecker
from html_video_workflow.ffmpeg.service import FFmpegService

ffmpeg_available = pytest.mark.skipif(
    not FFmpegService().available(), reason="ffmpeg not installed"
)

RATE = 22050


def _write_wav(path: Path, segments: list[tuple[float, float]]) -> Path:
    """Write a mono 16-bit WAV from (seconds, amplitude) pairs.

    Amplitude 0.0 gives real digital silence so silence detection has something
    true to find, rather than near-silence that depends on a threshold.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    for seconds, amplitude in segments:
        for index in range(int(seconds * RATE)):
            if amplitude == 0.0:
                value = 0
            else:
                value = int(
                    32767 * amplitude * math.sin(2 * math.pi * 220.0 * index / RATE)
                )
            frames += struct.pack("<h", value)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(bytes(frames))
    return path


@pytest.fixture
def speech_like(tmp_path: Path) -> Path:
    """0.5 s silence, 1.2 s tone, 0.5 s silence — a stand-in for a narration clip."""
    return _write_wav(tmp_path / "raw.wav", [(0.5, 0.0), (1.2, 0.35), (0.5, 0.0)])


# -------------------------------------------------------------- quality check
@ffmpeg_available
def test_check_reports_duration_and_sample_rate(speech_like: Path):
    report = AudioQualityChecker().check(speech_like)
    assert report.ok
    assert report.sample_rate == RATE
    assert report.channels == 1
    assert report.duration_ms is not None
    assert 2.1 <= report.duration_ms / 1000 <= 2.3


@ffmpeg_available
def test_check_measures_peak_and_loudness(speech_like: Path):
    report = AudioQualityChecker().check(speech_like)
    assert report.peak_db is not None
    assert report.mean_db is not None
    assert report.lufs_integrated is not None, "LUFS should be measurable via loudnorm"
    assert not report.clipping


@ffmpeg_available
def test_check_detects_clipping():
    """Peak at full scale is a defect, not a loud master."""
    path = _write_wav(Path(_tmp()) / "clip.wav", [(1.0, 1.0)])
    report = AudioQualityChecker().check(path)
    assert report.clipping
    assert not report.ok
    assert any("clipping" in failure for failure in report.failures)


@ffmpeg_available
def test_check_flags_a_very_quiet_clip():
    path = _write_wav(Path(_tmp()) / "quiet.wav", [(1.0, 0.0015)])
    report = AudioQualityChecker().check(path)
    assert report.ok, "quiet is a warning, not a failure"
    assert any("quiet" in warning for warning in report.warnings)


@ffmpeg_available
def test_check_finds_long_silence():
    path = _write_wav(Path(_tmp()) / "gap.wav", [(0.2, 0.3), (4.0, 0.0), (0.2, 0.3)])
    report = AudioQualityChecker().check(path, max_silence_sec=3.0)
    assert report.long_silences
    assert any("silent gap" in warning for warning in report.warnings)


@ffmpeg_available
def test_check_warns_when_duration_is_far_from_expected(speech_like: Path):
    report = AudioQualityChecker().check(speech_like, expected_duration_sec=9.0)
    assert any("differs from expected" in warning for warning in report.warnings)


@ffmpeg_available
def test_check_warns_on_unexpected_sample_rate(speech_like: Path):
    report = AudioQualityChecker().check(speech_like, expected_sample_rate=48000)
    assert any("sample rate" in warning for warning in report.warnings)


def test_check_fails_on_missing_file(tmp_path: Path):
    report = AudioQualityChecker().check(tmp_path / "nope.wav")
    assert not report.ok
    assert "missing or empty" in report.failures[0]


def test_check_fails_on_empty_file(tmp_path: Path):
    path = tmp_path / "empty.wav"
    path.write_bytes(b"")
    report = AudioQualityChecker().check(path)
    assert not report.ok
    assert any("missing or empty" in failure for failure in report.failures)


def test_check_fails_on_non_wav_content(tmp_path: Path):
    path = tmp_path / "fake.wav"
    path.write_bytes(b"this is not a wav file at all")
    report = AudioQualityChecker().check(path)
    assert not report.ok
    assert any("not a readable WAV" in failure for failure in report.failures)


def test_absent_measurements_are_none_not_zero(tmp_path: Path):
    """The distinction matters: 0 dBFS means clipping, None means unmeasured."""
    path = tmp_path / "tiny.wav"
    path.write_bytes(b"\x00" * 10)
    report = AudioQualityChecker().check(path)
    assert report.peak_db is None
    assert report.mean_db is None
    assert report.lufs_integrated is None


# ------------------------------------------------------------------- trimming
@ffmpeg_available
def test_trim_silence_shortens_the_clip(speech_like: Path, tmp_path: Path):
    original = AudioQualityChecker().check(speech_like).duration_ms
    trimmed = AudioPostProcessor().trim_silence(speech_like, tmp_path / "trim.wav")
    assert trimmed is not None and trimmed.exists()
    after = AudioQualityChecker().check(trimmed).duration_ms
    assert after < original, "trimming must actually remove dead air"


@ffmpeg_available
def test_trim_silence_keeps_a_natural_lead_in(speech_like: Path, tmp_path: Path):
    """Absolute silence to the first syllable sounds clipped, so keep a sliver."""
    trimmed = AudioPostProcessor().trim_silence(
        speech_like, tmp_path / "trim.wav", keep_sec=0.08
    )
    assert trimmed is not None
    assert AudioQualityChecker().check(trimmed).duration_ms > 1100


@ffmpeg_available
def test_trim_silence_returns_none_for_all_silence(tmp_path: Path):
    """A fully silent clip is a failed synthesis, not an empty file to pass on."""
    silent = _write_wav(tmp_path / "silent.wav", [(2.0, 0.0)])
    assert AudioPostProcessor().trim_silence(silent, tmp_path / "out.wav") is None


@ffmpeg_available
def test_trim_silence_returns_none_when_result_would_be_empty(tmp_path: Path):
    """A 30 ms blip is below the useful-duration floor."""
    blip = _write_wav(tmp_path / "blip.wav", [(0.03, 0.4)])
    assert AudioPostProcessor().trim_silence(blip, tmp_path / "out.wav") is None


# ------------------------------------------------------------------ loudness
@ffmpeg_available
def test_normalize_loudness_moves_toward_the_target(tmp_path: Path):
    quiet = _write_wav(tmp_path / "quiet.wav", [(2.0, 0.02)])
    before = AudioQualityChecker().check(quiet).lufs_integrated
    output = AudioPostProcessor().normalize_loudness(
        quiet, tmp_path / "loud.wav", target_lufs=-16.0
    )
    after = AudioQualityChecker().check(output).lufs_integrated
    assert before is not None and after is not None
    assert abs(after - (-16.0)) < abs(before - (-16.0))


@ffmpeg_available
def test_normalize_loudness_never_fails_a_render(tmp_path: Path):
    """Normalisation is best-effort: a failure must still produce an output."""
    source = _write_wav(tmp_path / "src.wav", [(0.5, 0.3)])
    output = AudioPostProcessor().normalize_loudness(source, tmp_path / "out.wav")
    assert output.exists() and output.stat().st_size > 0


# -------------------------------------------------------------------- fades
@ffmpeg_available
def test_add_fades_produces_a_playable_file(speech_like: Path, tmp_path: Path):
    output = AudioPostProcessor().add_fades(speech_like, tmp_path / "fade.wav")
    assert output.exists()
    assert AudioQualityChecker().check(output).duration_ms > 1000


@ffmpeg_available
def test_fade_out_is_clamped_for_very_short_clips(tmp_path: Path):
    """A 0.2 s fade on a 0.3 s clip would silence the whole thing."""
    short = _write_wav(tmp_path / "short.wav", [(0.3, 0.4)])
    output = AudioPostProcessor().add_fades(
        short, tmp_path / "fade.wav", fade_out_sec=0.2
    )
    assert AudioQualityChecker().check(output).duration_ms > 250


# ----------------------------------------------------------------- resampling
@ffmpeg_available
def test_resample_changes_rate_and_keeps_channel_count(speech_like: Path, tmp_path: Path):
    output = AudioPostProcessor().resample(
        speech_like, tmp_path / "24k.wav", sample_rate=24000, channels=1
    )
    report = AudioQualityChecker().check(output)
    assert report.sample_rate == 24000
    assert report.channels == 1


@ffmpeg_available
def test_resample_can_switch_to_stereo(speech_like: Path, tmp_path: Path):
    output = AudioPostProcessor().resample(
        speech_like, tmp_path / "st.wav", sample_rate=44100, channels=2
    )
    assert AudioQualityChecker().check(output).channels == 2


# ------------------------------------------------------------------ helper
def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()
