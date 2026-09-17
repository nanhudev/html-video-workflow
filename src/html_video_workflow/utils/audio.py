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


#: Measured Windows SAPI Chinese rate, in CJK characters per second.
#:
#: This is a *measurement*, not a guess. The value used to be 5.2, which was
#: never checked against an engine: narration timed at 3.35 chars/s on the SAPI
#: voices this project actually ships against, so every estimate was ~55% short
#: and a "20 second" video arrived at ~31 seconds. That drift is the single most
#: visible defect a viewer notices, because it makes the voice and the pictures
#: disagree.
#:
#: Re-measure with `scripts/measure_speech_rate.py` on any machine/voice before
#: trusting this number; it is a property of the engine, not of the language.
SAPI_CJK_CHARS_PER_SECOND = 3.35

#: Latin text through the same engine, measured on the same run (10.79/s).
#: It used to be 13.0, which made English narration ~17% short for the same
#: reason the CJK figure was wrong: nobody had timed it.
SAPI_LATIN_CHARS_PER_SECOND = 10.8

#: Engineering margin. Speech rate varies with punctuation, numbers and the
#: voice selected, and *undershooting* is the harmless direction: a scene that
#: runs slightly long holds its last frame, while one that runs short cuts the
#: speaker off mid-word. 4% is enough to keep the common case from clipping.
_SPEECH_SAFETY = 0.96

#: Breathing room added after a scene's narration, in seconds.
#:
#: This is what turns a sequence of sentences into a sequence of *scenes*:
#: without it the narration runs together and the video reads as one unbroken
#: drone. It lives here because two stages have to agree on it — the planner
#: budgets ``speech + pad`` per scene and the composer pads the rendered segment
#: by the same amount. They used to hard-code different numbers (0.9 and 0.35),
#: so a 28s request planned 25.5s of content against a render that could hold
#: 23.2s and delivered 20.3s. One constant, one answer.
SCENE_TAIL_PAD_SEC = 0.35


def estimate_speech_seconds(
    text: str,
    chars_per_second: float = SAPI_CJK_CHARS_PER_SECOND,
    *,
    latin_chars_per_second: float = SAPI_LATIN_CHARS_PER_SECOND,
) -> float:
    """How long this narration will take to speak, within a few percent.

    The default rate is the measured SAPI figure (see
    :data:`SAPI_CJK_CHARS_PER_SECOND`). A caller that knows it is routing to a
    different engine should pass that engine's rate; the constant is a default,
    not a law.
    """
    cleaned = "".join(ch for ch in text if not ch.isspace())
    cjk = sum(1 for ch in cleaned if "一" <= ch <= "鿿")
    latin = len(cleaned) - cjk
    seconds = cjk / chars_per_second + latin / latin_chars_per_second
    return max(0.8, seconds / _SPEECH_SAFETY)
