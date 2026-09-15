"""Provider contracts.

A Provider is the only layer allowed to know the name of a model, engine or
service. Everything above it talks in capabilities.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, Field


class ProviderType(str, Enum):
    LLM = "llm"
    TTS = "tts"
    ASR = "asr"
    RENDERER = "renderer"
    AVATAR = "avatar"
    IMAGE = "image"
    VIDEO = "video"
    MUSIC = "music"
    ASSET = "asset"
    SUBTITLE = "subtitle"
    STORAGE = "storage"
    AGENT = "agent"


class ProbeState(str, Enum):
    READY = "ready"
    NOT_INSTALLED = "not_installed"
    UNAVAILABLE = "unavailable"
    MISSING_CREDENTIALS = "missing_credentials"
    ERROR = "error"


class VoiceType(str, Enum):
    BUILT_IN = "built_in"
    LICENSED = "licensed"
    USER_OWNED = "user_owned"
    CLONE = "clone"


# ------------------------------------------------------------------- errors
class ProviderError(Exception):
    """Base class for typed, human-readable provider failures."""

    fallback_hint: str = ""

    def __init__(self, message: str, *, provider: str | None = None,
                 fallback: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.fallback_hint = fallback or self.fallback_hint


class ProviderUnavailable(ProviderError):
    fallback_hint = "Choose a different provider for this stage."


class ProviderNotInstalled(ProviderError):
    fallback_hint = "Install this provider, or let the runtime fall back."


class ProviderTimeout(ProviderError):
    fallback_hint = "Retry with a longer timeout or a faster provider."


class OutOfMemory(ProviderError):
    fallback_hint = "Free VRAM/RAM, or use a smaller/CPU provider."


class RenderFailed(ProviderError):
    fallback_hint = "Fallback renderer available (legacy_html)."


class InvalidProject(ProviderError):
    fallback_hint = "Fix the project IR before rendering."


class MissingAsset(ProviderError):
    fallback_hint = "Provide the asset or re-plan the shot."


class UnsupportedCapability(ProviderError):
    fallback_hint = "No provider can satisfy this stage; install one."


# ------------------------------------------------------------------- models
class LicenseInfo(BaseModel):
    code: str | None = None
    model: str | None = None
    commercial: str | None = None  # allowed | restricted | unclear
    attribution: bool = False
    redistribution: str | None = None
    notes: str | None = None


class ProviderSpec(BaseModel):
    """Static declaration of what a provider *claims* to be."""

    id: str
    type: ProviderType
    name: str
    vendor: str | None = None
    version: str = "0.1.0"
    local: bool = True
    implementation: str = "subprocess"  # inprocess | subprocess | http | api
    languages: list[str] = Field(default_factory=list)
    streaming: bool = False
    gpu: bool = False
    cpu: bool = True
    estimated_vram_mb: int = 0
    estimated_ram_mb: int = 64
    quality_score: float = 5.0
    speed_score: float = 5.0
    naturalness_score: float = 5.0
    startup_cost: str = "low"  # low | medium | high
    requires_os: list[str] = Field(default_factory=list)
    requires_binary: list[str] = Field(default_factory=list)
    install_state: str = "builtin"  # builtin | optional | manual
    install_docs: str | None = None
    license: LicenseInfo = Field(default_factory=LicenseInfo)
    voice_type: VoiceType | None = None
    tags: list[str] = Field(default_factory=list)


class VoiceInfo(BaseModel):
    id: str
    name: str
    language: str | None = None
    gender: str | None = None


class Capability(BaseModel):
    """Probed capability — may only confirm or downgrade the spec."""

    id: str
    type: ProviderType
    available: bool = False
    state: ProbeState = ProbeState.UNAVAILABLE
    local: bool = True
    languages: list[str] = Field(default_factory=list)
    voices: list[VoiceInfo] = Field(default_factory=list)
    streaming: bool = False
    gpu: bool = False
    cpu: bool = True
    estimated_vram_mb: int = 0
    quality_score: float = 0.0
    speed_score: float = 0.0
    naturalness_score: float = 0.0
    startup_cost: str = "low"
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ProbeResult(BaseModel):
    state: ProbeState = ProbeState.UNAVAILABLE
    reason: str = ""
    checked_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    evidence: dict[str, Any] = Field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.state == ProbeState.READY


class ProviderResult(BaseModel):
    ok: bool = True
    provider: str
    artifacts: dict[str, str] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    cached: bool = False
    message: str | None = None


# ------------------------------------------------------------ I/O payloads
class NarrationSpec(BaseModel):
    """Renderer-neutral narration description. Providers map what they support."""

    text: str
    speaker: str = "narrator"
    language: str = "zh-CN"
    voice: str | None = None
    emotion: str | None = None
    pace: float | None = None
    pitch: float | None = None
    energy: float | None = None
    pause_before_ms: int = 0
    pause_after_ms: int = 0
    emphasis: list[str] = Field(default_factory=list)
    pronunciation: dict[str, str] = Field(default_factory=dict)
    style: str | None = None


class TTSRequest(BaseModel):
    narration: NarrationSpec
    output_path: str
    sample_rate: int | None = None


class TTSResponse(ProviderResult):
    audio_path: str | None = None
    duration_sec: float | None = None


class LLMRequest(BaseModel):
    prompt: str
    system: str | None = None
    model: str | None = None
    temperature: float = 0.4
    max_tokens: int = 2048
    json_mode: bool = False
    schema_hint: str | None = None


class LLMResponse(ProviderResult):
    text: str = ""
    model: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)


class RenderSceneRequest(BaseModel):
    scene: dict[str, Any]
    project_meta: dict[str, Any] = Field(default_factory=dict)
    theme: str = "academic-blue"
    width: int = 1280
    height: int = 720
    out_dir: str = ""
    index: int = 1
    total: int = 1


class RenderSceneResponse(ProviderResult):
    image_path: str | None = None


# ------------------------------------------------------------------ provider
class Provider(ABC):
    """Base class. Subclasses declare ``spec`` and implement ``probe``."""

    spec: ClassVar[ProviderSpec]

    # -- identity ---------------------------------------------------------
    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def type(self) -> ProviderType:
        return self.spec.type

    # -- contract ---------------------------------------------------------
    @abstractmethod
    def probe(self) -> ProbeResult:
        """Real availability check. Never optimistic."""

    def capabilities(self) -> Capability:
        result = self.probe()
        return Capability(
            id=self.spec.id,
            type=self.spec.type,
            available=result.available,
            state=result.state,
            local=self.spec.local,
            languages=self.spec.languages,
            streaming=self.spec.streaming,
            gpu=self.spec.gpu,
            cpu=self.spec.cpu,
            estimated_vram_mb=self.spec.estimated_vram_mb,
            quality_score=self.spec.quality_score,
            speed_score=self.spec.speed_score,
            naturalness_score=self.spec.naturalness_score,
            startup_cost=self.spec.startup_cost,
            reason=result.reason,
            details=dict(result.evidence),
        )

    def benchmark(self) -> dict[str, Any] | None:  # pragma: no cover - optional
        return None

    def os_supported(self) -> bool:
        """True when this provider declared no OS restriction, or matches it."""
        import platform

        if not self.spec.requires_os:
            return True
        return platform.system() in self.spec.requires_os

    def missing_binaries(self) -> list[str]:
        import shutil

        return [name for name in self.spec.requires_binary if not shutil.which(name)]


class LLMProvider(Provider):
    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse: ...


class TTSProvider(Provider):
    """Base for speech synthesis.

    ``synthesize`` is the only required method. ``list_voices`` and
    ``descriptor`` have honest defaults: a provider that cannot enumerate voices
    returns an empty list rather than inventing plausible names, and a provider
    that has not implemented the rich descriptor simply reports less.
    """

    @abstractmethod
    def synthesize(self, request: TTSRequest) -> TTSResponse: ...

    def list_voices(self) -> list[VoiceInfo]:
        """Selectable voices. An empty list means "could not enumerate"."""
        return []

    def descriptor(self) -> "Any":
        """Rich capability descriptor, or ``None`` when not implemented.

        Imported lazily so ``base`` stays free of a hard dependency on the TTS
        subsystem; providers that implement it return a ``TTSProviderDescriptor``.
        """
        from .tts.contract import CapabilityFlag, TTSProviderDescriptor

        capability = self.capabilities()
        return TTSProviderDescriptor(
            id=self.spec.id,
            name=self.spec.name,
            vendor=self.spec.vendor,
            version=self.spec.version,
            implementation=self.spec.implementation,
            available=(
                CapabilityFlag.YES if capability.available else CapabilityFlag.NO
            ),
            local=self.spec.local,
            languages=list(capability.languages or self.spec.languages),
            quality_score=capability.quality_score or self.spec.quality_score,
            speed_score=capability.speed_score or self.spec.speed_score,
            naturalness_score=capability.naturalness_score or self.spec.naturalness_score,
            startup_cost=capability.startup_cost,
            license_notes=self.spec.license.notes,
            probed=True,
            reason=capability.reason,
        )

    def capabilities(self) -> Capability:
        """Base capability, enriched with the TTS descriptor's feature flags.

        The router scores on feature support (``supports_emotion`` and friends),
        and those live on the descriptor. Folding them into ``details`` here
        means the router reads one object instead of reaching into provider
        internals — and a provider that overrides ``descriptor`` still gets its
        flags surfaced without also having to override ``capabilities``.
        """
        capability = super().capabilities()
        try:
            descriptor = self.descriptor()
        except Exception:  # pragma: no cover - a broken descriptor must not kill routing
            return capability
        if descriptor is None:
            return capability
        for key in (
            "supports_emotion", "supports_style", "supports_voice_clone",
            "supports_streaming", "supports_speed", "supports_pitch",
            "supports_emphasis", "supports_ssml",
        ):
            value = getattr(descriptor, key, None)
            if value is not None:
                capability.details[key] = getattr(value, "value", value)
        capability.details["quality_tier"] = getattr(
            descriptor.quality_tier, "value", descriptor.quality_tier
        )
        capability.details["requires_gpu"] = getattr(
            descriptor.requires_gpu, "value", descriptor.requires_gpu
        )
        if descriptor.voice_count is not None and not capability.voices:
            capability.details["voice_count"] = descriptor.voice_count
        capability.details["implementation"] = descriptor.implementation
        return capability


class RendererProvider(Provider):
    @abstractmethod
    def render_scene(self, request: RenderSceneRequest) -> RenderSceneResponse: ...

    def validate_project(self, project: dict[str, Any]) -> None:
        if not project.get("project", {}).get("title") and not project.get("title"):
            raise InvalidProject("Project is missing a title", provider=self.id)


class AvatarProvider(Provider):
    @abstractmethod
    def generate(self, request: dict[str, Any]) -> ProviderResult: ...


class ImageProvider(Provider):
    @abstractmethod
    def generate_image(self, request: dict[str, Any]) -> ProviderResult: ...


class VideoProvider(Provider):
    @abstractmethod
    def generate_video(self, request: dict[str, Any]) -> ProviderResult: ...


class MusicProvider(Provider):
    @abstractmethod
    def generate_music(self, request: dict[str, Any]) -> ProviderResult: ...


class ASRProvider(Provider):
    @abstractmethod
    def transcribe(self, request: dict[str, Any]) -> ProviderResult: ...


class AssetProvider(Provider):
    @abstractmethod
    def resolve(self, request: dict[str, Any]) -> ProviderResult: ...


class SubtitleProvider(Provider):
    @abstractmethod
    def write(self, request: dict[str, Any]) -> ProviderResult: ...


class StorageProvider(Provider):
    @abstractmethod
    def put(self, request: dict[str, Any]) -> ProviderResult: ...


class AgentProvider(Provider):
    @abstractmethod
    def run(self, request: dict[str, Any]) -> ProviderResult: ...
