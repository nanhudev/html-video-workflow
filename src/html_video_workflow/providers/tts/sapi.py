"""Windows SAPI narration — zero-download fallback TTS."""
from __future__ import annotations

import platform
import shutil
import subprocess
import time
from pathlib import Path

from ...config.paths import repo_root
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
    VoiceInfo,
    VoiceType,
)
from ..registry import register

log = get_logger("providers.tts.sapi")

SAPI_SCRIPT = repo_root() / "scripts" / "sapi_tts.ps1"

#: Installed voices, read once per process.
#:
#: Enumerating them spawns a PowerShell process, and `capabilities()` reaches the
#: enumeration through *both* `probe()` and `descriptor()` — while the router asks
#: for every candidate's capabilities before it can rank them. Routing one job was
#: starting dozens of shells: most of the planning latency, none of the
#: information, since the installed voice set cannot change while we run.
#:
#: Held at module scope rather than on the class because ``@register`` *replaces*
#: the class with a decorator object, so the name ``SAPIProvider`` no longer
#: refers to a type and `SAPIProvider._VOICE_CACHE` raises. That failure is
#: silent by design — the registry catches a broken capability probe and marks
#: the provider unavailable — which turned a caching mistake into "SAPI does not
#: exist on this machine".
_VOICE_CACHE: list["VoiceInfo"] | None = None


def reset_voice_cache() -> None:
    """Drop the memo. For tests, and for tooling that installs a voice."""
    global _VOICE_CACHE
    _VOICE_CACHE = None


