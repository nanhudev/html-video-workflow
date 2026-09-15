"""``CreateVideoRequest`` — the single input object for every entry point.

Design rules that took real effort to hold onto:

* **One object, four entry points.** The CLI parses argv into this, FastAPI
  validates a JSON body into this, ``create_video(**kwargs)`` builds this from
  keywords, and the MCP tool maps its schema onto this. They then all call the
  same Runtime method, so a capability can never exist in one entry point only.
* **Nothing here is required except intent.** A user may supply only
  ``prompt="..."``; everything else is a *preference* the planner honours when
  it can and records when it cannot.
* **Overrides are explicit and auditable.** Forcing ``renderer="legacy_html"``
  is allowed, but it lands in the plan's ``reasons`` so nobody has to guess why
  a video looks the way it does.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Aspect ratios the renderer actually knows how to lay out safely.
AspectRatio = Literal["16:9", "9:16", "1:1", "4:5", "3:4"]
RoutePreset = Literal["auto", "fast", "balanced", "high_quality", "max_quality"]


class PlatformPreset(BaseModel):
    """A delivery target: aspect, resolution, safe-area insets, bitrate."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    aspect: AspectRatio
    width: int
    height: int
    fps: int = 30
    bitrate_kbps: int = 6000
    #: Fraction of the frame kept clear at the bottom (and sides), because
    #: platforms overlay their own UI there. A caption placed inside an inset
    #: is a caption nobody reads.
    safe_bottom: float = 0.06
    safe_side: float = 0.05
    max_duration_sec: float | None = None
    #: Platforms differ in how much text a viewer will tolerate per screen.
    density: Literal["sparse", "balanced", "dense"] = "balanced"


PLATFORM_PRESETS: dict[str, PlatformPreset] = {
    p.id: p
    for p in (
        PlatformPreset(id="youtube_16x9", label="YouTube 16:9", aspect="16:9",
                       width=1920, height=1080, fps=30, bitrate_kbps=8000,
                       safe_bottom=0.05, density="balanced"),
        PlatformPreset(id="bilibili_16x9", label="Bilibili 16:9", aspect="16:9",
                       width=1920, height=1080, fps=30, bitrate_kbps=8000,
                       safe_bottom=0.05, density="balanced"),
        PlatformPreset(id="x_16x9", label="X / Twitter 16:9", aspect="16:9",
                       width=1280, height=720, fps=30, bitrate_kbps=5000,
                       safe_bottom=0.07, density="sparse"),
        PlatformPreset(id="youtube_shorts_9x16", label="YouTube Shorts 9:16",
                       aspect="9:16", width=1080, height=1920, fps=30,
                       bitrate_kbps=8000, safe_bottom=0.14, safe_side=0.08,
                       max_duration_sec=60, density="dense"),
        PlatformPreset(id="tiktok_9x16", label="TikTok 9:16", aspect="9:16",
                       width=1080, height=1920, fps=30, bitrate_kbps=8000,
                       safe_bottom=0.16, safe_side=0.08, max_duration_sec=180,
                       density="dense"),
        PlatformPreset(id="instagram_reels_9x16", label="Instagram Reels 9:16",
                       aspect="9:16", width=1080, height=1920, fps=30,
                       bitrate_kbps=8000, safe_bottom=0.15, safe_side=0.08,
                       max_duration_sec=90, density="dense"),
        PlatformPreset(id="wechat_channels_9x16", label="微信视频号 9:16",
                       aspect="9:16", width=1080, height=1920, fps=30,
                       bitrate_kbps=7000, safe_bottom=0.15, safe_side=0.08,
                       max_duration_sec=60, density="dense"),
        PlatformPreset(id="xiaohongshu_3x4", label="小红书 3:4", aspect="3:4",
                       width=1080, height=1440, fps=30, bitrate_kbps=7000,
                       safe_bottom=0.10, density="balanced"),
        PlatformPreset(id="square_1x1", label="Square 1:1", aspect="1:1",
                       width=1080, height=1080, fps=30, bitrate_kbps=6000,
                       safe_bottom=0.07, density="balanced"),
        PlatformPreset(id="custom", label="Custom", aspect="16:9",
                       width=1280, height=720, fps=30, bitrate_kbps=6000,
                       density="balanced"),
    )
}

#: IR V2 ``OutputPreset`` values that map straight onto a platform preset.
_IR_PRESET_ALIAS: dict[str, str] = {
    "youtube_16x9": "youtube_16x9",
    "youtube_shorts_9x16": "youtube_shorts_9x16",
    "tiktok_9x16": "tiktok_9x16",
    "instagram_reels_9x16": "instagram_reels_9x16",
    "x_16x9": "x_16x9",
    "bilibili_16x9": "bilibili_16x9",
    "xiaohongshu_3x4": "xiaohongshu_3x4",
    "wechat_channels_9x16": "wechat_channels_9x16",
    "custom": "custom",
}


