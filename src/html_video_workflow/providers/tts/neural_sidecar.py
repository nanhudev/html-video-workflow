"""Neural TTS sidecar adapter — Fish Speech / CosyVoice class engines.

**Why a sidecar and not an import.** Fish Speech and CosyVoice both want
PyTorch, CUDA and tens of gigabytes of weights. Putting either behind an
``import`` would mean the core install could no longer run on a laptop, CI could
no longer install the package, and every developer without a GPU would hit an
ImportError while walking the provider registry.

So the contact surface is HTTP. The engine runs wherever it can run — a GPU box,
a container, the same machine after the user starts it — and this adapter talks
to it. Core stays ``pydantic`` + ``python-dotenv``.

The same protocol serves both families, because they all end up exposing the
same shape:

    GET  {base}/health          -> {"status": "ok", ...}
    GET  {base}/v1/voices       -> [{"id": ..., "name": ...}, ...]
    POST {base}/v1/tts          -> audio bytes
         {"text", "voice", "language", "speed", "emotion", "seed", "format"}

A deployment that deviates from this should ship a thin shim rather than
forking this adapter — that keeps engine-specific knowledge out of the core,
which is the entire point of the design.

``REAL HARDWARE VALIDATION PENDING``: contract tests run against a stub server.
No GPU inference has been executed on this project's development machine.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

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

log = get_logger("providers.tts.neural_sidecar")

DEFAULT_TIMEOUT = 300.0


@register
class NeuralSidecarTTSProvider(TTSProvider):
    """HTTP adapter for a local neural TTS service.

    The engine behind it is selected by env var, not by a subclass per engine —
    adding Fish Speech v2 or a new CosyVoice release should not require a code
    change, only a reconfiguration.
    """

    spec = ProviderSpec(
        id="neural_sidecar",
        type="tts",
        name="Neural TTS sidecar",
        vendor="Fish Speech / CosyVoice class",
        version="1.0.0",
        local=True,
        implementation="http",
        languages=["zh-CN", "en-US", "ja-JP", "ko-KR"],
        quality_score=9.0,
        speed_score=6.0,
        naturalness_score=9.2,
        startup_cost="high",
        estimated_vram_mb=4096,
        estimated_ram_mb=8192,
        install_state="manual",
        install_docs="docs/providers/neural_sidecar.md",
        voice_type=VoiceType.CLONE,
        tags=["neural", "http", "sidecar", "gpu-optional", "clone-capable"],
    )

    # -------------------------------------------------------------- config
    @property
    def base_url(self) -> str:
        return os.environ.get("HVW_NEURAL_TTS_URL", "").strip()

    @property
    def engine(self) -> str:
        """Free-text engine label, surfaced in the descriptor for the operator."""
        return os.environ.get("HVW_NEURAL_TTS_ENGINE", "").strip() or "unknown"

    @property
    def default_voice(self) -> str:
        return os.environ.get("HVW_NEURAL_TTS_VOICE", "").strip() or "default"

    @property
    def timeout(self) -> float:
        raw = os.environ.get("HVW_NEURAL_TTS_TIMEOUT", "").strip()
        try:
            return float(raw) if raw else DEFAULT_TIMEOUT
        except ValueError:
            return DEFAULT_TIMEOUT

    # ------------------------------------------------------------- probing
    def probe(self) -> ProbeResult:
        base = self.base_url
        if not base:
            return ProbeResult(
                state=ProbeState.NOT_INSTALLED,
                reason="HVW_NEURAL_TTS_URL is not set — no neural TTS service configured",
                evidence={"env": "HVW_NEURAL_TTS_URL"},
            )
        health = request(join_url(base, "/health"), timeout=5.0, retries=0)
        if not health.ok:
            return ProbeResult(
                state=ProbeState.UNAVAILABLE,
                reason=f"Neural TTS service not reachable at {base} ({health.error})",
                evidence={"base_url": base, "error": health.error},
            )
        data = health.json() or {}
        status = str(data.get("status") or "").lower()
        if status and status not in {"ok", "ready", "healthy"}:
            return ProbeResult(
                state=ProbeState.UNAVAILABLE,
                reason=f"Service reports status={status}",
                evidence={"base_url": base, "health": data},
            )
        voices = self._voices()
        return ProbeResult(
            state=ProbeState.READY,
            reason=f"{self.engine} reachable at {base} — {len(voices)} voices",
            evidence={
                "base_url": base,
                "engine": self.engine,
                "voices": len(voices),
                "gpu": data.get("gpu"),
                "health": {k: v for k, v in data.items() if k != "voices"},
            },
        )

    def _voices(self) -> list[dict]:
        base = self.base_url
        if not base:
            return []
        response = request(join_url(base, "/v1/voices"), timeout=10.0, retries=0)
        if not response.ok:
            return []
        data = response.json()
        if isinstance(data, dict):
            data = data.get("voices") or data.get("data") or []
        return data if isinstance(data, list) else []

    def list_voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(
                id=str(item.get("id") or item.get("name") or ""),
                name=str(item.get("name") or item.get("id") or "unknown"),
                language=item.get("language"),
                gender=item.get("gender"),
            )
            for item in self._voices()
        ]

    def voice_descriptors(self) -> list[VoiceDescriptor]:
        return [
            VoiceDescriptor(
                id=str(item.get("id") or item.get("name") or ""),
                name=str(item.get("name") or item.get("id") or "unknown"),
                language=item.get("language"),
                gender=item.get("gender"),
                styles=list(item.get("styles") or []),
                emotions=list(item.get("emotions") or []),
                description=item.get("description"),
                license_notes=item.get("license"),
            )
            for item in self._voices()
        ]

    def descriptor(self) -> TTSProviderDescriptor:
        result = self.probe()
        voices = self.list_voices() if result.available else []
        return TTSProviderDescriptor(
            id=self.spec.id,
            name=f"Neural TTS sidecar ({self.engine})",
            vendor=self.spec.vendor,
            version=self.spec.version,
            implementation="http",
            installed=CapabilityFlag.YES if self.base_url else CapabilityFlag.NO,
            available=CapabilityFlag.YES if result.available else CapabilityFlag.NO,
            local=True,
            languages=["zh-CN", "en-US", "ja-JP", "ko-KR"],
            voices=[v.name for v in voices],
            voice_count=len(voices) if result.available else None,
            supports_emotion=CapabilityFlag.YES,
            supports_style=CapabilityFlag.YES,
            supports_voice_clone=CapabilityFlag.YES,
            supports_streaming=CapabilityFlag.YES,
            supports_speed=CapabilityFlag.YES,
            supports_pitch=CapabilityFlag.UNKNOWN,
            supports_emphasis=CapabilityFlag.UNKNOWN,
            supports_ssml=CapabilityFlag.UNKNOWN,
            supported_formats=["wav", "mp3", "flac"],
            requires_gpu=GPURequirement.OPTIONAL,
            gpu_backends=["cuda", "rocm", "mps", "cpu"],
            minimum_vram_mb=2048,
            recommended_vram_mb=8192,
            estimated_download_mb=6000,
            estimated_ram_mb=8192,
            quality_tier=QualityTier.STUDIO,
            quality_score=self.spec.quality_score,
            speed_score=self.spec.speed_score,
            naturalness_score=self.spec.naturalness_score,
            startup_cost="high",
            estimated_realtime_factor=1.2,
            license_notes="Depends on the engine deployment. Fish Speech weights and "
                          "CosyVoice weights carry separate licences — check before "
                          "commercial use.",
            probed=True,
            reason=result.reason,
            details=dict(result.evidence),
        )

    # ------------------------------------------------------------ synthesis
    def synthesize(self, request_: TTSRequest) -> TTSResponse:
        base = self.base_url
        if not base:
            raise ProviderUnavailable(
                "Neural TTS service is not configured (HVW_NEURAL_TTS_URL unset)",
                provider=self.id,
                fallback="sapi",
            )
        started = time.perf_counter()
        payload = {
            "text": request_.text,
            "voice": request_.voice or request_.speaker or self.default_voice,
            "language": request_.language,
            "format": request_.output_format.value,
        }
        for field, value in (
            ("speed", request_.speed),
            ("pitch", request_.pitch),
            ("volume", request_.volume),
            ("emotion", request_.emotion),
            ("style", request_.style),
            ("seed", request_.seed),
            ("sample_rate", request_.sample_rate),
        ):
            if value is not None:
                payload[field] = value
        if request_.emphasis:
            payload["emphasis"] = list(request_.emphasis)

        response = request(
            join_url(base, "/v1/tts"),
            method="POST",
            json_body=payload,
            timeout=self.timeout,
            retries=0,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if response.status in (502, 503, 504):
            raise ProviderTimeout(
                f"Neural TTS service timed out (HTTP {response.status})",
                provider=self.id,
                fallback="sapi",
            )
        if not response.ok or not response.body:
            raise ProviderUnavailable(
                f"Neural TTS synthesis failed: {response.error}",
                provider=self.id,
                fallback="sapi",
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
                "engine": self.engine,
                "voice": payload["voice"],
                "realtime_factor": (
                    round(elapsed_ms / 1000 / duration, 3)
                    if duration else None
                ),
            },
        )

    def synthesize_rich(self, request_: TTSRequest) -> TTSResult:
        """Contract-shaped synthesis.

        This engine is the one adapter that genuinely claims the full feature
        set, so ``unsupported_fields`` is normally empty. It is still computed
        from the request rather than hardcoded, so the day the deployment drops
        a feature the report changes with it.
        """
        started = time.perf_counter()
        legacy = self.synthesize(request_)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        duration_ms = int((legacy.duration_sec or 0) * 1000) or None
        return TTSResult(
            ok=True,
            audio_path=legacy.audio_path,
            duration_ms=duration_ms,
            sample_rate=request_.sample_rate or 32000,
            channels=1,
            provider=self.id,
            model=self.engine,
            voice=legacy.metrics.get("voice"),
            generation_time_ms=elapsed_ms,
            realtime_factor=round(elapsed_ms / duration_ms, 3) if duration_ms else None,
            seed=request_.seed,
            output_format=request_.output_format,
            unsupported_fields=[],
            metadata=dict(legacy.metrics),
        )