@register
class SAPIProvider(TTSProvider):
    spec = ProviderSpec(
        id="sapi",
        type="tts",
        name="Windows SAPI",
        vendor="Microsoft",
        version="1.0.0",
        local=True,
        implementation="subprocess",
        languages=["zh-CN", "en-US"],
        quality_score=4.5,
        speed_score=9.0,
        naturalness_score=4.0,
        startup_cost="low",
        requires_os=["Windows"],
        install_state="builtin",
        voice_type=VoiceType.BUILT_IN,
        tags=["fallback", "offline", "windows"],
    )

    # ------------------------------------------------------------- probing
    def probe(self) -> ProbeResult:
        if platform.system() != "Windows":
            return ProbeResult(
                state=ProbeState.UNAVAILABLE,
                reason="SAPI requires Windows",
                evidence={"os": platform.system()},
            )
        if not SAPI_SCRIPT.exists():
            return ProbeResult(
                state=ProbeState.NOT_INSTALLED,
                reason=f"Missing helper script: {SAPI_SCRIPT}",
            )
        if not shutil.which("powershell"):
            return ProbeResult(
                state=ProbeState.UNAVAILABLE, reason="powershell.exe not found on PATH"
            )
        voices = self.list_voices()
        return ProbeResult(
            state=ProbeState.READY,
            reason=f"SAPI available with {len(voices)} voices",
            evidence={"voices": len(voices), "script": str(SAPI_SCRIPT)},
        )

    def capabilities(self):  # noqa: D102
        return super().capabilities()

    def _voices(self) -> list[VoiceInfo]:
        global _VOICE_CACHE
        if _VOICE_CACHE is not None:
            return _VOICE_CACHE
        if platform.system() != "Windows" or not shutil.which("powershell"):
            return []
        command = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.GetInstalledVoices() | ForEach-Object { "
            "$i = $_.VoiceInfo; $i.Name + '|' + $i.Culture + '|' + $i.Gender }"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=45,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        voices: list[VoiceInfo] = []
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            name, culture, gender = (line.split("|") + ["", ""])[:3]
            voices.append(
                VoiceInfo(id=name.strip(), name=name.strip(),
                          language=culture.strip() or None, gender=gender.strip() or None)
            )
        _VOICE_CACHE = voices
        return voices

    def list_voices(self) -> list[VoiceInfo]:
        return self._voices()

    def descriptor(self):  # noqa: D102 - TTSProviderDescriptor
        """Rich descriptor. SAPI is formant-era synthesis wearing a modern API.

        The honest summary is: it always works, it sounds robotic, and it can
        adjust rate and volume but nothing about *how* a sentence is delivered.
        Marking those as ``NO`` rather than ``UNKNOWN`` is deliberate — this
        provider has been probed, so "cannot" is a known fact, not an absence of
        information.
        """
        from .contract import (
            CapabilityFlag,
            GPURequirement,
            QualityTier,
            TTSProviderDescriptor,
        )

        result = self.probe()
        voices = self.list_voices() if result.available else []
        languages = sorted({v.language for v in voices if v.language}) or ["zh-CN", "en-US"]
        return TTSProviderDescriptor(
            id=self.spec.id,
            name=self.spec.name,
            vendor=self.spec.vendor,
            version=self.spec.version,
            implementation="subprocess",
            installed=CapabilityFlag.YES,
            available=CapabilityFlag.YES if result.available else CapabilityFlag.NO,
            local=True,
            languages=languages,
            voices=[v.name for v in voices],
            voice_count=len(voices) if result.available else None,
            supports_emotion=CapabilityFlag.NO,
            supports_style=CapabilityFlag.NO,
            supports_voice_clone=CapabilityFlag.NO,
            supports_streaming=CapabilityFlag.NO,
            supports_speed=CapabilityFlag.YES,
            supports_pitch=CapabilityFlag.NO,
            supports_emphasis=CapabilityFlag.NO,
            supports_ssml=CapabilityFlag.UNKNOWN,
            supported_formats=["wav"],
            requires_gpu=GPURequirement.NO,
            gpu_backends=[],
            minimum_vram_mb=0,
            recommended_vram_mb=0,
            estimated_download_mb=0,
            estimated_ram_mb=128,
            quality_tier=QualityTier.ROBOTIC,
            quality_score=4.5,
            speed_score=9.0,
            naturalness_score=4.0,
            startup_cost="low",
            estimated_realtime_factor=0.1,
            license_notes="Bundled with Windows; per-voice terms apply.",
            probed=True,
            reason=result.reason,
            details=dict(result.evidence),
        )

    def synthesize_rich(self, request: TTSRequest):
        """Contract-shaped synthesis reporting what this engine cannot honour."""
        import time

        from .contract import AudioFormat, TTSResult

        started = time.perf_counter()
        unsupported = [
            name
            for name in sorted(request.requested_features())
            if name in {"emotion", "style", "pitch", "volume", "emphasis",
                        "seed", "pronunciation"}
        ]
        legacy = self.synthesize(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        duration_ms = int((legacy.duration_sec or 0) * 1000) or None
        return TTSResult(
            ok=True,
            audio_path=legacy.audio_path,
            duration_ms=duration_ms,
            sample_rate=22050,
            channels=1,
            provider=self.id,
            model="sapi5",
            voice=request.voice,
            generation_time_ms=elapsed_ms,
            realtime_factor=round(elapsed_ms / duration_ms, 3) if duration_ms else None,
            output_format=AudioFormat.WAV,
            unsupported_fields=unsupported,
            metadata=dict(legacy.metrics),
        )

    # -------------------------------------------------------------- synth
    def synthesize(self, request: TTSRequest) -> TTSResponse:
        if platform.system() != "Windows":
            raise ProviderNotInstalled(
                "SAPI is only available on Windows", provider=self.id, fallback="mock_tts"
            )
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        text_path = output.with_suffix(".txt")
        text_path.write_text(request.narration.text, encoding="utf-8")

        voice = request.narration.voice or ""
        rate = request.narration.pace
        rate_value = 0
        if rate is not None:
            rate_value = max(-10, min(10, int(round((float(rate) - 1.0) * 10))))

        cmd = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SAPI_SCRIPT),
            "-TextFile",
            str(text_path),
            "-OutputFile",
            str(output),
        ]
        if voice:
            cmd += ["-Voice", voice]
        cmd += ["-Rate", str(rate_value)]

        started = time.perf_counter()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired as exc:
            raise ProviderTimeout(
                "SAPI synthesis timed out", provider=self.id, fallback="mock_tts"
            ) from exc
        elapsed = time.perf_counter() - started
        if result.returncode != 0 or not output.exists():
            raise ProviderNotInstalled(
                f"SAPI synthesis failed: {(result.stderr or result.stdout or '').strip()[:300]}",
                provider=self.id,
                fallback="mock_tts",
            )
        duration = wav_duration(output)
        log.debug("sapi synth %.2fs -> %.2fs audio", elapsed, duration or 0)
        return TTSResponse(
            provider=self.id,
            audio_path=str(output),
            duration_sec=duration,
            artifacts={"wav": str(output), "txt": str(text_path)},
            metrics={"wall_seconds": round(elapsed, 3), "voice": voice or "default"},
        )