def resolve_output(platform: str | None, aspect: str | None,
                   width: int | None, height: int | None) -> PlatformPreset:
    """Turn a loose user preference into one concrete delivery target.

    Precedence: explicit ``platform`` wins; otherwise an ``aspect`` narrows the
    field to the first preset carrying that aspect; otherwise 16:9. Explicit
    width/height are applied last so "1080p vertical" never silently reverts to
    a preset's default.
    """
    key = (platform or "").strip()
    preset = PLATFORM_PRESETS.get(_IR_PRESET_ALIAS.get(key, key))
    if preset is None and aspect:
        wanted = aspect.replace("：", ":").strip()
        preset = next((p for p in PLATFORM_PRESETS.values()
                       if p.aspect == wanted and p.id != "custom"), None)
    if preset is None:
        preset = PLATFORM_PRESETS["youtube_16x9"]
    if width and height and (width != preset.width or height != preset.height):
        preset = preset.model_copy(update={"width": int(width), "height": int(height)})
    return preset


class SourceInput(BaseModel):
    """Material to base the video on.

    ``kind="auto"`` lets the SourceProvider decide from the value itself: a
    URL becomes a webpage, a ``.md`` path becomes Markdown, bare prose becomes
    text. Asking users to classify their own input is a tax with no upside.
    """

    model_config = ConfigDict(extra="allow")

    kind: Literal["auto", "text", "markdown", "file", "webpage", "github", "url"] = "auto"
    value: str = ""
    #: Hard cap on ingested characters. Long source documents summarise badly
    #: and blow up planner prompts, so the cut is deliberate and reported.
    max_chars: int = 12000

    @field_validator("value")
    @classmethod
    def _strip(cls, value: str) -> str:
        return (value or "").strip()


class CreateVideoRequest(BaseModel):
    """The whole ask, in one object. Only one of the intent fields is needed."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # ---------------------------------------------------------------- intent
    prompt: str | None = Field(
        default=None, description="Free-form ask, e.g. 'explain vector databases'")
    topic: str | None = Field(default=None, description="Short topic title")
    source: SourceInput | None = Field(
        default=None, description="Document/URL/repo to ground the video in")
    script: str | None = Field(
        default=None, description="Pre-written narration; skips script planning")
    title: str | None = None

    # ---------------------------------------------------------------- shape
    language: str = "zh-CN"
    platform: str | None = Field(default=None, description="Platform preset id")
    aspect: AspectRatio | None = None
    width: int | None = None
    height: int | None = None
    duration_sec: float | None = Field(default=None, ge=5.0, le=1200.0)
    scenes: int | None = Field(default=None, ge=1, le=40)

    # ----------------------------------------------------------- appearance
    template: str | None = Field(default=None, description="Force a template id")
    style: str | None = Field(default=None, description="Style profile id")
    voice: str | None = None
    captions: bool = True

    # ------------------------------------------------------------- routing
    preset: RoutePreset = "auto"
    llm: str | None = None
    tts: str | None = None
    renderer: str | None = None

    # ------------------------------------------------------------- behaviour
    out_dir: str | None = None
    #: ``False`` returns immediately with a job id (REST/MCP use this).
    wait: bool = True
    #: Plan and build the IR but do not render. Cheap way to inspect decisions.
    dry_run: bool = False
    #: QC failures become errors instead of warnings.
    strict: bool = False
    created_by: Literal["agent", "studio", "cli", "api", "mcp", "sdk"] = "cli"

    # ----------------------------------------------------------- validators
    @field_validator("duration_sec")
    @classmethod
    def _round_duration(cls, value: float | None) -> float | None:
        return round(value, 2) if value else value

    @model_validator(mode="after")
    def _require_intent(self) -> CreateVideoRequest:
        if not any((self.prompt, self.topic, self.script,
                    self.source and self.source.value)):
            raise ValueError(
                "nothing to make a video from: supply prompt, topic, script or source")
        return self

    # -------------------------------------------------------------- helpers
    @property
    def intent_text(self) -> str:
        """The best single sentence describing what the user wants."""
        if self.script:
            return self.script.strip()[:400]
        if self.prompt:
            return self.prompt.strip()
        if self.topic:
            return self.topic.strip()
        if self.source:
            return self.source.value[:400]
        return ""

    def output(self) -> PlatformPreset:
        return resolve_output(self.platform, self.aspect, self.width, self.height)

    def overrides(self) -> dict[str, str]:
        """Provider locks. Empty strings are treated as 'no preference'."""
        return {
            key: value
            for key, value in (("llm", self.llm), ("tts", self.tts),
                               ("renderer", self.renderer))
            if value
        }


class VideoResult(BaseModel):
    """What came back. ``ok`` is the only field a caller must check."""

    model_config = ConfigDict(extra="allow")

    ok: bool = False
    job_id: str | None = None
    project_id: str | None = None
    video_path: str | None = None
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    scenes: int = 0

    template: str | None = None
    style: str | None = None
    title: str | None = None

    #: Which provider actually ran each stage.
    providers: dict[str, str] = Field(default_factory=dict)
    #: Every silent-degradation escape hatch, with a reason. Never empty when
    #: something fell back.
    fallbacks: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    #: Why the planner chose what it chose — one string per decision.
    reasons: list[str] = Field(default_factory=list)

    qc: dict[str, Any] | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None
    elapsed_sec: float | None = None
    #: Present when the result was produced by polling an async job.
    status: str | None = None
    progress: float | None = None

    @classmethod
    def failure(cls, code: str, message: str, **kwargs: Any) -> VideoResult:
        return cls(ok=False, error=message, error_code=code, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
