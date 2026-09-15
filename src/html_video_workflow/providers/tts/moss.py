"""MOSS-TTS-Nano provider — the original local neural narration engine.

The binary is optional. When it is missing the provider reports
``not_installed`` instead of pretending to work.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from ...utils.audio import wav_duration
from ...utils.logging import get_logger
from ..base import (
    ProbeResult,
    ProbeState,
    ProviderNotInstalled,
    ProviderSpec,
    ProviderTimeout,
    TTSProvider,
    TTSRequest,
    TTSResponse,
    VoiceType,
)
from ..registry import register

log = get_logger("providers.tts.moss")

DEFAULT_COMMAND = "moss-tts-nano"


@register
class MOSSProvider(TTSProvider):
    spec = ProviderSpec(
        id="moss",
        type="tts",
        name="MOSS-TTS-Nano",
        vendor="OpenMOSS",
        version="1.0.0",
        local=True,
        implementation="subprocess",
        languages=["zh-CN", "en-US"],
        quality_score=7.0,
        speed_score=6.0,
        naturalness_score=7.5,
        startup_cost="medium",
        estimated_ram_mb=2048,
        requires_binary=[DEFAULT_COMMAND],
        install_state="manual",
        install_docs="Install moss-tts-nano and ensure it is on PATH.",
        voice_type=VoiceType.BUILT_IN,
        tags=["local", "neural", "clone-capable"],
    )

    def _command(self) -> str:
        return os.environ.get("MOSS_TTS_COMMAND", DEFAULT_COMMAND)

    def probe(self) -> ProbeResult:
        command = self._command()
        path = shutil.which(command)
        if not path:
            return ProbeResult(
                state=ProbeState.NOT_INSTALLED,
                reason=f"Binary not found on PATH: {command}",
                evidence={"command": command},
            )
        return ProbeResult(
            state=ProbeState.READY,
            reason=f"MOSS binary found at {path}",
            evidence={"path": path, "command": command},
        )

    def synthesize(self, request: TTSRequest) -> TTSResponse:
        command = self._command()
        if not shutil.which(command):
            raise ProviderNotInstalled(
                f"MOSS binary not installed: {command}",
                provider=self.id,
                fallback="sapi",
            )
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        text_path = output.with_suffix(".txt")
        text_path.write_text(request.narration.text, encoding="utf-8")

        options = self.spec.license.notes  # placeholder for future per-project config
        cmd = [
            command,
            "generate",
            "--backend", "onnx",
            "--text-file", str(text_path),
            "--output", str(output),
            "--execution-provider", "cpu",
            "--cpu-threads", str(max(2, (os.cpu_count() or 4) // 2)),
        ]
        voice = request.narration.voice or "Junhao"
        cmd += ["--voice", voice]

        started = time.perf_counter()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=600)
        except subprocess.TimeoutExpired as exc:
            raise ProviderTimeout(
                "MOSS synthesis timed out", provider=self.id, fallback="sapi"
            ) from exc
        elapsed = time.perf_counter() - started
        if result.returncode != 0 or not output.exists():
            raise ProviderNotInstalled(
                f"MOSS synthesis failed: {(result.stderr or '').strip()[:300]}",
                provider=self.id,
                fallback="sapi",
            )
        duration = wav_duration(output)
        return TTSResponse(
            provider=self.id,
            audio_path=str(output),
            duration_sec=duration,
            artifacts={"wav": str(output), "txt": str(text_path)},
            metrics={"wall_seconds": round(elapsed, 3), "voice": voice, "options": bool(options)},
        )
