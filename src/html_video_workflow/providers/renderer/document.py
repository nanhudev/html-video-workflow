"""Renderer-neutral IR  →  HTML/CSS document.

Anti-slideshow rules encoded here:

* layout comes from the IR (anchor + fractions), never "center everything";
* motion is chosen from ``motion.semantic``, never a uniform fade-up;
* roles drive typography scale, so a headline never looks like a caption.
"""
from __future__ import annotations

import html
from typing import Any

from .themes import Theme

ROLE_STYLE: dict[str, dict[str, str]] = {
    "headline": {"size": "60px", "weight": "800", "tracking": "-0.035em", "line": "1.12"},
    "subhead": {"size": "34px", "weight": "600", "tracking": "-0.01em", "line": "1.25"},
    "body": {"size": "27px", "weight": "400", "tracking": "0", "line": "1.55"},
    "annotation": {"size": "19px", "weight": "500", "tracking": "0.02em", "line": "1.4"},
    "label": {"size": "18px", "weight": "800", "tracking": "0.16em", "line": "1.2"},
    "metric": {"size": "52px", "weight": "900", "tracking": "-0.04em", "line": "1.0"},
    "evidence": {"size": "22px", "weight": "500", "tracking": "0", "line": "1.45"},
    "caption": {"size": "24px", "weight": "600", "tracking": "0", "line": "1.3"},
}

SEMANTIC_MOTION: dict[str, tuple[str, str]] = {
    # semantic: (keyframe name, extra css)
    "reveal": ("hvwReveal", "clip-path:inset(0 0 0 0)"),
    "count": ("hvwCount", ""),
    "trace": ("hvwTrace", ""),
    "connect": ("hvwConnect", "transform-origin:left center"),
    "split": ("hvwSplit", ""),
    "depth": ("hvwDepth", ""),
    "progression": ("hvwProgress", "transform-origin:left center"),
    "focus": ("hvwFocus", ""),
    "drift": ("hvwDrift", ""),
}

KEYFRAMES = """
@keyframes hvwReveal{from{opacity:0;transform:translateY(26px);clip-path:inset(0 0 100% 0)}to{opacity:1;transform:none;clip-path:inset(0 0 0 0)}}
@keyframes hvwCount{from{opacity:0;transform:scale(.92)}to{opacity:1;transform:none}}
@keyframes hvwTrace{from{opacity:0;stroke-dashoffset:var(--len,1200)}to{opacity:1;stroke-dashoffset:0}}
@keyframes hvwConnect{from{opacity:0;transform:scaleX(0)}to{opacity:1;transform:scaleX(1)}}
@keyframes hvwSplit{from{opacity:0;transform:translateX(-30px)}to{opacity:1;transform:none}}
@keyframes hvwDepth{from{opacity:0;transform:translateZ(-160px) scale(.9)}to{opacity:1;transform:none}}
@keyframes hvwProgress{from{opacity:.2;transform:scaleX(0)}to{opacity:1;transform:scaleX(1)}}
@keyframes hvwFocus{from{opacity:0;transform:scale(1.06)}to{opacity:1;transform:none}}
@keyframes hvwDrift{from{opacity:0;transform:scale(1.08) translate3d(0,0,0)}to{opacity:1;transform:none}}
"""


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _anchor_css(anchor: str | None) -> str:
    """Map IR anchors to flex alignment — asymmetry is allowed and expected."""
    mapping = {
        "top_left": ("flex-start", "flex-start", "left"),
        "top_right": ("flex-end", "flex-start", "right"),
        "bottom_left": ("flex-start", "flex-end", "left"),
        "bottom_right": ("flex-end", "flex-end", "right"),
        "center_left": ("flex-start", "center", "left"),
        "center_right": ("flex-end", "center", "right"),
        "center": ("center", "center", "center"),
    }
    return mapping.get(anchor or "top_left", mapping["top_left"])[2]


def _motion_css(layer: dict[str, Any]) -> str:
    motion = layer.get("motion") or {}
    semantic = (motion.get("semantic") or "reveal").lower()
    name, extra = SEMANTIC_MOTION.get(semantic, SEMANTIC_MOTION["reveal"])
    duration = int(motion.get("duration_ms") or 620)
    delay = int(motion.get("delay_ms") or 0)
    easing = motion.get("easing") or "cubic-bezier(.16,1,.3,1)"
    return (
        f"animation:{name} {duration}ms {easing} {delay}ms both;"
        f"animation-fill-mode:both;{extra}"
    )


