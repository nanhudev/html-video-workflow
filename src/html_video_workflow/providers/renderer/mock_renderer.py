"""MockRenderer — deterministic PNG output with no browser dependency.

Used by CI and as the last-resort fallback. It draws a labelled placeholder so a
missing browser can never be mistaken for a successful, designed frame.
"""
from __future__ import annotations

from pathlib import Path

from ..base import (
    ProbeResult,
    ProbeState,
    ProviderSpec,
    RenderSceneRequest,
    RenderSceneResponse,
    RendererProvider,
)
from ..registry import register


@register
class MockRenderer(RendererProvider):
    spec = ProviderSpec(
        id="mock_renderer",
        type="renderer",
        name="Mock Renderer",
        vendor="html-video-workflow",
        version="1.0.0",
        local=True,
        implementation="inprocess",
        quality_score=0.5,
        speed_score=10.0,
        naturalness_score=0.0,
        startup_cost="low",
        install_state="builtin",
        # A labelled grey placeholder is not a quality ceiling to route toward.
        # Without this the mock wins every high_quality round on its speed score
        # alone, and a preset that exists to buy rendering fidelity quietly
        # selects the one provider that has none.
        tags=["mock", "ci", "fallback", "low_fidelity"],
    )

    def probe(self) -> ProbeResult:
        return ProbeResult(state=ProbeState.READY, reason="Always available (mock)")

    def render_scene(self, request: RenderSceneRequest) -> RenderSceneResponse:
        out_dir = Path(request.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        png_path = out_dir / f"scene-{request.index:03d}.png"
        scene = request.scene or {}
        label = str(
            scene.get("title")
            or scene.get("intent")
            or (scene.get("narration", {}) or {}).get("text", "")[:24]
            or f"scene {request.index}"
        )
        _write_png(png_path, request.width, request.height, label)
        return RenderSceneResponse(
            provider=self.id,
            image_path=str(png_path),
            artifacts={"png": str(png_path)},
            metrics={"mock": True},
        )


def _write_png(path: Path, width: int, height: int, label: str) -> None:
    """Write a minimal valid PNG: flat grey canvas with a dark bar.

    Pure stdlib (zlib + struct) so CI never needs Pillow.
    """
    import struct
    import zlib

    row_bytes = bytearray()
    for y in range(height):
        band = 60 if (y // max(1, height // 12)) % 2 == 0 else 45
        row = bytearray([0])  # filter type 0
        for x in range(width):
            if height * 0.45 < y < height * 0.55:
                row += bytes((28, 32, 38))
            else:
                row += bytes((band, band + 2, band + 6))
        row_bytes += row

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(row_bytes), 6))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    # The label is exposed through a sibling text file so tests/CI can assert it.
    path.with_suffix(".txt").write_text(label, encoding="utf-8")
