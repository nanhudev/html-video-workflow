"""Template and style models.

Neither may name a renderer. A manifest says ``layouts: ["stat", "quote"]`` —
layout *primitives*, which any renderer is free to interpret. The moment a
manifest says ``remotionComponent: "StatBlock"`` the IR stops being retargetable
and this whole layer becomes a liability.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Layout primitives defined by the advanced renderer.
LAYOUT_PRIMITIVES = (
    "center", "split", "editorial_left", "editorial_right", "full_bleed",
    "overlay", "stat", "quote", "diagram",
)

#: Motion semantics defined by IR V2.
MOTION_SEMANTICS = (
    "reveal", "count", "trace", "connect", "split", "depth", "progression",
    "focus", "drift",
)


class TemplateManifest(BaseModel):
    """Agent-readable description of a video structure."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    version: str = "1.0.0"
    #: Written for a model: what this template is for, in one sentence.
    description: str = ""
    #: IR V2 ``video_type`` values this template serves.
    best_for: list[str] = Field(default_factory=list)
    #: Where it goes wrong. An agent that reads this avoids the mistake; a
    #: ranker that ignores it ships bad videos.
    not_for: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    aspects: list[str] = Field(default_factory=list)

    scene_count: dict[str, int] = Field(
        default_factory=lambda: {"min": 3, "max": 8, "recommended": 5})
    #: Narrative arc: the role each scene plays, in order.
    beats: list[str] = Field(default_factory=list)
    narration: dict[str, Any] = Field(default_factory=dict)
    layouts: list[str] = Field(default_factory=list)
    motion_vocabulary: list[str] = Field(default_factory=list)
    density: Literal["sparse", "balanced", "dense"] = "balanced"
    #: What must exist for this template to work at all (images, data…).
    requires: list[str] = Field(default_factory=list)

    default_style: str = "editorial"
    compatible_styles: list[str] = Field(default_factory=list)
    #: Weights the ranker applies; a manifest can express its own preferences.
    score_hints: dict[str, float] = Field(default_factory=dict)

    @field_validator("layouts")
    @classmethod
    def _known_layouts(cls, value: list[str]) -> list[str]:
        return [v for v in value if v in LAYOUT_PRIMITIVES] or ["editorial_left"]

    def supports_aspect(self, aspect: str | None) -> bool:
        return not self.aspects or not aspect or aspect in self.aspects

    def supports_platform(self, platform: str | None) -> bool:
        return not self.platforms or not platform or platform in self.platforms

    def clamp_scenes(self, wanted: int | None) -> int:
        low = int(self.scene_count.get("min", 3))
        high = int(self.scene_count.get("max", 8))
        recommended = int(self.scene_count.get("recommended", 5))
        if wanted is None:
            return recommended
        return max(low, min(high, int(wanted)))


class WritingPreset(BaseModel):
    """How the words should be written: who is talking, to whom, and how.

    A preset is *not* a template. A template decides what the video is made of
    (beats, layouts, scene count); a preset decides how the narration is
    written. Keeping them apart means "教程步骤 in blueprint colours" is a
    combination, not a new file.

    ``persona`` and ``rules`` are what a language model receives. They are
    deliberately separate from ``structure``/``description``, which exist for
    the human choosing the card — a user-facing blurb and a model instruction
    are different documents that happen to be about the same thing.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    icon: str = "✳"
    #: One line, for a card. The reason a user picks this one.
    tagline: str = ""
    #: The longer explanation, shown once the card is expanded.
    description: str = ""
    audience: str = ""
    tone: str = ""

    persona: str = ""
    rules: list[str] = Field(default_factory=list)
    #: The narrative arc, in user-facing language. Mirrors the template's
    #: ``beats`` without being the same thing: beats are machine kinds.
    structure: list[str] = Field(default_factory=list)

    #: Recommendations, never requirements — the request wins over the preset.
    template: str | None = None
    style: str | None = None
    duration_sec: int | None = None
    scenes: int | None = None
    platform: str | None = None
    tags: list[str] = Field(default_factory=list)

    def brief(self, custom: str | None = None) -> str:
        """The human-readable brief, used when no model is configured."""
        parts = [self.persona, *self.rules]
        if custom and custom.strip():
            parts.append(custom.strip())
        return "\n".join(part for part in parts if part)


class StyleProfile(BaseModel):
    """The skin. Never changes the argument, only the reading of it."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    description: str = ""
    palette: dict[str, str] = Field(default_factory=dict)
    fonts: dict[str, str] = Field(default_factory=dict)
    type_scale: dict[str, float] = Field(default_factory=dict)
    #: Legacy renderer theme this style maps onto. The split exists because the
    #: renderer still resolves colour through a theme while this layer thinks in
    #: palettes; the field is the bridge, and removing it is the right fix.
    theme: str = "academic-blue"
    #: IR ``style_profile`` value, which selects the typography profile.
    typography: str = "editorial"
    motion_bias: Literal["calm", "normal", "energetic"] = "normal"
    #: The critic refuses palettes below this; a style declares its own floor so
    #: "brand colours" cannot silently produce unreadable video.
    contrast_floor: float = 4.5
    tags: list[str] = Field(default_factory=list)

    def color(self, key: str, fallback: str = "#ffffff") -> str:
        return self.palette.get(key) or fallback