def _role_css(role: str, typography: dict[str, Any]) -> str:
    base = dict(ROLE_STYLE.get(role, ROLE_STYLE["body"]))
    size_map = {"xs": "16px", "sm": "21px", "md": "30px", "lg": "44px", "xl": "62px"}
    if typography.get("size") in size_map:
        base["size"] = size_map[typography["size"]]
    elif typography.get("size"):
        base["size"] = str(typography["size"])
    if typography.get("weight"):
        base["weight"] = str(typography["weight"])
    if typography.get("tracking"):
        base["tracking"] = str(typography["tracking"])
    if typography.get("line"):
        base["line"] = str(typography["line"])
    return (
        f"font-size:{base['size']};font-weight:{base['weight']};"
        f"letter-spacing:{base['tracking']};line-height:{base['line']}"
    )


def _layer_html(layer: dict[str, Any], theme: Theme, index: int) -> str:
    layer_type = (layer.get("type") or "text").lower()
    role = layer.get("role") or ("headline" if index == 0 else "body")
    layout = layer.get("layout") or {}
    x = float(layout.get("x", 0.08))
    y = float(layout.get("y", 0.2 + 0.18 * index))
    w = float(layout.get("w", 0.6))
    h = float(layout.get("h", 0.2))
    anchor = _anchor_css(layout.get("anchor"))
    typography = layer.get("typography") or {}
    style = layer.get("style") or {}
    color = style.get("color")
    color_value = {
        "text": theme.text,
        "accent": theme.accent,
        "muted": theme.muted,
        "bg": theme.bg,
        "panel": theme.panel,
    }.get(color, style.get("hex") or (theme.accent if role in {"label", "metric"} else theme.text))

    box = (
        f"position:absolute;left:{x*100:.3f}%;top:{y*100:.3f}%;"
        f"width:{w*100:.3f}%;min-height:{h*100:.3f}%;text-align:{anchor};"
        f"color:{color_value};{_role_css(role, typography)};{_motion_css(layer)}"
    )
    if style.get("opacity") is not None:
        box += f"opacity:{float(style['opacity'])};"

    if layer_type == "shape":
        kind = layer.get("kind") or "rule"
        if kind == "rule":
            return f'<div style="{box};height:3px;background:{color_value}"></div>'
        if kind == "block":
            return f'<div style="{box};background:{color_value};opacity:.14"></div>'
        return f'<div style="{box};border:2px solid {color_value}"></div>'

    if layer_type == "image":
        src = _escape(layer.get("src") or layer.get("path") or "")
        alt = _escape(layer.get("alt") or "")
        return (
            f'<div style="{box}"><img src="{src}" alt="{alt}" '
            f'style="max-width:100%;max-height:100%;object-fit:cover"></div>'
        )

    if layer_type == "html":
        return f'<div style="{box}">{layer.get("content","")}</div>'

    if layer_type == "svg":
        return f'<div style="{box}">{layer.get("content","")}</div>'

    content = _escape(layer.get("content", ""))
    tag = "h1" if role == "headline" else ("h2" if role == "subhead" else "div")
    return f'<{tag} style="{box};margin:0">{content}</{tag}>'


