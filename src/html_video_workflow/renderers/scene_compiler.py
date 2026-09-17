"""SceneCompiler — IR V2 Scene → a standalone, deterministic HTML document.

This is the component that makes `advanced_html` genuinely *advanced* rather than
another template: it consumes IR V2 directly. The legacy path (**IR V2 → legacy
schema → legacy template**) necessarily discards every layer's motion semantics
and per-layer timing, because the intermediate schema has nowhere to put them.

Nothing in this module names a technology beyond HTML/CSS. No `class=`, no
`remotionComponent`, no framework — if a render target changes, this file does.
"""
from __future__ import annotations

import html as _html
from dataclasses import dataclass, field
from typing import Any

from .aspect import AspectSpec, SafeArea, aspect_for, safe_area_for
from .assets import AssetResolver
from .critic import SceneFacts, SceneSignature, SceneVariationPolicy, VisualDesignCritic
from .determinism import (
    DETERMINISTIC_BASE_CSS,
    STABLE_FONT_STACK,
    RenderSeed,
    validate_document,
)
from .layer import LayerRenderer
from .layout import LayoutEngine, LayoutResult
from .motion import MotionEngine, TimingPlan
from .typography import get_profile

#: Layer types whose box is *content*, i.e. something a viewer would notice being
#: printed over. A `shape` is furniture — a hairline rule, a tinted block behind a
#: quote — and two of those sharing a band is a composition, not a collision.
#: `background` is excluded outright: it is behind everything by contract.
_PAINTING_KINDS = frozenset({"text", "image", "video", "svg", "chart", "html"})


def _paints_content(layer: dict[str, Any]) -> bool:
    """Whether a shared position would be a defect rather than a design."""
    kind = str(layer.get("type") or "text").lower()
    if kind == "shape" and str(layer.get("kind") or "").lower() in {"block", "rule"}:
        return False
    role = str(layer.get("role") or "").lower()
    if role == "background":
        return False
    return kind in _PAINTING_KINDS


@dataclass
class CompiledScene:
    """Everything one compiled scene produced, including the critique."""
    html: str
    layout: LayoutResult
    timing: TimingPlan
    keyframes: str
    facts: SceneFacts
    seed: RenderSeed
    notes: list[str] = field(default_factory=list)

    @property
    def total_motion_ms(self) -> float:
        return self.timing.total_ms


def _escape(value: Any) -> str:
    return _html.escape(str(value), quote=True)


