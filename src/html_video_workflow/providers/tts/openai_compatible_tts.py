"""OpenAI-compatible speech endpoint adapter.

Works against anything that speaks ``POST {base}/audio/speech`` with
``{model, input, voice, response_format}`` — the OpenAI API, Azure-compatible
gateways, a vLLM/OpenAI-proxy in front of a local model, or a home-grown TTS
gateway that mirrored the shape.

**Secret handling is the reason this file is careful.** The API key:

* is read from the environment only, never from a project file;
* is never written into ``job.json``, ``events.jsonl`` or any artifact;
* is masked when it appears in a descriptor or error message;
* is passed as a header, so it cannot leak through a logged query string.

The key that reaches a log is a key that has been revoked and reissued. There is
no exception to this.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from ...config.settings import mask_secret
from ...utils.audio import wav_duration
from ...utils.logging import get_logger
from ..base import (
    ProbeResult,
    ProbeState,
    ProviderSpec,
    ProviderTimeout,
    ProviderUnavailable,
    TTSProvider,
    TTSRequest,
    TTSResponse,
    VoiceInfo,
    VoiceType,
)
from ..registry import register
from .contract import (
    AudioFormat,
    CapabilityFlag,
    GPURequirement,
    QualityTier,
    TTSProviderDescriptor,
    TTSResult,
    VoiceDescriptor,
)
from .http_client import join_url, request

log = get_logger("providers.tts.openai_compatible")

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "tts-1"
DEFAULT_VOICE = "alloy"
DEFAULT_TIMEOUT = 120.0

#: Environment variables consulted, in order. The first non-empty one wins.
API_KEY_ENV_VARS = ("HVW_TTS_API_KEY", "OPENAI_API_KEY")

#: Voices the reference implementation advertises. A custom gateway may have
#: different ones, so these are labelled as *known* rather than *exhaustive*.
KNOWN_VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")

FORMAT_TO_REQUEST: dict[AudioFormat, str] = {
    AudioFormat.WAV: "wav",
    AudioFormat.MP3: "mp3",
    AudioFormat.OPUS: "opus",
    AudioFormat.FLAC: "flac",
    AudioFormat.PCM: "pcm",
}
FORMAT_CONTENT_TYPE: dict[AudioFormat, str] = {
    AudioFormat.WAV: "audio/wav",
    AudioFormat.MP3: "audio/mpeg",
    AudioFormat.OPUS: "audio/ogg",
    AudioFormat.FLAC: "audio/flac",
    AudioFormat.PCM: "application/octet-stream",
}


@register
class OpenAICompatibleTTSProvider(TTSProvider):
    spec = ProviderSpec(
        id="openai_compatible_tts",
        type="tts",
        name="OpenAI-compatible TTS",
        vendor="OpenAI / any compatible gateway",
        version="1.0.0",
        local=False,
        implementation="api",
        languages=["en-US", "zh-CN", "ja-JP", "ko-KR", "es-ES", "fr-FR", "de-DE"],
        quality_score=8.0,
        speed_score=8.0,
        naturalness_score=8.0,
        startup_cost="low",
        install_state="optional",
        install_docs="Set HVW_TTS_API_KEY (or OPENAI_API_KEY) and optionally "
                     "HVW_TTS_BASE_URL.",
        voice_type=VoiceType.LICENSED,
        tags=["cloud", "api", "openai-compatible", "neural"],
    )

    # -------------------------------------------------------------- config
    @property
    def api_key(self) -> str | None:
        for name in API_KEY_ENV_VARS:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return None

    @property
    def masked_key(self) -> str:
        """Always safe to log. ``sk-****7a3`` or empty."""
        return mask_secret(self.api_key)

    @property
    def base_url(self) -> str:
        return os.environ.get("HVW_TTS_BASE_URL", "").strip() or DEFAULT_BASE_URL

    @property
    def model(self) -> str:
        return os.environ.get("HVW_TTS_MODEL", "").strip() or DEFAULT_MODEL

    @property
    def default_voice(self) -> str:
        return os.environ.get("HVW_TTS_VOICE", "").strip() or DEFAULT_VOICE

    @property
    def timeout(self) -> float:
        raw = os.environ.get("HVW_TTS_TIMEOUT", "").strip()
        try:
            return float(raw) if raw else DEFAULT_TIMEOUT
        except ValueError:
            return DEFAULT_TIMEOUT

    # ------------------------------------------------------------- probing
    def probe(self) -> ProbeResult:
        key = self.api_key
        if not key:
            return ProbeResult(
                state=ProbeState.MISSING_CREDENTIALS,
                reason="No API key found (" + " / ".join(API_KEY_ENV_VARS) + ")",
                evidence={"base_url": self.base_url, "model": self.model,
                          "key": self.masked_key},
            )
        return ProbeResult(
            state=ProbeState.READY,
            reason=f"API key present for {self.base_url} (model {self.model})",
            evidence={
                "base_url": self.base_url,
                "model": self.model,
                "key": self.masked_key,
                "voices": list(KNOWN_VOICES),
            },
        )

    def list_voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(id=name, name=name.title(), language="en-US")
            for name in KNOWN_VOICES
        ]

    def voice_descriptors(self) -> list[VoiceDescriptor]:
        return [
            VoiceDescriptor(
                id=name,
                name=name.title(),
                language=None,
                license_notes="Licensed for use through the configured endpoint.",
            )
            for name in KNOWN_VOICES
        ]

    def descriptor(self) -> TTSProviderDescriptor:
        result = self.probe()
        return TTSProviderDescriptor(
            id=self.spec.id,
            name=self.spec.name,
            vendor=self.spec.vendor,
            version=self.spec.version,
            implementation="api",
            installed=CapabilityFlag.YES,
            available=CapabilityFlag.YES if result.available else CapabilityFlag.NO,
            local=False,
            languages=list(self.spec.languages),
            voices=list(KNOWN_VOICES),
            voice_count=len(KNOWN_VOICES) if result.available else None,
            supports_emotion=CapabilityFlag.NO,
            supports_style=CapabilityFlag.UNKNOWN,
            supports_voice_clone=CapabilityFlag.UNKNOWN,
            supports_streaming=CapabilityFlag.YES,
            supports_speed=CapabilityFlag.NO,
            supports_pitch=CapabilityFlag.NO,
            supports_emphasis=CapabilityFlag.NO,
            supports_ssml=CapabilityFlag.NO,
            supported_formats=["mp3", "opus", "aac", "flac", "wav", "pcm"],
            requires_gpu=GPURequirement.NO,
            gpu_backends=[],
            minimum_vram_mb=0,
            recommended_vram_mb=0,
            estimated_download_mb=0,
            estimated_ram_mb=128,
            quality_tier=QualityTier.HIGH,
            quality_score=self.spec.quality_score,
            speed_score=self.spec.speed_score,
            naturalness_score=self.spec.naturalness_score,
            startup_cost="low",
            estimated_realtime_factor=0.35,
            license_notes="Billed per character by the endpoint operator. "
                          "Voice licence follows the provider's terms.",
            probed=True,
            reason=result.reason,
            details=dict(result.evidence),
        )

    # ------------------------------------------------------------ synthesis
    def synthesize(self, request_: TTSRequest) -> TTSResponse:
        endpoint = join_url(self.base_url, "/audio/speech")
        started = time.perf_counter()
        payload = {
            "model": self.model,
            "input": request_.text,
            "voice": request_.voice or self.default_voice,
            "response_format": FORMAT_TO_REQUEST.get(request_.output_format, "wav"),
        }
        if request_.speed is not None:
            # The reference API accepts 0.25–4.0. Clamp rather than get a 400.
            payload["speed"] = max(0.25, min(4.0, float(request_.speed)))

        response = request(
            endpoint,
            method="POST",
            json_body=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
            retries=0,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if response.status == 429:
            raise ProviderTimeout(
                "TTS endpoint rate limited (429)", provider=self.id, fallback="sapi"
            )
        if not response.ok or not response.body:
            # `response.error` never contains the key: it is a header, not a URL.
            raise ProviderUnavailable(
                f"TTS endpoint failed: {response.error}", provider=self.id, fallback="sapi"
            )

        output = Path(request_.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(response.body)
        duration = wav_duration(output)
        return TTSResponse(
            provider=self.id,
            audio_path=str(output),
            duration_sec=duration,
            artifacts={"audio": str(output)},
            metrics={
                "wall_seconds": round(elapsed_ms / 1000, 3),
                "model": self.model,
                "voice": payload["voice"],
                "format": payload["response_format"],
                "key": self.masked_key,
            },
        )

    def synthesize_rich(self, request_: TTSRequest) -> TTSResult:
        unsupported = [
            name for name in sorted(request_.requested_features())
            if name in {"emotion", "style", "pitch", "volume", "emphasis",
                        "seed", "pronunciation"}
        ]
        started = time.perf_counter()
        legacy = self.synthesize(request_)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        duration_ms = int((legacy.duration_sec or 0) * 1000) or None
        return TTSResult(
            ok=True,
            audio_path=legacy.audio_path,
            duration_ms=duration_ms,
            sample_rate=24000,
            channels=1,
            provider=self.id,
            model=self.model,
            voice=legacy.metrics.get("voice"),
            generation_time_ms=elapsed_ms,
            realtime_factor=round(elapsed_ms / duration_ms, 3) if duration_ms else None,
            output_format=request_.output_format,
            unsupported_fields=unsupported,
            metadata={"key": self.masked_key, "base_url": self.base_url},
        )
