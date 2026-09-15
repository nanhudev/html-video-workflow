"""Renderer themes.

A theme is a *palette + typography + texture* triplet. It is deliberately not a
layout: layouts belong to the IR (roles, hierarchy, motion). Ten legacy themes
are preserved verbatim so existing projects keep their look.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    id: str
    bg: str
    panel: str
    accent: str
    text: str
    muted: str
    mode: str
    font: str = "'Microsoft YaHei UI','Segoe UI',system-ui,sans-serif"
    radius: int = 28
    glow: bool = True


def _make(
    id: str,
    palette: tuple[str, str, str, str, str, str],
    *,
    font: str | None = None,
    radius: int | None = None,
    glow: bool | None = None,
) -> Theme:
    bg, panel, accent, text, muted, mode = palette
    flat = mode in {"brutal", "terminal", "newspaper"}
    mono = "'Cascadia Mono','Consolas',ui-monospace,monospace"
    return Theme(
        id=id,
        bg=bg,
        panel=panel,
        accent=accent,
        text=text,
        muted=muted,
        mode=mode,
        font=font or (mono if mode == "terminal" else Theme.font),
        radius=0 if flat else (radius if radius is not None else 28),
        glow=glow if glow is not None else not flat,
    )


#: The ten legacy templates, preserved for compatibility.
LEGACY_THEMES: dict[str, Theme] = {
    "academic-blue": _make(
        "academic-blue", ("#071c33", "#0b2d50", "#58c8ff", "#f4fbff", "#9cc8df", "academic")
    ),
    "minimal-light": _make(
        "minimal-light", ("#f5f1e8", "#ffffff", "#155eef", "#101828", "#667085", "minimal")
    ),
    "glass-aurora": _make(
        "glass-aurora", ("#100b2f", "#25175a", "#7cf7d4", "#ffffff", "#c7befd", "glass")
    ),
    "neo-brutal": _make(
        "neo-brutal", ("#ffd83d", "#fff7d0", "#ff4d2e", "#111111", "#3a3a3a", "brutal")
    ),
    "newspaper": _make(
        "newspaper", ("#e9e2d0", "#f8f2e4", "#9d1f1f", "#16130f", "#625c50", "paper")
    ),
    "terminal-green": _make(
        "terminal-green", ("#06110b", "#0a1d12", "#39ff88", "#d6ffe5", "#75a989", "terminal")
    ),
    "cyber-grid": _make(
        "cyber-grid", ("#050718", "#11142e", "#f449ff", "#f8f7ff", "#8fa7ff", "cyber")
    ),
    "warm-editorial": _make(
        "warm-editorial", ("#3d1715", "#652821", "#ffb067", "#fff4e6", "#e5bda2", "editorial")
    ),
    "data-dashboard": _make(
        "data-dashboard", ("#07111f", "#10243e", "#5ce1a5", "#f3f8ff", "#9bb0c8", "dashboard")
    ),
    "cinematic-dark": _make(
        "cinematic-dark", ("#050505", "#181818", "#d8b66a", "#ffffff", "#b9b9b9", "cinematic")
    ),
}

#: Style profiles — the future-facing notion of "style". Schema first, no
#: explosion of templates yet.
STYLE_PROFILES: dict[str, dict[str, str]] = {
    "editorial": {"density": "medium", "typography": "serif_display", "motion": "restrained"},
    "documentary": {"density": "low", "typography": "sans_editorial", "motion": "slow_push"},
    "minimal-tech": {"density": "low", "typography": "mono_accent", "motion": "precise"},
    "brutalist": {"density": "high", "typography": "oversized", "motion": "hard_cut"},
    "cinematic": {"density": "low", "typography": "wide_tracking", "motion": "drift"},
    "academic": {"density": "medium", "typography": "sans_structured", "motion": "stepped"},
    "corporate-clean": {"density": "medium", "typography": "sans_neutral", "motion": "soft"},
}


def get_theme(theme_id: str | None) -> Theme:
    if not theme_id:
        return LEGACY_THEMES["academic-blue"]
    return LEGACY_THEMES.get(theme_id, LEGACY_THEMES["academic-blue"])


def theme_ids() -> list[str]:
    return list(LEGACY_THEMES)


def style_profile_ids() -> list[str]:
    return list(STYLE_PROFILES)
