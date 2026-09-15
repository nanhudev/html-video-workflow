"""AivisSpeech adapter — VOICEVOX-compatible HTTP engine.

``AivisSpeech`` ships the same HTTP surface as VOICEVOX (``/engine_manifest``,
``/speakers``, ``/audio_query``, ``/synthesis``), so this adapter works against
either. It is an **HTTP adapter only**: the core never imports engine internals,
never loads an ONNX model, and needs no GPU.

When the engine is not running this provider reports ``unavailable`` with the
connection error attached — it does not raise, and it does not pretend to be
ready. That distinction is what lets the router fall through to SAPI at 3 a.m.
on a machine where nobody started the engine.

Configuration (``HVW_`` env prefix, or ``providers.aivisspeech`` in settings):

===========================  ==========================================
``HVW_AIVIS_BASE_URL``       engine root, default ``http://127.0.0.1:10101``
``HVW_AIVIS_SPEAKER``        style id, default ``888753760``
``HVW_AIVIS_TIMEOUT``        per-request seconds, default ``60``
===========================  ==========================================
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
from .http_client import HttpResult, join_url, request

log = get_logger("providers.tts.aivisspeech")

DEFAULT_BASE_URL = "http://127.0.0.1:10101"
DEFAULT_SPEAKER = 888753760  # AivisSpeech "Anneli" default style in VOICEVOX ids
DEFAULT_TIMEOUT = 60.0


@register
class AivisSpeechProvider(TTSProvider):
    spec = ProviderSpec(
        id="aivisspeech",
        type="tts",
        name="AivisSpeech",
        vendor="Aivis Project",
        version="1.0.0",
        local=True,
        implementation="http",
        languages=["ja-JP"],
        quality_score=8.0,
        speed_score=7.0,
        naturalness_score=8.5,
        startup_cost="medium",
        estimated_ram_mb=2048,
        install_state="optional",
        install_docs="https://github.com/Aivis-Project/AivisSpeech-Engine",
        voice_type=VoiceType.BUILT_IN,
        tags=["neural", "http", "voicevox-compatible", "japanese"],
    )

    # -------------------------------------------------------------- config
    @property
    def base_url(self) -> str:
        return os.environ.get("HVW_AIVIS_BASE_URL", "").strip() or DEFAULT_BASE_URL

    @property
    def timeout(self) -> float:
        raw = os.environ.get("HVW_AIVIS_TIMEOUT", "").strip()
        try:
            return float(raw) if raw else DEFAULT_TIMEOUT
        except ValueError:
            return DEFAULT_TIMEOUT

    @property
    def default_speaker(self) -> int:
        raw = os.environ.get("HVW_AIVIS_SPEAKER", "").strip()
        try:
            return int(raw) if raw else DEFAULT_SPEAKER
        except ValueError:
            return DEFAULT_SPEAKER

    # ------------------------------------------------------------- probing
    def _manifest(self) -> HttpResult:
        return request(
            join_url(self.base_url, "/engine_manifest"),
            timeout=min(self.timeout, 5.0),
            retries=0,
        )

    def probe(self) -> ProbeResult:
        manifest = self._manifest()
        if not manifest.ok:
            return ProbeResult(
                state=ProbeState.UNAVAILABLE,
                reason=f"Engine not reachable at {self.base_url} ({manifest.error})",
                evidence={"base_url": self.base_url, "error": manifest.error},
            )
        data = manifest.json() or {}
        speakers = self._raw_speakers()
        styles = sum(len(s.get("styles", [])) for s in speakers)
        return ProbeResult(
            state=ProbeState.READY,
            reason=f"AivisSpeech {data.get('brand_name', 'engine')} "
                   f"{data.get('engine_version', '?')} — {styles} styles",
            evidence={
                "base_url": self.base_url,
                "engine_version": data.get("engine_version"),
                "brand_name": data.get("brand_name"),
                "styles": styles,
                "speakers": len(speakers),
            },
        )

    def _raw_speakers(self) -> list[dict]:
        result = request(
            join_url(self.base_url, "/speakers"),
            timeout=min(self.timeout, 10.0),
            retries=0,
        )
        if not result.ok:
            return []
        data = result.json()
        return data if isinstance(data, list) else []

    def list_voices(self) -> list[VoiceInfo]:
        voices: list[VoiceInfo] = []
        for speaker in self._raw_speakers():
            name = speaker.get("name") or "unknown"
            for style in speaker.get("styles", []):
                style_name = style.get("name") or ""
                voices.append(
                    VoiceInfo(
                        id=str(style.get("id", "")),
                        name=f"{name} / {style_name}".strip(" /"),
                        language="ja-JP",
                        gender=speaker.get("speaker_uuid") and None,
                    )
                )
        return voices

    def voice_descriptors(self) -> list[VoiceDescriptor]:
        out: list[VoiceDescriptor] = []
        for speaker in self._raw_speakers():
            name = speaker.get("name") or "unknown"
            for style in speaker.get("styles", []):
                out.append(
                    VoiceDescriptor(
                        id=str(style.get("id", "")),
                        name=f"{name} / {style.get('name', '')}".strip(" /"),
                        language="ja-JP",
                        styles=[style.get("name") or ""],
                        license_notes=str(speaker.get("policy") or "") or None,
                    )
                )
        return out

    def descriptor(self) -> TTSProviderDescriptor:
        result = self.probe()
        voices = self.list_voices() if result.available else []
        return TTSProviderDescriptor(
            id=self.spec.id,
            name=self.spec.name,
            vendor=self.spec.vendor,
            version=self.spec.version,
            implementation="http",
            installed=CapabilityFlag.YES,
            available=CapabilityFlag.YES if result.available else CapabilityFlag.NO,
            local=True,
            languages=["ja-JP"],
            voices=[v.name for v in voices],
            voice_count=len(voices) if result.available else None,
            supports_emotion=CapabilityFlag.NO,
            supports_style=CapabilityFlag.YES,
            supports_voice_clone=CapabilityFlag.UNKNOWN,
            supports_streaming=CapabilityFlag.YES,
            supports_speed=CapabilityFlag.YES,
            supports_pitch=CapabilityFlag.YES,
            supports_emphasis=CapabilityFlag.YES,
            supports_ssml=CapabilityFlag.NO,
            supported_formats=["wav"],
            requires_gpu=GPURequirement.OPTIONAL,
            gpu_backends=["cpu", "cuda", "directml"],
            minimum_vram_mb=0,
            recommended_vram_mb=2048,
            estimated_download_mb=1500,
            estimated_ram_mb=2048,
            quality_tier=QualityTier.HIGH,
            quality_score=self.spec.quality_score,
            speed_score=self.spec.speed_score,
            naturalness_score=self.spec.naturalness_score,
            startup_cost="medium",
            estimated_realtime_factor=0.6,
            license_notes="Engine MIT; individual model licences vary by speaker.",
            probed=True,
            reason=result.reason,
            details=dict(result.evidence),
        )

    # ------------------------------------------------------------ synthesis
    def synthesize(self, request_: TTSRequest) -> TTSResponse:
        started = time.perf_counter()
        speaker = self._speaker_id(request_)

        query = request(
            join_url(self.base_url, "/audio_query"),
            method="POST",
            json_body={"text": request_.text, "speaker": speaker},
            timeout=self.timeout,
            retries=0,
        )
        if not query.ok:
            raise ProviderUnavailable(
                f"AivisSpeech audio_query failed: {query.error}",
                provider=self.id,
                fallback="sapi",
            )
        payload = query.json() or {}
        self._apply_controls(payload, request_)

        output = Path(request_.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        synth_url = join_url(self.base_url, "/synthesis")
        synth_url = f"{synth_url}?speaker={speaker}"
        audio = request(
            synth_url,
            method="POST",
            json_body=payload,
            headers={"Accept": "audio/wav"},
            timeout=self.timeout,
            retries=0,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if not audio.ok or not audio.body:
            raise ProviderUnavailable(
                f"AivisSpeech synthesis failed: {audio.error}",
                provider=self.id,
                fallback="sapi",
            )
        output.write_bytes(audio.body)
        duration = wav_duration(output)
        return TTSResponse(
            provider=self.id,
            audio_path=str(output),
            duration_sec=duration,
            artifacts={"wav": str(output)},
            metrics={
                "wall_seconds": round(elapsed_ms / 1000, 3),
                "speaker": speaker,
                "engine": self.base_url,
            },
        )

    def synthesize_rich(self, request_: TTSRequest) -> TTSResult:
        """Contract-shaped synthesis, reporting fields the engine cannot honour."""
        started = time.perf_counter()
        unsupported = [
            name for name in sorted(request_.requested_features())
            if name in {"emotion", "style", "volume", "seed", "pronunciation"}
        ]
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
            model="aivisspeech-engine",
            voice=str(self._speaker_id(request_)),
            generation_time_ms=elapsed_ms,
            realtime_factor=(
                round(elapsed_ms / duration_ms, 3) if duration_ms else None
            ),
            output_format=AudioFormat.WAV,
            unsupported_fields=unsupported,
            metadata=dict(legacy.metrics),
        )

    # ---------------------------------------------------------------- bits
    def _speaker_id(self, request_: TTSRequest) -> int:
        for candidate in (request_.voice, request_.speaker):
            if candidate is None:
                continue
            try:
                return int(candidate)
            except (TypeError, ValueError):
                continue
        return self.default_speaker

    def _apply_controls(self, payload: dict, request_: TTSRequest) -> None:
        """Map request fields onto VOICEVOX audio_query parameters in place."""
        if request_.speed is not None:
            payload["speedScale"] = float(request_.speed)
        if request_.pitch is not None:
            payload["pitchScale"] = float(request_.pitch) / 12.0
        if request_.volume is not None:
            payload["volumeScale"] = max(0.0, float(request_.volume))
        if request_.emphasis and isinstance(payload.get("accent_phrases"), list):
            self._apply_emphasis(payload["accent_phrases"], request_.emphasis)
        if request_.pause_before_ms or request_.pause_after_ms:
            payload["prePhonemeLength"] = max(
                float(payload.get("prePhonemeLength") or 0.1),
                request_.pause_before_ms / 1000.0,
            )
            payload["postPhonemeLength"] = max(
                float(payload.get("postPhonemeLength") or 0.1),
                request_.pause_after_ms / 1000.0,
            )

    @staticmethod
    def _apply_emphasis(phrases: list[dict], emphasis: list[str]) -> None:
        """Raise the accent on mora whose text appears in an emphasised token.

        VOICEVOX has no SSML, so emphasis is expressed the only way the engine
        understands: marking the mora's accent. The match is by character
        containment and is intentionally conservative — a false positive bends
        the pitch slightly, which is recoverable, whereas inventing emphasis on
        an unrelated word is not.
        """
        needles = [e for e in emphasis if e]
        if not needles:
            return
        for phrase in phrases:
            for mora in phrase.get("moras", []):
                text = str(mora.get("text") or "")
                if any(needle in text for needle in needles):
                    mora["pitch"] = max(5.5, float(mora.get("pitch") or 0.0) + 0.35)
            accent = phrase.get("accent")
            if isinstance(accent, int):
                phrase["accent"] = max(1, accent)


UTTERANCE_ENDPOINT_NOTE = (
    "AivisSpeech exposes /audio_query (POST) then /synthesis (POST). "
    "Both are required; the query carries prosody, the synthesis carries audio."
)
