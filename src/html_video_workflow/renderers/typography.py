"""TypographyProfile — a type system, not per-layer font guesses.

The failure mode this replaces is easy to spot in generated slides: every text
layer is roughly the same size, the "title" differs from the body by a few
pixels, and nothing is optically weighted. That reads as machine-generated even
when each individual font choice is defensible.

A profile fixes the *ratios*. `display` is not a bigger `headline` — it is a
different job, and it only appears when a scene genuinely has one.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TypeStep:
    """One role's optical definition."""

    #: Size as a fraction of the reference pixel dimension.
    scale: float
    weight: int
    tracking: float  # em
    line_height: float
    #: Uppercase transform — used sparingly, because shouting is not emphasis.
    uppercase: bool = False

    def css(self, reference_px: float, *, unit_scale: float = 1.0) -> str:
        size = max(10.0, reference_px * self.scale * unit_scale)
        return (
            f"font-size:{size:.1f}px;"
            f"font-weight:{self.weight};"
            f"letter-spacing:{self.tracking:.3f}em;"
            f"line-height:{self.line_height:.2f};"
            f"text-transform:{'uppercase' if self.uppercase else 'none'}"
        )


@dataclass(frozen=True)
class TypographyProfile:
    """Six roles, fixed ratios. Roles are semantic; never invent a new one."""

    id: str
    display: TypeStep
    headline: TypeStep
    body: TypeStep
    caption: TypeStep
    annotation: TypeStep
    number: TypeStep

    def for_role(self, role: str) -> TypeStep:
        return getattr(self, role, self.body)

    def css(self, role: str, reference_px: float, *, unit_scale: float = 1.0) -> str:
        return self.for_role(role).css(reference_px, unit_scale=unit_scale)


# The ratios below are chosen so no two neighbouring steps are within ~15% of
# each other. Steps closer than that read as "approximately the same size",
# which is exactly what makes a frame look templated.
EDITORIAL = TypographyProfile(
    id="editorial",
    display=TypeStep(0.115, 800, -0.035, 1.02),
    headline=TypeStep(0.072, 700, -0.022, 1.14),
    body=TypeStep(0.038, 400, 0.005, 1.55),
    caption=TypeStep(0.030, 500, 0.010, 1.40),
    annotation=TypeStep(0.022, 700, 0.140, 1.25, uppercase=True),
    number=TypeStep(0.098, 800, -0.045, 1.00),
)

DOCUMENTARY = TypographyProfile(
    id="documentary",
    display=TypeStep(0.100, 700, -0.020, 1.06),
    headline=TypeStep(0.066, 600, -0.012, 1.18),
    body=TypeStep(0.036, 400, 0.004, 1.60),
    caption=TypeStep(0.028, 400, 0.008, 1.45),
    annotation=TypeStep(0.021, 600, 0.110, 1.30, uppercase=True),
    number=TypeStep(0.086, 700, -0.035, 1.00),
)

PRECISE_TECH = TypographyProfile(
    id="precise_tech",
    display=TypeStep(0.105, 700, -0.030, 1.05),
    headline=TypeStep(0.068, 600, -0.015, 1.16),
    body=TypeStep(0.034, 400, 0.002, 1.58),
    caption=TypeStep(0.027, 500, 0.006, 1.42),
    annotation=TypeStep(0.020, 700, 0.170, 1.22, uppercase=True),
    number=TypeStep(0.092, 700, -0.040, 1.00),
)

OVERSIZED = TypographyProfile(
    id="oversized",
    display=TypeStep(0.140, 900, -0.045, 0.96),
    headline=TypeStep(0.085, 800, -0.028, 1.08),
    body=TypeStep(0.040, 500, 0.000, 1.50),
    caption=TypeStep(0.031, 600, 0.000, 1.38),
    annotation=TypeStep(0.024, 800, 0.120, 1.20, uppercase=True),
    number=TypeStep(0.125, 900, -0.055, 0.95),
)

PROFILES: dict[str, TypographyProfile] = {
    p.id: p for p in (EDITORIAL, DOCUMENTARY, PRECISE_TECH, OVERSIZED)
}

#: Style profile (IR level) → typography profile (render level).
STYLE_TO_PROFILE: dict[str, str] = {
    "editorial": "editorial",
    "documentary": "documentary",
    "minimal-tech": "precise_tech",
    "brutalist": "oversized",
    "cinematic": "documentary",
    "academic": "editorial",
    "corporate-clean": "precise_tech",
}


def get_profile(style_profile: str | None) -> TypographyProfile:
    if not style_profile:
        return EDITORIAL
    return PROFILES.get(STYLE_TO_PROFILE.get(style_profile, ""), EDITORIAL)


#: IR layer roles → typographic roles.
ROLE_MAP: dict[str, str] = {
    "headline": "headline",
    "subhead": "headline",
    "metric": "number",
    "body": "body",
    "evidence": "body",
    "annotation": "annotation",
    "label": "annotation",
    "caption": "caption",
    "background": "body",
    "foreground": "display",
    "logo": "annotation",
}


def type_role_for(layer_role: str | None, *, is_sole_headline: bool = False) -> str:
    """Map an IR role onto a typographic role.

    ``is_sole_headline`` promotes a headline to ``display`` when it is the only
    text of consequence in the scene. A single big line is a statement; the same
    line surrounded by three others is just the top one — and promoting it anyway
    is how every frame ends up with the same oversized word in it.
    """
    if not layer_role:
        return "body"
    mapped = ROLE_MAP.get(layer_role, "body")
    if mapped == "headline" and is_sole_headline:
        return "display"
    return mapped
