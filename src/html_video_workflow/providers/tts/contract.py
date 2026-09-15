"""TTS subsystem contracts.

Business code above this module knows one thing: *a TTS provider exists*. It
never learns the name Fish Speech, CosyVoice, AivisSpeech or SAPI — those live
only in ``ProviderSpec.id`` and in the adapter that implements it.

Three rules this module exists to enforce:

1. **A capability is never guessed.** Every optional feature is a tri-state
   ``CapabilityFlag`` — ``yes`` / ``no`` / ``unknown``. A provider that has not
   been probed reports ``unknown``. Reporting ``yes`` without evidence is the
   single easiest way to make an honest pipeline lie.
2. **A request may carry more than a provider supports.** ``TTSRequest`` is the
   union of everything the layer can express. Providers map what they can and
   ignore the rest — but they must *say* what they ignored, via
   ``TTSResult.unsupported_fields``, so a dropped emotion never disappears
   silently.
3. **No heavy imports.** Nothing here may import torch, transformers, or any
   model runtime. Neural engines reach this layer over HTTP or a subprocess.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class CapabilityFlag(str, Enum):
    """Tri-state capability. ``UNKNOWN`` is the honest default.

    A boolean would force every provider to claim something before it has been
    probed. ``unknown`` lets the router weight an unproven feature differently
    from a proven absence, which is the difference between "we have not checked"
    and "this engine cannot do it".
    """

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"

    @property
    def truthy(self) -> bool:
        """Only an explicit ``yes`` counts as support."""
        return self is CapabilityFlag.YES


class QualityTier(str, Enum):
    """Coarse naturalness band, used for routing rather than marketing."""

    NONE = "none"          # silence / tone
    ROBOTIC = "robotic"    # formant synthesis
    BASIC = "basic"        # older concatenative system voices
    GOOD = "good"          # competent neural, audible artefacts under stress
    HIGH = "high"          # natural prosody, suitable for long-form narration
    STUDIO = "studio"      # indistinguishable from a human reader


class GPURequirement(str, Enum):
    NO = "no"
    OPTIONAL = "optional"
    REQUIRED = "required"


class AudioFormat(str, Enum):
    WAV = "wav"
    MP3 = "mp3"
    OGG = "ogg"
    OPUS = "opus"
    FLAC = "flac"
    PCM = "pcm"


class TTSProviderDescriptor(BaseModel):
    """What a TTS provider claims *and* what it has been observed to do.

    Fields inherited from a probe are stored alongside declared ones, so a
    consumer never has to reconcile two objects. ``probed`` records which half
    the reader is looking at.
    """

    id: str
    name: str
    provider_type: str = "tts"
    vendor: str | None = None
    version: str = "0.1.0"
    implementation: str = "inprocess"  # inprocess | subprocess | http | api

    # -- availability ----------------------------------------------------
    installed: CapabilityFlag = CapabilityFlag.UNKNOWN
    available: CapabilityFlag = CapabilityFlag.UNKNOWN
    local: bool = True

    # -- language & voices -----------------------------------------------
    languages: list[str] = Field(default_factory=list)
    voices: list[str] = Field(default_factory=list)
    voice_count: int | None = None

    # -- feature support -------------------------------------------------
    supports_emotion: CapabilityFlag = CapabilityFlag.UNKNOWN
    supports_style: CapabilityFlag = CapabilityFlag.UNKNOWN
    supports_voice_clone: CapabilityFlag = CapabilityFlag.UNKNOWN
    supports_streaming: CapabilityFlag = CapabilityFlag.UNKNOWN
    supports_speed: CapabilityFlag = CapabilityFlag.UNKNOWN
    supports_pitch: CapabilityFlag = CapabilityFlag.UNKNOWN
    supports_emphasis: CapabilityFlag = CapabilityFlag.UNKNOWN
    supports_ssml: CapabilityFlag = CapabilityFlag.UNKNOWN
    supported_formats: list[str] = Field(default_factory=lambda: ["wav"])

    # -- hardware --------------------------------------------------------
    requires_gpu: GPURequirement = GPURequirement.NO
    gpu_backends: list[str] = Field(default_factory=list)
    minimum_vram_mb: int = 0
    recommended_vram_mb: int = 0
    estimated_download_mb: int = 0
    estimated_ram_mb: int = 64

    # -- cost & quality --------------------------------------------------
    quality_tier: QualityTier = QualityTier.BASIC
    quality_score: float = 0.0
    speed_score: float = 0.0
    naturalness_score: float = 0.0
    startup_cost: str = "low"  # low | medium | high
    #: Rough wall-clock ratio for a probe-free estimate; ``None`` means unmeasured.
    estimated_realtime_factor: float | None = None

    # -- licensing -------------------------------------------------------
    license_notes: str | None = None

    # -- provenance ------------------------------------------------------
    probed: bool = False
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    def summary_row(self) -> dict[str, Any]:
        """Compact row for the Studio provider table."""
        return {
            "id": self.id,
            "name": self.name,
            "installed": self.installed.value,
            "available": self.available.value,
            "local": self.local,
            "quality_tier": self.quality_tier.value,
            "languages": self.languages,
            "voice_count": self.voice_count,
            "requires_gpu": self.requires_gpu.value,
            "reason": self.reason,
        }


class TTSRequest(BaseModel):
    """Everything the layer can ask for. Providers map what they support.

    The field set is deliberately wider than any single engine. A provider that
    cannot honour ``emotion`` must report ``emotion`` in
    ``TTSResult.unsupported_fields`` rather than pretending it applied.
    """

    text: str
    language: str = "zh-CN"
    voice: str | None = None
    speaker: str | None = None
    emotion: str | None = None
    speed: float | None = None
    pitch: float | None = None
    volume: float | None = None
    style: str | None = None
    sample_rate: int | None = None
    output_format: AudioFormat = AudioFormat.WAV
    seed: int | None = None

    # -- prosody scheduling (applied by the caller, not the engine) -------
    pause_before_ms: int = 0
    pause_after_ms: int = 0
    emphasis: list[str] = Field(default_factory=list)
    pronunciation: dict[str, str] = Field(default_factory=dict)

    # -- output plumbing --------------------------------------------------
    output_path: str = ""

    @field_validator("speed")
    @classmethod
    def _sane_speed(cls, value: float | None) -> float | None:
        if value is None:
            return None
        # Clamp rather than reject: a planner producing 3.0x is a planner bug,
        # not a reason to fail a render that a 2.0x read would survive.
        return max(0.25, min(4.0, float(value)))

    @field_validator("pitch")
    @classmethod
    def _sane_pitch(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return max(-24.0, min(24.0, float(value)))

    def requested_features(self) -> set[str]:
        """Which optional features this request actually asks for."""
        asked: set[str] = set()
        if self.emotion:
            asked.add("emotion")
        if self.style:
            asked.add("style")
        if self.speed is not None:
            asked.add("speed")
        if self.pitch is not None:
            asked.add("pitch")
        if self.volume is not None:
            asked.add("volume")
        if self.emphasis:
            asked.add("emphasis")
        if self.pronunciation:
            asked.add("pronunciation")
        if self.seed is not None:
            asked.add("seed")
        return asked


class TTSResult(BaseModel):
    """What a synthesis run actually produced."""

    ok: bool = True
    audio_path: str | None = None
    duration_ms: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    provider: str = ""
    model: str | None = None
    voice: str | None = None
    generation_time_ms: int | None = None
    realtime_factor: float | None = None
    seed: int | None = None
    output_format: AudioFormat = AudioFormat.WAV
    #: Request fields this provider could not honour. Never silently dropped.
    unsupported_fields: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None

    @property
    def duration_sec(self) -> float | None:
        return None if self.duration_ms is None else self.duration_ms / 1000.0


class VoiceDescriptor(BaseModel):
    """A selectable voice, richer than the id/name pair the registry needed."""

    id: str
    name: str
    language: str | None = None
    gender: str | None = None
    styles: list[str] = Field(default_factory=list)
    emotions: list[str] = Field(default_factory=list)
    sample_url: str | None = None
    description: str | None = None
    license_notes: str | None = None


# ------------------------------------------------------------------ prosody
class ProsodySegment(BaseModel):
    """One spoken unit with the timing and emphasis it should be read with."""

    text: str
    pause_before_ms: int = 0
    pause_after_ms: int = 0
    emphasis: list[str] = Field(default_factory=list)
    pace: float = 1.0
    emotion: str | None = None
    #: Why the planner chose these values — keeps the baseline debuggable.
    rationale: str | None = None


class ProsodyPlan(BaseModel):
    """A narration text broken into segments a provider can speak in order."""

    segments: list[ProsodySegment] = Field(default_factory=list)
    language: str = "zh-CN"
    total_pause_ms: int = 0
    planner: str = "rule_based"

    @property
    def text(self) -> str:
        return " ".join(segment.text for segment in self.segments)

    def estimated_speech_ms(self, chars_per_second: float = 5.2) -> int:
        """Speech time only, excluding pauses."""
        from ...utils.audio import estimate_speech_seconds

        total = sum(
            estimate_speech_seconds(segment.text, chars_per_second) / max(0.25, segment.pace)
            for segment in self.segments
        )
        return int(total * 1000)


class AudioQualityReport(BaseModel):
    """Automated audio checks. Absent measurements stay ``None``, not zero."""

    ok: bool = True
    path: str | None = None
    duration_ms: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    peak_db: float | None = None
    mean_db: float | None = None
    lufs_integrated: float | None = None
    true_peak_db: float | None = None
    clipping: bool = False
    long_silences: list[dict[str, float]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
