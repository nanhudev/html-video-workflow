"""LegacyHTMLRenderer — headless-Chromium screenshot renderer.

It wraps the original `scripts/workflow.py` rendering approach (one HTML page
per scene → PNG) but reads the renderer-neutral IR instead of a fixed template.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from ...hardware import profile as _hw_profile
from ...utils.logging import get_logger
from ..base import (
    ProbeResult,
    ProbeState,
    ProviderNotInstalled,
    ProviderSpec,
    ProviderTimeout,
    RenderFailed,
    RenderSceneRequest,
    RenderSceneResponse,
    RendererProvider,
)
from ..registry import register
from .document import build_scene_document
from .themes import get_theme

log = get_logger("providers.renderer.legacy_html")


def _resolve_browser():
    """Look up the browser at call time, not import time.

    Bound through the module so a caller (or a test) can repoint
    ``hardware.profile.resolve_browser`` and have this renderer notice. Importing
    the function directly would freeze the reference and silently ignore
    environment changes — the renderer would keep reporting "ready" after the
    browser was uninstalled.
    """
    return _hw_profile.resolve_browser()


@register
class LegacyHTMLRenderer(RendererProvider):
    spec = ProviderSpec(
        id="legacy_html",
        type="renderer",
        name="Legacy HTML Renderer",
        vendor="html-video-workflow",
        version="2.0.0",
        local=True,
        implementation="subprocess",
        quality_score=6.5,
        speed_score=8.0,
        naturalness_score=6.0,
        startup_cost="low",
        install_state="builtin",
        tags=["html", "css", "deterministic"],
    )

    # ------------------------------------------------------------- probing
    def probe(self) -> ProbeResult:
        browser = _resolve_browser()
        if not browser.available:
            return ProbeResult(
                state=ProbeState.NOT_INSTALLED,
                reason="No Chromium-compatible browser found (looked for Edge/Chrome/Chromium)",
                evidence={"searched": ["msedge", "chrome", "chromium"]},
            )
        return ProbeResult(
            state=ProbeState.READY,
            reason=f"Browser found: {browser.name} @ {browser.path}",
            evidence={"browser": browser.name, "path": browser.path,
                      "version": browser.version},
        )

    def capabilities(self):  # noqa: D102 - extends base with voices/themes
        capability = super().capabilities()
        capability.details.setdefault("themes", 10)
        capability.details["browser"] = _resolve_browser().name
        return capability

    # ------------------------------------------------------------ rendering
    def render_scene(self, request: RenderSceneRequest) -> RenderSceneResponse:
        browser = _resolve_browser()
        if not browser.available or not browser.path:
            raise ProviderNotInstalled(
                "No Chromium-compatible browser available for HTML rendering",
                provider=self.id,
                fallback="mock_renderer",
            )
        out_dir = Path(request.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        theme = get_theme(request.theme)
        document = build_scene_document(
            request.scene,
            theme,
            request.project_meta,
            width=request.width,
            height=request.height,
            index=request.index,
            total=request.total,
        )
        html_path = out_dir / f"scene-{request.index:03d}.html"
        png_path = out_dir / f"scene-{request.index:03d}.png"
        html_path.write_text(document, encoding="utf-8")

        cmd = [
            browser.path,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "--disable-lcd-text",
            f"--window-size={request.width},{request.height}",
            "--virtual-time-budget=2500",
            f"--screenshot={png_path.resolve()}",
            html_path.resolve().as_uri(),
        ]
        started = time.perf_counter()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=120)
        except subprocess.TimeoutExpired as exc:
            raise ProviderTimeout(
                f"Browser screenshot timed out after 120s for scene {request.index}",
                provider=self.id,
            ) from exc
        elapsed = time.perf_counter() - started
        if not png_path.exists() or png_path.stat().st_size == 0:
            raise RenderFailed(
                f"Browser did not produce a screenshot (rc={result.returncode}): "
                f"{(result.stderr or '').strip()[:300]}",
                provider=self.id,
                fallback="mock_renderer",
            )
        log.debug("rendered scene %s in %.2fs", request.index, elapsed)
        return RenderSceneResponse(
            provider=self.id,
            image_path=str(png_path),
            artifacts={"html": str(html_path), "png": str(png_path)},
            metrics={"seconds": round(elapsed, 3), "theme": theme.id},
        )

    def render_gallery(self, scene: dict[str, Any], out_dir: str,
                       meta: dict[str, Any] | None = None) -> list[dict[str, str]]:
        """Render one scene in every theme — the legacy `gallery` capability."""
        from .themes import theme_ids

        results: list[dict[str, str]] = []
        for position, name in enumerate(theme_ids(), start=1):
            response = self.render_scene(
                RenderSceneRequest(
                    scene=scene,
                    project_meta=meta or {},
                    theme=name,
                    out_dir=out_dir,
                    index=position,
                    total=len(theme_ids()),
                )
            )
            results.append({"theme": name, "image": response.image_path or ""})
        return results
