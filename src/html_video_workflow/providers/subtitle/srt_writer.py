"""SRT subtitle writer — first implementation of the Caption IR."""
from __future__ import annotations

from pathlib import Path

from ..base import ProbeResult, ProbeState, ProviderResult, ProviderSpec, SubtitleProvider
from ..registry import register


def format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:  # rounding guard
        secs += 1
        millis = 0
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


@register
class SRTSubtitleProvider(SubtitleProvider):
    spec = ProviderSpec(
        id="srt",
        type="subtitle",
        name="SRT Writer",
        vendor="html-video-workflow",
        version="1.0.0",
        local=True,
        implementation="inprocess",
        quality_score=7.0,
        speed_score=10.0,
        naturalness_score=7.0,
        startup_cost="low",
        install_state="builtin",
        tags=["caption", "srt"],
    )

    def probe(self) -> ProbeResult:
        return ProbeResult(state=ProbeState.READY, reason="Pure stdlib writer")

    def write(self, request: dict) -> ProviderResult:
        cues = request.get("cues") or []
        output = Path(request.get("output_path") or "subtitles.srt")
        output.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for index, cue in enumerate(cues, start=1):
            start = float(cue.get("start", 0))
            end = float(cue.get("end", start + 2))
            text = str(cue.get("text", "")).replace("\n", " ").strip()
            lines.append(f"{index}\n{format_timestamp(start)} --> {format_timestamp(end)}\n{text}\n")
        output.write_text("\n".join(lines), encoding="utf-8")
        return ProviderResult(
            provider=self.id,
            artifacts={"srt": str(output)},
            metrics={"cues": len(cues)},
        )
