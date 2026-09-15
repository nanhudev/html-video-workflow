"""MockTTS — deterministic placeholder audio for CI and smoke tests.

It never pretends to be speech: the artifact is a quiet tone whose length
matches the estimated narration length, and the response is flagged mock.
"""
from __future__ import annotations

from pathlib import Path

from ...utils.audio import estimate_speech_seconds, wav_duration, write_tone_wav
from ..base import (
    ProbeResult,
    ProbeState,
    ProviderSpec,
    TTSProvider,
    TTSRequest,
    TTSResponse,
    VoiceType,
)
from ..registry import register


@register
class MockTTSProvider(TTSProvider):
    spec = ProviderSpec(
        id="mock_tts",
        type="tts",
        name="Mock TTS",
        vendor="html-video-workflow",
        version="1.0.0",
        local=True,
        implementation="inprocess",
        languages=["zh-CN", "en-US", "ja-JP"],
        quality_score=0.0,
        speed_score=10.0,
        naturalness_score=0.0,
        startup_cost="low",
        install_state="builtin",
        voice_type=VoiceType.BUILT_IN,
        # ``low_fidelity`` keeps the mock in the routing pool as a guaranteed
        # last resort while letting quality-oriented presets rank it last. It is
        # still the first choice under ``fast``, which is where a placeholder
        # tone belongs — and a tone claiming naturalness would be a lie that
        # propagates straight into the router's ranking.
        tags=["mock", "ci", "fallback", "low_fidelity"],
    )

    def probe(self) -> ProbeResult:
        return ProbeResult(state=ProbeState.READY, reason="Always available (mock)")

    def synthesize(self, request: TTSRequest) -> TTSResponse:
        output = Path(request.output_path)
        estimated = estimate_speech_seconds(request.narration.text)
        write_tone_wav(output, seconds=estimated, frequency=170.0, amplitude=0.04)
        return TTSResponse(
            provider=self.id,
            audio_path=str(output),
            duration_sec=wav_duration(output),
            artifacts={"wav": str(output)},
            metrics={"mock": True, "estimated_seconds": round(estimated, 2)},
            message="Mock audio — not speech",
        )