def _legacy_layers(scene: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate V1 scene fields into IR layers so one renderer covers both."""
    layers: list[dict[str, Any]] = []
    cursor = 0.18
    if scene.get("eyebrow"):
        layers.append(
            {
                "type": "text",
                "role": "label",
                "content": scene["eyebrow"],
                "layout": {"x": 0.075, "y": 0.16, "w": 0.5, "h": 0.06, "anchor": "top_left"},
                "motion": {"semantic": "reveal", "duration_ms": 420, "delay_ms": 0},
            }
        )
        cursor = 0.24
    if scene.get("title"):
        layers.append(
            {
                "type": "text",
                "role": "headline",
                "content": scene["title"],
                "layout": {"x": 0.075, "y": cursor, "w": 0.72, "h": 0.26, "anchor": "top_left"},
                "motion": {"semantic": "reveal", "duration_ms": 620, "delay_ms": 120},
            }
        )
        cursor += 0.3
    if scene.get("body"):
        layers.append(
            {
                "type": "text",
                "role": "body",
                "content": scene["body"],
                "layout": {"x": 0.075, "y": cursor, "w": 0.68, "h": 0.2, "anchor": "top_left"},
                "motion": {"semantic": "reveal", "duration_ms": 560, "delay_ms": 260},
            }
        )
    if scene.get("tags"):
        layers.append(
            {
                "type": "text",
                "role": "annotation",
                "content": " · ".join(str(t) for t in scene["tags"]),
                "layout": {"x": 0.075, "y": 0.8, "w": 0.55, "h": 0.06, "anchor": "bottom_left"},
                "motion": {"semantic": "reveal", "duration_ms": 460, "delay_ms": 420},
                "style": {"color": "accent"},
            }
        )
    if scene.get("metric"):
        layers.append(
            {
                "type": "text",
                "role": "metric",
                "content": str(scene["metric"]),
                "layout": {"x": 0.62, "y": 0.70, "w": 0.3, "h": 0.12, "anchor": "bottom_right"},
                "motion": {"semantic": "count", "duration_ms": 700, "delay_ms": 380},
                "style": {"color": "accent"},
            }
        )
        if scene.get("metric_label"):
            layers.append(
                {
                    "type": "text",
                    "role": "annotation",
                    "content": str(scene["metric_label"]),
                    "layout": {"x": 0.62, "y": 0.845, "w": 0.3, "h": 0.05,
                               "anchor": "bottom_right"},
                    "motion": {"semantic": "reveal", "duration_ms": 420, "delay_ms": 520},
                    "style": {"color": "muted"},
                }
            )
    return layers


def build_scene_document(
    scene: dict[str, Any],
    theme: Theme,
    project_meta: dict[str, Any] | None = None,
    *,
    width: int = 1280,
    height: int = 720,
    index: int = 1,
    total: int = 1,
) -> str:
    """Return a standalone HTML document for one scene."""
    meta = project_meta or {}
    layers = scene.get("layers") or _legacy_layers(scene)
    texture = (
        "linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),"
        "linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px)"
        if theme.mode in {"cyber", "dashboard", "terminal"}
        else "radial-gradient(circle at 82% 14%, color-mix(in srgb, var(--accent) 26%, transparent), transparent 34%)"
    )
    glow = (
        f'<div style="position:absolute;right:-90px;top:-90px;width:420px;height:420px;'
        f'border-radius:50%;background:{theme.accent};filter:blur(110px);opacity:.16"></div>'
        if theme.glow
        else ""
    )
    border = "1px solid rgba(255,255,255,.14)" if theme.mode != "brutal" else "3px solid #111"
    body = "".join(_layer_html(layer, theme, i) for i, layer in enumerate(layers))
    brand = _escape(meta.get("brand") or meta.get("author") or "VIDEO RUNTIME")
    title = _escape(meta.get("title") or "")
    counter = f"{index:02d} / {total:02d}" if total else f"{index:02d}"

    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
:root{{--bg:{theme.bg};--panel:{theme.panel};--accent:{theme.accent};--text:{theme.text};--muted:{theme.muted}}}
*{{box-sizing:border-box}}
html,body{{margin:0;width:{width}px;height:{height}px;overflow:hidden;background:var(--bg)}}
body{{font-family:{theme.font};color:var(--text)}}
.frame{{position:relative;width:{width}px;height:{height}px;padding:64px 74px;
 background:{texture};background-size:46px 46px;overflow:hidden}}
{KEYFRAMES}
header{{position:absolute;top:44px;left:74px;right:74px;display:flex;justify-content:space-between;
 align-items:center;font-size:17px;letter-spacing:.14em;color:var(--muted)}}
.brand{{font-weight:800;color:var(--accent)}}
main{{position:absolute;inset:0}}
footer{{position:absolute;left:74px;right:74px;bottom:42px;display:flex;justify-content:space-between;
 align-items:center;color:var(--muted);font-size:16px}}
.line{{height:3px;width:170px;background:var(--accent);margin-bottom:10px}}
</style></head>
<body><div class="frame">{glow}
<header><div class="brand">{brand}</div><div>{counter}</div></header>
<main>{body}</main>
<footer><div><div class="line"></div>{title}</div><div>{_escape(meta.get("subtitle",""))}</div></footer>
</div></body></html>"""
