"""LayerRenderer — turn one IR layer into HTML + CSS.

The renderer never sees the IR's `motion` block directly; it consumes the already
decided `MotionInstance` and `Slot`. Keeping those boundaries rigid means the
motion engine can change without touching markup, and vice versa.
"""
from __future__ import annotations

import html as _html
from typing import Any

from .assets import AssetResolver, MissingAsset, ResolvedAsset
from .layout import Slot
from .motion import MotionInstance
from .typography import TypographyProfile, type_role_for

VOIDOK_TEXT_TYPES = {"text"}


def _escape(value: Any) -> str:
    return _html.escape(str(value), quote=True)


class LayerRenderer:
    """Emit markup for one layer, knowing nothing about the wider scene."""

    def __init__(
        self,
        theme: Any,
        profile: TypographyProfile,
        reference_px: int,
        assets: AssetResolver | None = None,
    ) -> None:
        self.theme = theme
        self.profile = profile
        self.reference_px = reference_px
        self.assets = assets or AssetResolver()
        self.notes: list[str] = []

    def render(
        self,
        layer: dict[str, Any],
        slot: Slot,
        motion: MotionInstance,
        *,
        is_sole_headline: bool = False,
        unit_scale: float = 1.0,
    ) -> str:
        kind = str(layer.get("type") or "text").lower()
        role = str(layer.get("role") or "").lower()
        type_role = type_role_for(role, is_sole_headline=is_sole_headline)

        style_parts = [
            slot.css(),
            self.profile.css(type_role, self.reference_px, unit_scale=unit_scale),
            f"color:{self._color(layer, role)}",
            motion.css,
        ]
        extra = layer.get("style") or {}
        if extra.get("opacity") is not None:
            style_parts.append(f"opacity:{float(extra['opacity'])}")
        if extra.get("background"):
            style_parts.append(f"background:{extra['background']}")
        if role == "background":
            # Backgrounds must sit behind everything and never capture clicks.
            style_parts.append("pointer-events:none")

        style = ";".join(style_parts)

        if kind == "image":
            return self._image(layer, style)
        if kind == "video":
            return self._video(layer, style)
        if kind in {"svg", "html"}:
            inner = str(layer.get("content") or "")
            return f'<div style="{style}">{inner}</div>'
        if kind == "shape":
            return self._shape(layer, style)
        if kind == "chart":
            return self._chart(layer, style)
        return self._text(layer, style, role)

    # ------------------------------------------------------------- fragments
    def _text(self, layer: dict[str, Any], style: str, role: str) -> str:
        content = _escape(layer.get("content", ""))
        if not content:
            self.notes.append(f"empty text layer (role={role or 'none'})")
        # Semantics matter for accessibility even in a rendered image, and cost
        # nothing: a screen reader happy path is a free side effect here.
        tag = "h1" if role == "headline" else ("h2" if role == "subhead" else "p")
        return f'<{tag} style="{style};margin:0">{content}</{tag}>'

    def _image(self, layer: dict[str, Any], style: str) -> str:
        resolved = self.assets.resolve(layer.get("src") or layer.get("path"))
        if isinstance(resolved, MissingAsset):
            # A missing asset gets a visible marker, never a broken <img> that
            # silently renders as nothing and looks like an intentional blank.
            self.notes.append(f"missing image: {resolved.reason}")
            return (
                f'<div style="{style};border:2px dashed {self.theme.accent};'
                f'display:flex;align-items:center;justify-content:center;'
                f'font-size:14px;color:{self.theme.muted}">'
                f"missing asset: {_escape(resolved.ref)}</div>"
            )
        assert isinstance(resolved, ResolvedAsset)
        src = _escape(resolved.as_src())
        fit = (layer.get("style") or {}).get("fit") or "cover"
        return (
            f'<img src="{src}" alt="{_escape(layer.get("alt") or "")}" '
            f'style="{style};object-fit:{fit};max-width:100%">'
        )

    def _video(self, layer: dict[str, Any], style: str) -> str:
        resolved = self.assets.resolve(layer.get("src"))
        if isinstance(resolved, MissingAsset):
            self.notes.append(f"missing video: {resolved.reason}")
            return (
                f'<div style="{style};border:2px dashed {self.theme.accent};'
                f'display:flex;align-items:center;justify-content:center;'
                f'font-size:14px;color:{self.theme.muted}">missing video</div>'
            )
        assert isinstance(resolved, ResolvedAsset)
        # muted+playsinline is required for any browser to paint a frame
        # without user interaction.
        return (
            f'<video src="{_escape(resolved.as_src())}" muted playsinline '
            f'preload="auto" style="{style};object-fit:cover"></video>'
        )

    def _shape(self, layer: dict[str, Any], style: str) -> str:
        kind = str(layer.get("kind") or "rule").lower()
        color = self._color(layer, "")
        if kind == "rule":
            return f'<div style="{style};height:3px;background:{color}"></div>'
        if kind == "block":
            return f'<div style="{style};background:{color};opacity:.14"></div>'
        if kind == "ring":
            return (
                f'<div style="{style};border:2px solid {color};'
                f'border-radius:50%;aspect-ratio:1"></div>'
            )
        return f'<div style="{style};border:2px solid {color}"></div>'

    def _chart(self, layer: dict[str, Any], style: str) -> str:
        """Minimal inline bar chart. No charting library dependency.

        The alternative — pulling a charting runtime in — would add a heavy
        dependency to a renderer that is supposed to stay dependency-free, and
        would make every frame depend on that library's async layout. Bars are
        divs. That is genuinely all most video charts need.
        """
        series = (layer.get("style") or {}).get("series") or []
        if not series:
            self.notes.append("chart layer has no series data")
            return f'<div style="{style}"></div>'
        peak = max((float(point.get("value", 0)) for point in series), default=1) or 1
        accent = self.theme.accent
        bars = "".join(
            f'<div style="flex:1;display:flex;flex-direction:column;'
            f'justify-content:flex-end;align-items:center">'
            f'<div style="width:72%;height:{(float(point.get("value", 0)) / peak) * 100:.1f}%;'
            f'background:{accent};border-radius:2px"></div>'
            f'<div style="font-size:11px;color:{self.theme.muted};margin-top:6px">'
            f"{_escape(point.get('label', ''))}</div>"
            f"</div>"
            for point in series
        )
        return (
            f'<div style="{style}">'
            f'<div style="width:100%;height:100%;display:flex;align-items:flex-end;'
            f'gap:6px">{bars}</div></div>'
        )

    # ---------------------------------------------------------------- color
    def _color(self, layer: dict[str, Any], role: str) -> str:
        style = layer.get("style") or {}
        named = style.get("color")
        mapping = {
            "text": self.theme.text,
            "accent": self.theme.accent,
            "muted": self.theme.muted,
            "bg": self.theme.bg,
            "panel": self.theme.panel,
        }
        if isinstance(named, str) and named in mapping:
            return mapping[named]
        if style.get("hex"):
            return str(style["hex"])
        if named:
            return str(named)
        # Metrics and labels carry the accent by default; everything else is
        # body text. Defaulting everything to the accent is AA-007.
        return self.theme.accent if role in {"metric", "label"} else self.theme.text
