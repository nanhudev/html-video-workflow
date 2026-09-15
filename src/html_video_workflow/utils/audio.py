"""Tiny stdlib audio helpers (no ffmpeg dependency for the basics)."""
from __future__ import annotations

import wave
from pathlib import Path


def wav_duration(path: str | Path) -> float | None:
    """Return duration in seconds, or None when the file is not a readable WAV."""
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            if not rate:
                return None
            return frames / float(rate)
    except (wave.Error, OSError, EOFError):
        return None


def write_tone_wav(
    path: str | Path,
    seconds: float = 1.0,
    sample_rate: int = 22050,
    frequency: float = 180.0,
    amplitude: float = 0.05,
) -> str:
    """Write a quiet sine tone as a mono 16-bit WAV (mock narration)."""
    import math
    import struct

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    total = max(1, int(seconds * sample_rate))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for index in range(total):
            value = int(32767 * amplitude * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames += struct.pack("<h", value)
        handle.writeframes(bytes(frames))
    return str(path)


def estimate_speech_seconds(text: str, chars_per_second: float = 5.2) -> float:
    """Rough narration length estimate used before real audio exists."""
    cleaned = "".join(ch for ch in text if not ch.isspace())
    cjk = sum(1 for ch in cleaned if "一" <= ch <= "鿿")
    latin = len(cleaned) - cjk
    return max(0.8, cjk / chars_per_second + latin / 13.0)
