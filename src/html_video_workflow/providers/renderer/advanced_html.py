"""AdvancedHTMLRenderer — consumes IR V2 directly.

This is the renderer Phase 2 exists for. The difference from `legacy_html` is
not cosmetic:

* `legacy_html` translated IR V2 **down** to the legacy template shape, then
  rendered that. Every layer's per-layer timing and motion semantics were lost in
  the translation, because the intermediate shape has nowhere to keep them.
* this renderer feeds the IR V2 scene straight into `SceneCompiler`, so the
  nine motion primitives, nine layouts, safe areas and the type system all
  survive to the screen.

`legacy_html` is retained and remains the fallback. If this renderer throws, the
runtime records the substitution and falls back — it never silently does nothing.
"""
from __future__ import annotations

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
    RenderFailed,
    RenderSceneRequest,
    RenderSceneResponse,
    RendererProvider,
)
from ..registry import register
from ..renderer.themes import get_theme
from ...renderers.critic import SceneVariationPolicy, VisualDesignCritic
from ...renderers.scene_compiler import SceneCompiler
from ...renderers.service import BrowserRenderService, RenderRequest

log = get_logger("providers.renderer.advanced_html")


def _resolve_browser():
    """Looked up per call, so a repointed/removed browser is noticed."""
    return _hw_profile.resolve_browser()


def _duration_ms(request: RenderSceneRequest) -> float:
    scene = request.scene or {}
    if scene.get("duration_hint_sec"):
        return float(scene["duration_hint_sec"]) * 1000.0
    narration = scene.get("narration") or {}
    text = str(narration.get("text") or "")
    if text:
        # ~4.6 CJK chars/sec is the project's existing speech estimate; doubled
        # here because a scene usually needs room to breathe either side.
        return max(1200.0, len(text) / 4.6 * 1000.0 * 1.15)
    return 4000.0


@register
class AdvancedHTMLRenderer(RendererProvider):
    spec = ProviderSpec(
        id="advanced_html",
        type="renderer",
        name="Advanced HTML Renderer",
        vendor="html-video-workflow",
        version="1.0.0",
        local=True,
        implementation="subprocess",
        quality_score=8.5,
        speed_score=7.0,
        naturalness_score=8.0,
        startup_cost="low",
        install_state="builtin",
        tags=["html", "css", "deterministic", "ir-v2"],
    )

    def __init__(self) -> None:
        self._service = BrowserRenderService()
        self._variation = SceneVariationPolicy()
        self._critic = VisualDesignCritic()

    # ------------------------------------------------------------- probing
    def probe(self) -> ProbeResult:
        browser = _resolve_browser()
        if not browser.available:
            return ProbeResult(
                state=ProbeState.NOT_INSTALLED,
                reason="No Chromium-compatible browser found (advanced renderer cannot run)",
                evidence={"searched": ["msedge", "chrome", "chromium"]},
            )
        return ProbeResult(
            state=ProbeState.READY,
            reason=f"Browser found: {browser.name} @ {browser.path}",
            evidence={"browser": browser.name, "path": browser.path,
                      "backend": self._service.backend},
        )

    def capabilities(self):  # noqa: D102 - extends base with renderer metadata
        capability = super().capabilities()
        from ...renderers.layout import supported_layouts
        from ...renderers.motion import supported_motions

        capability.details["motions"] = supported_motions()
        capability.details["layouts"] = supported_layouts()
        capability.details["consumes"] = "ir-v2-direct"
        capability.details["backend"] = self._service.backend
        return capability

    # ------------------------------------------------------------ rendering
    def render_scene(self, request: RenderSceneRequest) -> RenderSceneResponse:
        browser = _resolve_browser()
        if not browser.available or not browser.path:
            raise ProviderNotInstalled(
                "No Chromium-compatible browser available for HTML rendering",
                provider=self.id,
                fallback="legacy_html",
            )

        out_dir = Path(request.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        theme = get_theme(request.theme)
        scene = request.scene or {}

        compiler = SceneCompiler(theme, variation_policy=self._variation)
        compiled = compiler.compile(
            scene,
            meta=request.project_meta or {},
            assets=(request.project_meta or {}).get("assets"),
            width=request.width,
            height=request.height,
            index=request.index,
            total=request.total,
            scene_duration_ms=_duration_ms(request),
            output_preset=str((request.project_meta or {}).get("output_preset")
                              or "youtube_16x9"),
            project_id=str((request.project_meta or {}).get("project_id") or ""),
        )

        html_path = out_dir / f"scene-{request.index:03d}.html"
        html_path.write_text(compiled.html, encoding="utf-8")
        # The pipeline addresses frames by this exact name (`stage_render` builds
        # the same path independently), so writing anything else would leave the
        # stage looking at a file that was never created.
        png_path = out_dir / f"scene-{request.index:03d}.png"

        result = self._service.render(
            RenderRequest(
                html_path=str(html_path),
                out_dir=str(out_dir),
                width=request.width,
                height=request.height,
                strategy="screenshot",
                image_path=str(png_path),
            )
        )
        if not result.ok or not result.images:
            raise RenderFailed(
                f"advanced render produced no image: {result.reason}",
                provider=self.id,
                fallback="legacy_html",
            )
        if not png_path.exists() or png_path.stat().st_size == 0:
            raise RenderFailed(
                f"advanced render wrote nothing to {png_path}",
                provider=self.id,
                fallback="legacy_html",
            )

        critique = self._critic.review(compiled.facts)
        metrics: dict[str, Any] = {
            "seconds": result.seconds,
            "layout": str(compiled.layout.name),
            "theme": theme.id,
            "motion_ms": round(compiled.total_motion_ms, 1),
            "motions": sorted({i.name for i in compiled.timing.instances}),
            "warnings": len(critique.findings),
            "errors": len(critique.errors),
            "safe_area_breaches": len(compiled.facts.safe_area_breaches),
        }
        # Findings ride along in the response rather than being raised: a frame
        # with a warning is still the frame the user asked for, and refusing to
        # render over a style opinion would be absurd.
        if critique.findings:
            metrics["findings"] = [f.to_dict() for f in critique.findings]
        if compiled.notes:
            metrics["notes"] = compiled.notes

        return RenderSceneResponse(
            provider=self.id,
            image_path=str(png_path),
            artifacts={"html": str(html_path), "png": str(png_path)},
            metrics=metrics,
            message=compiled.layout.reason[-1] if compiled.layout.reason else None,
        )

    # ---------------------------------------------------------------- APIs
    def compile_only(self, request: RenderSceneRequest) -> dict[str, Any]:
        """Compile without rendering — powers Studio's scene preview.

        Preview must be cheap and must not require a successful browser call to
        return something useful; returning HTML lets the Studio render it in an
        iframe with live animation instead of shipping a static PNG.
        """
        theme = get_theme(request.theme)
        compiler = SceneCompiler(theme)
        compiled = compiler.compile(
            request.scene or {},
            meta=request.project_meta or {},
            width=request.width,
            height=request.height,
            index=request.index,
            total=request.total,
            scene_duration_ms=_duration_ms(request),
        )
        critique = self._critic.review(compiled.facts)
        return {
            "html": compiled.html,
            "layout": str(compiled.layout.name),
            "layout_reason": compiled.layout.reason,
            "timing": [
                {
                    "motion": instance.name,
                    "start_ms": round(instance.start_ms, 1),
                    "end_ms": round(instance.end_ms, 1),
                    "reason": instance.reason,
                }
                for instance in compiled.timing.instances
            ],
            "findings": [f.to_dict() for f in critique.findings],
            "notes": compiled.notes,
        }
