"""Aspect ratios, safe areas and display geometry.

Every platform crops video differently, and every platform puts UI *on top* of
your video. A 9:16 export that fills the full frame will have its headline
sitting under TikTok's like/share row and its bottom line behind the caption.

Safe areas are therefore not decoration — they are the difference between a frame
that reads and one that is occluded. The percentages below are derived from each
platform's documented overlay regions, rounded outward so we stay conservative.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AspectName = Literal["16:9", "9:16", "1:1", "4:5", "3:4"]


@dataclass(frozen=True)
class SafeArea:
    """Insets as fractions of the frame, measured from each edge."""

    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    left: float = 0.0

    def __post_init__(self) -> None:
        for name in ("top", "right", "bottom", "left"):
            value = getattr(self, name)
            if not 0.0 <= value < 1.0:
                raise ValueError(f"safe area {name}={value} must be in [0, 1)")

    @property
    def usable_height(self) -> float:
        return max(0.0, 1.0 - self.top - self.bottom)

    @property
    def usable_width(self) -> float:
        return max(0.0, 1.0 - self.left - self.right)

    def as_css(self) -> str:
        return (
            f"padding-top:{self.top * 100:.3f}%;"
            f"padding-right:{self.right * 100:.3f}%;"
            f"padding-bottom:{self.bottom * 100:.3f}%;"
            f"padding-left:{self.left * 100:.3f}%"
        )


#: Overlay regions per platform, expressed as fractions of the frame.
#: ``content`` is the area we must keep clear of overlays entirely.
PLATFORM_SAFE_AREAS: dict[str, SafeArea] = {
    # Landscape: overlays are thin; a small uniform margin is enough.
    "youtube_16x9": SafeArea(top=0.045, right=0.04, bottom=0.085, left=0.04),
    "bilibili_16x9": SafeArea(top=0.05, right=0.04, bottom=0.09, left=0.04),
    "x_16x9": SafeArea(top=0.05, right=0.05, bottom=0.09, left=0.05),
    # Vertical: the right rail holds like/share/comment, the bottom holds the
    # caption block and the progress bar. These are large and they are real.
    "tiktok_9x16": SafeArea(top=0.10, right=0.155, bottom=0.185, left=0.05),
    "instagram_reels_9x16": SafeArea(top=0.10, right=0.145, bottom=0.175, left=0.05),
    "youtube_shorts_9x16": SafeArea(top=0.085, right=0.14, bottom=0.145, left=0.05),
    "wechat_channels_9x16": SafeArea(top=0.09, right=0.13, bottom=0.15, left=0.05),
    "xiaohongshu_3x4": SafeArea(top=0.075, right=0.09, bottom=0.13, left=0.05),
    # Unconstrained fallback: enough to avoid edge-clipping without being 9:16.
    "custom": SafeArea(top=0.05, right=0.05, bottom=0.08, left=0.05),
}


@dataclass(frozen=True)
class AspectSpec:
    name: AspectName
    width: int
    height: int

    @property
    def ratio(self) -> float:
        return self.width / self.height

    @property
    def orientation(self) -> str:
        if abs(self.ratio - 1.0) < 1e-6:
            return "square"
        return "landscape" if self.ratio > 1.0 else "portrait"

    @property
    def reference_px(self) -> int:
        """The dimension used to scale type.

        Using the *smaller* dimension for portrait and the height for landscape
        keeps type optically consistent across aspects; scaling from width makes
        9:16 type absurdly large.
        """
        return self.height if self.ratio >= 1.0 else self.width


ASPECTS: dict[AspectName, AspectSpec] = {
    "16:9": AspectSpec("16:9", 1920, 1080),
    "9:16": AspectSpec("9:16", 1080, 1920),
    "1:1": AspectSpec("1:1", 1080, 1080),
    "4:5": AspectSpec("4:5", 1080, 1350),
    "3:4": AspectSpec("3:4", 1080, 1440),
}


def aspect_for(output_preset: str, width: int, height: int) -> AspectSpec:
    """Resolve the aspect for a project, honouring the actual pixel size.

    The pixel dimensions win whenever they disagree with the declared preset.
    Trusting the preset would give a 1080x1920 render the *16:9* reference
    dimension, scaling every type size from the wrong edge, while looking like
    it worked. A caller passing contradictory values is a bug worth being
    loud about, not one worth silently resolving in favour of metadata.
    """
    height = max(1, int(height))
    width = max(1, int(width))
    actual_ratio = width / height
    if abs(actual_ratio - 1.0) < 1e-3:
        return ASPECTS["1:1"]

    if actual_ratio >= 1.7:
        return ASPECTS["16:9"]
    if actual_ratio <= 0.65:
        return ASPECTS["9:16"]
    if abs(actual_ratio - 4 / 5) < 0.02:
        return ASPECTS["4:5"]
    if abs(actual_ratio - 3 / 4) < 0.02:
        return ASPECTS["3:4"]
    # Square-ish but not exactly square: fall back to the declared preset so a
    # platform's intended framing survives.
    mapping: dict[str, AspectName] = {
        "youtube_16x9": "16:9",
        "bilibili_16x9": "16:9",
        "x_16x9": "16:9",
        "tiktok_9x16": "9:16",
        "instagram_reels_9x16": "9:16",
        "youtube_shorts_9x16": "9:16",
        "wechat_channels_9x16": "9:16",
        "xiaohongshu_3x4": "3:4",
    }
    return ASPECTS.get(mapping.get(output_preset, ""), ASPECTS["1:1"])


def safe_area_for(output_preset: str, *, enabled: bool = True) -> SafeArea:
    """Platform overlay insets, or an empty area when the user turned it off.

    ``enabled=False`` is a legitimate choice (burning your own full-bleed
    background to the edge is fine) — but it is opt-in, never silent.
    """
    if not enabled:
        return SafeArea()
    return PLATFORM_SAFE_AREAS.get(output_preset, PLATFORM_SAFE_AREAS["custom"])