class SceneCompiler:
    """Compile IR V2 scenes into deterministic HTML documents."""

    def __init__(self, theme: Any, variation_policy: SceneVariationPolicy | None = None) -> None:
        self.theme = theme
        self.layout_engine = LayoutEngine()
        self.motion_engine = MotionEngine()
        self.critic = VisualDesignCritic()
        self.variation = variation_policy

    # ------------------------------------------------------------- compile
    def compile(
        self,
        scene: dict[str, Any],
        *,
        meta: dict[str, Any] | None = None,
        assets: list[dict[str, Any]] | dict[str, Any] | None = None,
        base_dir: Any | None = None,
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
        index: int = 1,
        total: int = 1,
        scene_duration_ms: float | None = None,
        output_preset: str = "youtube_16x9",
        safe_area_enabled: bool = True,
        project_id: str | None = None,
        variation_seed: int = 0,
        explicit_layout: str | None = None,
    ) -> CompiledScene:
        meta = meta or {}
        aspect = aspect_for(output_preset, width, height)
        safe = safe_area_for(output_preset, enabled=safe_area_enabled)
        profile = get_profile(meta.get("style_profile"))
        assets_resolver = AssetResolver(assets, base_dir=base_dir)

        layers = list(scene.get("layers") or [])
        if not layers:
            # V1-shaped scenes carry eyebrow/title/body instead of layers, so the
            # advanced renderer can still render them. This is a compatibility
            # bridge, not the main path — and it is deliberately listed in
            # `notes` so nobody mistakes it for native IR V2 rendering.
            layers = self._legacy_layers(scene)
            notes = ["scene had no IR V2 layers; synthesised from V1 fields"]
        else:
            notes = []

        # --- layout, with cross-scene variation applied when a policy exists.
        layout = self.layout_engine.choose(scene, explicit=explicit_layout)
        if self.variation is not None:
            from .layout import supported_layouts

            chosen, finding = self.variation.next_layout(
                layout.name, supported_layouts()
            )
            if finding is not None:
                layout = self.layout_engine.choose(scene, explicit=chosen)
                layout.reason.append(finding.message)
                layout.reason.append(finding.suggestion)

        placed = self.layout_engine.assign(layout, layers)

        # Unit scale keeps type optically correct when you change resolution:
        # a 480p render should not use 1080p's absolute pixel sizes.
        unit_scale = aspect.reference_px / 1080.0

        # --- motion. Derived from file duration when known, else a sane default.
        duration_ms = scene_duration_ms or float(scene.get("duration_hint_sec") or 4.0) * 1000
        seed = RenderSeed(
            project_id=project_id or str(meta.get("id") or "untitled"),
            scene_index=index,
            variation_seed=variation_seed,
            theme=getattr(self.theme, "id", "default"),
            layout=layout.name,
        )
        timing = self.motion_engine.build(
            layers, scene_duration_ms=duration_ms, fps=fps, seed=seed.value
        )

        renderer = LayerRenderer(self.theme, profile, aspect.reference_px, assets_resolver)
        sole_headline = self._is_sole_headline(layers)
        fragments: list[str] = []
        type_sizes: list[float] = []
        for position, (layer, slot, _key) in enumerate(placed):
            instance = (
                timing.instances[position]
                if position < len(timing.instances)
                else timing.instances[-1]
            )
            fragments.append(
                renderer.render(
                    layer, slot, instance,
                    is_sole_headline=sole_headline and position == 0,
                    unit_scale=unit_scale,
                )
            )
            role = str(layer.get("role") or "")
            from .typography import type_role_for

            step = profile.for_role(type_role_for(role, is_sole_headline=sole_headline))
            type_sizes.append(aspect.reference_px * step.scale * unit_scale)

        notes.extend(renderer.notes)

        facts = self._facts(
            index=index,
            layers=layers,
            placed=placed,
            timing=timing,
            layout=layout,
            safe=safe,
            type_sizes=type_sizes,
            scene=scene,
        )
        document = self._document(
            body="".join(fragments),
            layout=layout,
            timing=timing,
            aspect=aspect,
            safe=safe,
            meta=meta,
            scene=scene,
            index=index,
            total=total,
            width=width,
            height=height,
        )

        compiled = CompiledScene(
            html=document,
            layout=layout,
            timing=timing,
            keyframes="".join(i.keyframes for i in timing.instances),
            facts=facts,
            seed=seed,
            notes=notes,
        )
        compiled.notes.extend(
            str(finding) for finding in validate_document(document, seed=seed).violations
        )
        if self.variation is not None:
            self.variation.record(
                SceneSignature(
                    layout=layout.name,
                    motion_set=tuple(sorted({i.name for i in timing.instances})),
                    role_sequence=tuple(str(l.get("role") or "") for l in layers),
                )
            )
        return compiled

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _is_sole_headline(layers: list[dict[str, Any]]) -> bool:
        text_layers = [
            layer for layer in layers
            if str(layer.get("type") or "text").lower() == "text"
            and str(layer.get("content") or "").strip()
        ]
        if len(text_layers) != 1:
            return False
        role = str(text_layers[0].get("role") or "").lower()
        return role in {"headline", "subhead"}

    @staticmethod
    def _legacy_layers(scene: dict[str, Any]) -> list[dict[str, Any]]:
        """Synthesise minimal IR layers from V1 fields so nothing fails to render."""
        layers: list[dict[str, Any]] = []
        cursor = 0.16
        if scene.get("eyebrow"):
            layers.append({
                "type": "text", "role": "label", "content": scene["eyebrow"],
                "layout": {"x": 0.08, "y": cursor, "w": 0.5, "h": 0.06,
                           "anchor": "top_left"},
                "motion": {"semantic": "reveal"},
            })
            cursor += 0.10
        if scene.get("title"):
            layers.append({
                "type": "text", "role": "headline", "content": scene["title"],
                "layout": {"x": 0.08, "y": cursor, "w": 0.72, "h": 0.26,
                           "anchor": "top_left"},
                "motion": {"semantic": "reveal"},
            })
            cursor += 0.32
        if scene.get("body"):
            layers.append({
                "type": "text", "role": "body", "content": scene["body"],
                "layout": {"x": 0.08, "y": cursor, "w": 0.66, "h": 0.2,
                           "anchor": "top_left"},
                "motion": {"semantic": "reveal"},
            })
        if scene.get("metric"):
            layers.append({
                "type": "text", "role": "metric", "content": str(scene["metric"]),
                "layout": {"x": 0.62, "y": 0.68, "w": 0.3, "h": 0.14,
                           "anchor": "bottom_right"},
                "motion": {"semantic": "count"}, "style": {"color": "accent"},
            })
        if scene.get("tags"):
            layers.append({
                "type": "text", "role": "annotation",
                "content": " · ".join(str(t) for t in scene["tags"]),
                "layout": {"x": 0.08, "y": 0.84, "w": 0.55, "h": 0.06,
                           "anchor": "bottom_left"},
                "motion": {"semantic": "reveal"}, "style": {"color": "accent"},
            })
        return layers

    @staticmethod
    def _facts(
        *,
        index: int,
        layers: list[dict[str, Any]],
        placed: list[tuple[dict[str, Any], Any, str]],
        timing: TimingPlan,
        layout: LayoutResult,
        safe: SafeArea,
        type_sizes: list[float],
        scene: dict[str, Any],
    ) -> SceneFacts:
        text_layers = [
            layer for layer in layers
            if str(layer.get("type") or "text").lower() in {"text"}
            and str(layer.get("content") or "").strip()
        ]
        # Coverage of the *usable* area, ignoring full-bleed media.
        usable = max(1e-6, safe.usable_width * safe.usable_height)
        coverage = 0.0
        for layer, slot, _key in placed:
            if str(layer.get("type") or "").lower() in {"image", "video"} and slot.w >= 0.99:
                continue
            coverage += slot.w * slot.h
        coverage = min(1.0, coverage / usable)

        breaches: list[str] = []
        for layer, slot, key in placed:
            if str(layer.get("type") or "").lower() in {"image", "video"} and slot.w >= 0.99:
                continue  # full-bleed media is *supposed* to ignore safe areas
            if slot.y < safe.top:
                breaches.append(f"{key} above top inset ({safe.top:.0%})")
            if slot.y + slot.h > 1.0 - safe.bottom:
                breaches.append(f"{key} below bottom inset ({safe.bottom:.0%})")
            if slot.x + slot.w > 1.0 - safe.right:
                breaches.append(f"{key} past right inset ({safe.right:.0%})")

        accent_count = sum(
            1 for layer in layers
            if (layer.get("style") or {}).get("color") in {"accent", None}
            and str(layer.get("role") or "") in {"metric", "label"}
        )
        longest = max(
            (
                len(str(layer.get("content") or ""))
                + sum(
                    1
                    for ch in str(layer.get("content") or "")
                    if "\u3000" <= ch <= "\u9fff"
                )
                for layer in text_layers
            ),
            default=0,
        )
        return SceneFacts(
            index=index,
            layer_count=len(layers),
            text_layer_count=len(text_layers),
            motion_starts=[i.start_ms for i in timing.instances],
            motion_names=[str(i.name) for i in timing.instances],
            text_aligns=[slot.text_align for _l, slot, _k in placed],
            type_sizes=type_sizes,
            accent_layer_count=accent_count,
            coverage=coverage,
            layout=str(layout.name),
            safe_area_breaches=breaches,
            longest_line=longest,
            # Everything that paints its own content is checked, media included:
            # a full-bleed image *is* meant to sit under a caption, but a body
            # paragraph sharing a band with a diagram is not, and the engine
            # cannot tell the two apart from the coordinates alone. The decor
            # shapes are the exception — a hairline rule behind a headline is
            # deliberate furniture, and flagging it would train people to ignore
            # the check.
            slot_positions=[
                (key, slot.x, slot.y)
                for layer, slot, key in placed
                if _paints_content(layer) and str(layer.get("content") or "").strip()
            ],
            largest_is_large_text=bool(type_sizes) and max(type_sizes) >= 24,
            background_has_motion=any(
                str(i.name) == "parallax" for i in timing.instances
            ),
        )

    # ----------------------------------------------------------- document
    def _document(
        self,
        *,
        body: str,
        layout: LayoutResult,
        timing: TimingPlan,
        aspect: AspectSpec,
        safe: SafeArea,
        meta: dict[str, Any],
        scene: dict[str, Any],
        index: int,
        total: int,
        width: int,
        height: int,
    ) -> str:
        keyframes = "".join(instance.keyframes for instance in timing.instances)
        total_ms = max(timing.total_ms, 1.0)
        accent = self.theme.accent
        bg = self.theme.bg
        text = self.theme.text
        muted = self.theme.muted
        font = getattr(self.theme, "font", STABLE_FONT_STACK)
        title = _escape(meta.get("title") or "")
        brand = _escape(meta.get("brand") or meta.get("author") or "")
        counter = f"{index:02d}/{total:02d}" if total else f"{index:02d}"

        # Fixed-time animation: every animation is emitted paused, then one
        # deterministic timestamp is applied by the driver below. This is what
        # removes "which frame did the screenshot catch" from the picture.
        driver = f"""
<script>
(function(){{
  var T = {total_ms:.0f};
  document.getAnimations().forEach(function(a){{
    a.pause();
    try {{ a.currentTime = T; }} catch (e) {{}}
  }});
  document.documentElement.style.setProperty('animation-play-state','paused');
  var style = document.createElement('style');
  style.textContent = '*{{animation-play-state:paused !important}}';
  document.head.appendChild(style);
  window.HVW_FIXED_TIME = T;
}})();
</script>"""

        chrome = self._chrome(brand, counter, title, muted, accent, index, total)
        return f"""<!doctype html>
<html lang="{_escape(meta.get('language') or 'zh-CN')}"><head><meta charset="utf-8">
<title>{title}</title>
<style>
{DETERMINISTIC_BASE_CSS}
:root{{--bg:{bg};--accent:{accent};--text:{text};--muted:{muted}}}
html,body{{width:{width}px;height:{height}px;background:var(--bg);
 font-family:{STABLE_FONT_STACK};color:var(--text)}}
*{'{'}box-sizing:border-box}}
.scene{{position:relative;width:{width}px;height:{height}px;overflow:hidden;
 background:var(--bg)}}
.stage{{position:absolute;inset:0;{safe.as_css()}}}
.chrome{{position:absolute;inset:0;{safe.as_css()};pointer-events:none;z-index:50}}
{keyframes}
</style></head>
<body>
<div class="scene">
  <div class="stage">{body}</div>
  {chrome}
</div>
{driver}
</body></html>"""

    @staticmethod
    def _chrome(
        brand: str,
        counter: str,
        title: str,
        muted: str,
        accent: str,
        index: int,
        total: int,
    ) -> str:
        """Minimal chrome. Nothing about it animates.

        Scene furniture is the first thing that makes a generated frame look
        generated, because it repeats identically in every scene. This is
        deliberately near-invisible and never moves.
        """
        del index, total
        return (
            f'<div class="chrome">'
            f'<div style="position:absolute;top:0;left:0;font-size:13px;'
            f'letter-spacing:.16em;color:{muted};opacity:.75">{brand}</div>'
            f'<div style="position:absolute;bottom:0;left:0;font-size:12px;'
            f'color:{muted};opacity:.5">{counter}</div>'
            f'<div style="position:absolute;bottom:0;right:0;width:34px;height:2px;'
            f'background:{accent};opacity:.6"></div>'
            f"</div>"
        )
