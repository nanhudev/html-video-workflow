"""Video Project IR V2 — pydantic models.

Design rule: the IR describes meaning, never rendering technology. A layer is
``{"type": "text", "role": "headline"}`` — never a component name.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SCHEMA_VERSION = 2

LayerType = Literal[
    "text", "image", "video", "svg", "html", "chart", "shape", "avatar", "effect", "audio"
]
LayerRole = Literal[
    "headline", "subhead", "body", "annotation", "label", "metric", "evidence",
    "background", "foreground", "logo", "caption",
]
VisualStrategy = Literal[
    "typography_led", "diagram_led", "image_led", "data_led", "screen_led",
    "avatar_led", "broll", "chart",
]
VideoType = Literal[
    "explainer", "product_demo", "knowledge", "news", "data_story", "tutorial",
    "social_short", "essay", "documentary", "avatar_presenter", "music_visualizer",
    "custom",
]
OutputPreset = Literal[
    "youtube_16x9", "youtube_shorts_9x16", "tiktok_9x16", "instagram_reels_9x16",
    "x_16x9", "bilibili_16x9", "xiaohongshu_3x4", "wechat_channels_9x16", "custom",
]


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class SourceRef(_Base):
    id: str | None = None
    title: str | None = None
    url: str | None = None
    retrieved_at: str | None = None
    trust: Literal["user_provided", "public_web", "model", "unknown"] = "unknown"


class Brand(_Base):
    name: str | None = None
    colors: dict[str, str] = Field(default_factory=dict)
    fonts: dict[str, str] = Field(default_factory=dict)
    logo: str | None = None


class CaptionSpec(_Base):
    mode: Literal["none", "burn_in", "sidecar", "both"] = "burn_in"
    format: Literal["srt", "ass", "vtt"] = "srt"
    position: str = "lower_third"
    safe_area: bool = True


class OutputSpec(_Base):
    preset: OutputPreset = "youtube_16x9"
    width: int = 1280
    height: int = 720
    fps: int = 30
    bitrate_kbps: int = 6000
    captions: CaptionSpec = Field(default_factory=CaptionSpec)


class Beat(_Base):
    id: str | None = None
    t: float = 0.0
    kind: str = "transition"
    label: str | None = None
    intent: str | None = None


class Story(_Base):
    logline: str | None = None
    beats: list[Beat] = Field(default_factory=list)


class NarrationIR(_Base):
    """Rich narration description; providers map whatever they support."""

    text: str = ""
    speaker: str = "narrator"
    language: str = "zh-CN"
    voice: str | None = None
    emotion: str | None = None
    pace: float | None = None
    pitch: float | None = None
    energy: float | None = None
    pause_before_ms: int = 0
    pause_after_ms: int = 0
    emphasis: list[str] = Field(default_factory=list)
    pronunciation: dict[str, str] = Field(default_factory=dict)
    style: str | None = None


class Layout(_Base):
    x: float = 0.08
    y: float = 0.2
    w: float = 0.6
    h: float = 0.2
    anchor: str = "top_left"

    @field_validator("x", "y", "w", "h")
    @classmethod
    def _clamp(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class Typography(_Base):
    size: str | None = None
    weight: int | None = None
    align: str | None = None
    tracking: str | None = None
    line: str | None = None


class Motion(_Base):
    enter: str | None = None
    duration_ms: int = 600
    delay_ms: int = 0
    easing: str | None = None
    semantic: Literal[
        "reveal", "count", "trace", "connect", "split", "depth", "progression",
        "focus", "drift",
    ] = "reveal"


class Layer(_Base):
    id: str | None = None
    type: LayerType = "text"
    role: LayerRole | None = None
    content: str = ""
    src: str | None = None
    kind: str | None = None
    typography: Typography = Field(default_factory=Typography)
    layout: Layout = Field(default_factory=Layout)
    motion: Motion = Field(default_factory=Motion)
    style: dict[str, Any] = Field(default_factory=dict)


class Caption(_Base):
    text: str = ""
    position: str = "lower_third"
    safe_area: bool = True


class Camera(_Base):
    type: str = "static"
    intensity: float | None = None


class Shot(_Base):
    id: str | None = None
    start: float = 0.0
    duration: float = 4.0
    camera: Camera = Field(default_factory=Camera)
    caption: Caption | None = None
    layers: list[Layer] = Field(default_factory=list)


class Transition(_Base):
    type: str = "cut"
    duration_ms: int = 0


class Scene(_Base):
    id: str | None = None
    intent: str | None = None
    duration_hint_sec: float | None = None
    narration: NarrationIR = Field(default_factory=NarrationIR)
    visual_strategy: VisualStrategy = "typography_led"
    sources: list[str] = Field(default_factory=list)
    transition: Transition = Field(default_factory=Transition)
    shots: list[Shot] = Field(default_factory=list)
    # Legacy V1 fields tolerated for round-tripping (eyebrow/title/body/tags/metric).
    title: str | None = None
    body: str | None = None
    eyebrow: str | None = None
    tags: list[str] = Field(default_factory=list)
    metric: str | None = None
    metric_label: str | None = None


class Sequence(_Base):
    id: str | None = None
    intent: str | None = None
    scenes: list[Scene] = Field(default_factory=list)


class AudioSpec(_Base):
    narration_voice: dict[str, Any] = Field(default_factory=dict)
    bgm: dict[str, Any] | None = None
    sfx: list[dict[str, Any]] = Field(default_factory=list)
    mix: dict[str, Any] = Field(default_factory=dict)
    loudness_target_lufs: float = -16.0


class AssetRef(_Base):
    id: str | None = None
    kind: str = "image"
    origin: Literal[
        "local", "user", "licensed_stock", "generated", "screenshot", "recording", "remote"
    ] = "local"
    path: str | None = None
    url: str | None = None
    license: str | None = None
    generated: bool = False
    generator: str | None = None
    prompt: str | None = None
    sha256: str | None = None
    created_at: str | None = None
    attribution: str | None = None


class QualitySpec(_Base):
    checks: list[str] = Field(
        default_factory=lambda: ["file_exists", "duration", "streams", "audio_level"]
    )
    report: dict[str, Any] | None = None


class Provenance(_Base):
    generator: str | None = None
    prompts: list[str] = Field(default_factory=list)
    providers: dict[str, Any] = Field(default_factory=dict)
    created_by: Literal["agent", "studio", "cli", "api", "mcp"] = "cli"


class ProjectMeta(_Base):
    title: str = "Untitled"
    subtitle: str | None = None
    language: str = "zh-CN"
    video_type: VideoType = "explainer"
    style_profile: str = "editorial"
    theme: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class VideoProject(_Base):
    schema_version: int = SCHEMA_VERSION
    id: str | None = None
    project: ProjectMeta = Field(default_factory=ProjectMeta)
    sources: list[SourceRef] = Field(default_factory=list)
    brand: Brand = Field(default_factory=Brand)
    output: OutputSpec = Field(default_factory=OutputSpec)
    story: Story = Field(default_factory=Story)
    sequences: list[Sequence] = Field(default_factory=list)
    audio: AudioSpec = Field(default_factory=AudioSpec)
    assets: list[AssetRef] | dict[str, Any] = Field(default_factory=list)
    quality: QualitySpec = Field(default_factory=QualitySpec)
    provenance: Provenance = Field(default_factory=Provenance)

    # ------------------------------------------------------------- helpers
    @property
    def scenes(self) -> list[Scene]:
        return [scene for seq in self.sequences for scene in seq.scenes]

    @property
    def scene_count(self) -> int:
        return len(self.scenes)

    def estimated_duration(self) -> float:
        total = 0.0
        for scene in self.scenes:
            if scene.duration_hint_sec:
                total += scene.duration_hint_sec
            elif scene.shots:
                total += sum(shot.duration for shot in scene.shots)
            else:
                total += 4.0
        return round(total, 2)

    def narration_texts(self) -> list[str]:
        return [scene.narration.text for scene in self.scenes if scene.narration.text]


def validate_project(data: dict[str, Any]) -> tuple[VideoProject | None, list[str]]:
    """Return (project, errors). Errors are path-prefixed and human readable."""
    try:
        return VideoProject.model_validate(data), []
    except ValidationError as exc:
        errors = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"]) or "<root>"
            errors.append(f"{location}: {error['msg']}")
        return None, errors
