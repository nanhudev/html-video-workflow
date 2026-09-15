"""Is the routed voice actually speaking, or writing a tone?

`sapi` and `mock_tts` both return a WAV whose duration tracks the text, so
duration proves nothing. What separates speech from a placeholder tone is
*structure*: the mock writes a constant-amplitude sine, so the energy of every
short window is the same, while speech has syllables, pauses and plosives and
therefore swings wildly. Windowed-energy variance is a crude test, but it is the
crude test that answers the only question that matters here.

Run:  python scripts/voice_probe.py "为什么本地 AI 很重要"
"""
from __future__ import annotations

import math
import struct
import sys
import wave
from pathlib import Path

OUT = Path("D:/hvw-tmp/voice-probe")

TEXT = sys.argv[1] if len(sys.argv) > 1 else "为什么本地 AI 很重要"
OUT.mkdir(parents=True, exist_ok=True)

TARGET = OUT / "probe.wav"


def windowed_energy_variance(path: Path, window_ms: int = 25) -> float:
    """Normalised spread of short-window RMS. A constant tone scores ~0."""
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())

    if width != 2:
        raise SystemExit(f"expected 16-bit samples, got {width * 8}-bit")
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    if channels > 1:
        samples = samples[::channels]

    size = max(1, rate * window_ms // 1000)
    rms: list[float] = []
    for start in range(0, len(samples) - size, size):
        chunk = samples[start:start + size]
        rms.append(math.sqrt(sum(s * s for s in chunk) / len(chunk)))

    if len(rms) < 2:
        return 0.0
    mean = sum(rms) / len(rms)
    if mean <= 0:
        return 0.0
    var = sum((value - mean) ** 2 for value in rms) / len(rms)
    return math.sqrt(var) / mean  # coefficient of variation


def probe(provider_id: str) -> None:
    from html_video_workflow.providers.base import NarrationSpec, TTSRequest
    from html_video_workflow.providers.registry import get
    from html_video_workflow.utils.audio import estimate_speech_seconds, wav_duration

    provider = get(provider_id)
    capability = provider.capabilities()
    print(f"== {provider_id}: available={capability.available} "
          f"languages={capability.languages}")
    if not capability.available:
        print("   skipped: not available here")
        return

    target = OUT / f"{provider_id}.wav"
    try:
        provider.synthesize(TTSRequest(
            narration=NarrationSpec(text=TEXT, language="zh-CN"),
            output_path=str(target),
        ))
    except Exception as exc:  # noqa: BLE001 - a finding, not a crash
        print(f"   synthesis FAILED: {type(exc).__name__}: {exc}")
        return

    duration = wav_duration(target)
    print(f"   wrote {target.name}: {target.stat().st_size} bytes, "
          f"{duration:.2f}s (text estimates ~{estimate_speech_seconds(TEXT):.2f}s)")
    print(f"   windowed-energy spread (0 = a steady tone): "
          f"{windowed_energy_variance(target):.3f}")


if __name__ == "__main__":
    for name in ("sapi", "mock_tts"):
        probe(name)
