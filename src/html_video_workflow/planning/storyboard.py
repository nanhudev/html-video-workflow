"""StoryboardPlanner — script beats → Video IR V2.

This is the only place a ``VideoProject`` is synthesised from a plan. It never
names a renderer: it sets ``visual_strategy`` and layer *roles*, and lets the
renderer's layout engine decide. That is what keeps the IR retargetable.
"""
from __future__ import annotations

import re

from ..core.request import CreateVideoRequest, PlatformPreset
from ..project.ir import VideoProject
from ..sources.document import SourceDocument
from ..templates.models import StyleProfile, TemplateManifest
from .script import ScriptBeat, VideoScript

# IR V2 ``Motion.semantic`` is a closed set. A manifest may *suggest* a richer
# vocabulary (the renderer has more primitives than the IR has semantics), so
# anything outside the set is dropped here rather than failing validation later.
_VALID_SEMANTICS = {
    "reveal", "count", "trace", "connect", "split", "depth", "progression",
    "focus", "drift",
}

_DIGITS = re.compile(r"\d+(?:\.\d+)?%?")

_STRATEGY_FOR_LAYOUT = {
    "stat": "data_led",
    "quote": "typography_led",
    "center": "typography_led",
    "editorial_left": "typography_led",
    "editorial_right": "typography_led",
    "split": "diagram_led",
    "diagram": "diagram_led",
    "full_bleed": "screen_led",
    "overlay": "screen_led",
}


class StoryboardPlanner:
    """Assembles the IR. Deterministic given (script, template, style, output)."""

    def build(
        self,
        script: VideoScript,
        *,
        manifest: TemplateManifest,
        style: StyleProfile,
        output: PlatformPreset,
        request: CreateVideoRequest,
        documents: list[SourceDocument] | None = None,
        video_type: str = "explainer",
    ) -> VideoProject:
        documents = documents or []
        motion_pool = [m for m in manifest.motion_vocabulary if m in _VALID_SEMANTICS] \
            or ["reveal"]
        scenes = []
        for index, beat in enumerate(script.beats, start=1):
            scenes.append(
                self._scene(index, beat, script, manifest, motion_pool, len(script.beats))
            )

        data: dict = {
            "schema_version": 2,
            "id": None,
            "project": {
                "title": (request.title or script.title or "未命名")[:80],
                "subtitle": (script.logline or "")[:120] or None,
                "language": script.language,
                "video_type": _safe_video_type(video_type),
                "style_profile": style.typography,
                "theme": style.theme,
            },
            "sources": [
                {
                    "id": doc.id,
                    "title": doc.title,
                    "url": doc.url,
                    "trust": doc.trust,
                    "retrieved_at": doc.retrieved_at,
                }
                for doc in documents
            ],
            "brand": {
                "name": (request.title or script.title or "")[:40] or None,
                "colors": dict(style.palette),
                "fonts": dict(style.fonts),
            },
            "output": {
                "preset": output.id if output.id in _IR_OUTPUT_PRESETS else "custom",
                "width": output.width,
                "height": output.height,
                "fps": output.fps,
                "captions": {
                    "mode": "burn_in" if request.captions else "none",
                    "format": "srt",
                    "position": "lower_third",
                    "safe_area": True,
                },
            },
            "story": {
                "logline": script.logline,
                "beats": [
                    {"id": beat.id, "t": _cumulative(script.beats, i), "kind": beat.kind,
                     "label": beat.label}
                    for i, beat in enumerate(script.beats)
                ],
            },
            "sequences": [{"id": "sq_1", "intent": script.logline or script.title,
                           "scenes": scenes}],
            "audio": {
                "narration_voice": {"provider": "auto",
                                     "voice": request.voice} if request.voice
                else {"provider": "auto"},
                "loudness_target_lufs": -16.0,
            },
            "assets": {"items": []},
            "quality": {"checks": ["file_exists", "duration", "streams", "audio_level"]},
            "provenance": {
                "generator": f"storyboard:{manifest.id}/{style.id}",
                "prompts": [request.intent_text[:400]] if request.intent_text else [],
                "providers": {},
                "created_by": request.created_by,
            },
        }
        return VideoProject.model_validate(data)

    # --------------------------------------------------------------- internals
    def _scene(self, index: int, beat: ScriptBeat, script: VideoScript,
               manifest: TemplateManifest, motion_pool: list[str],
               total: int) -> dict:
        semantic = motion_pool[(index - 1) % len(motion_pool)]
        layout = beat.layout or "editorial_left"
        layers: list[dict] = []

        layers.append({
            "type": "text",
            "role": "label",
            "content": f"{index:02d} / {beat.label}" if beat.label else f"{index:02d}",
            "layout": {"x": 0.075, "y": 0.14, "w": 0.5, "h": 0.05},
            "motion": {"semantic": "reveal", "duration_ms": 420},
            "style": {"color": "accent"},
        })

        headline = (beat.headline or script.topic or "").strip()
        layers.append({
            "type": "text",
            "role": "headline",
            "content": headline[:48],
            "layout": {"x": 0.075, "y": 0.26, "w": 0.68, "h": 0.24},
            "motion": {"semantic": _pick_semantic(beat, semantic),
                       "duration_ms": 640, "delay_ms": 120},
        })

        body = _on_screen_body(beat.narration)
        if body:
            layers.append({
                "type": "text",
                "role": "body",
                "content": body,
                "layout": {"x": 0.075, "y": 0.58, "w": 0.6, "h": 0.16},
                "motion": {"semantic": "reveal", "duration_ms": 560, "delay_ms": 260},
                "style": {"color": "muted"},
            })

        # A stat band without a number is a lie — only claim one when the
        # narration actually contains a figure worth promoting.
        number = _first_number(beat.narration)
        if layout == "stat" and number:
            layers.append({
                "type": "text",
                "role": "metric",
                "content": number,
                "layout": {"x": 0.08, "y": 0.22, "w": 0.55, "h": 0.26},
                "motion": {"semantic": "count", "duration_ms": 900, "delay_ms": 160},
                "style": {"color": "accent"},
            })
        elif layout == "diagram":
            layers.append({
                "type": "svg",
                "role": "annotation",
                "content": _svg_flow(headline or script.topic, index),
                "layout": {"x": 0.58, "y": 0.24, "w": 0.34, "h": 0.42},
                "motion": {"semantic": "trace", "duration_ms": 900, "delay_ms": 240},
                "style": {"color": "accent"},
            })
        else:
            layers.append({
                "type": "shape",
                "role": "background",
                "kind": "rule",
                "layout": {"x": 0.075, "y": 0.80, "w": 0.22, "h": 0.01},
                "motion": {"semantic": "progression", "duration_ms": 700, "delay_ms": 200},
                "style": {"color": "accent"},
            })

        return {
            "id": f"sc_{index}",
            "intent": beat.headline or beat.label or f"第 {index} 段",
            "duration_hint_sec": beat.duration_sec,
            "narration": {
                "text": beat.narration,
                "speaker": "narrator",
                "language": script.language,
                "emotion": _emotion_for(beat.kind),
                "pace": 1.0,
                "pause_after_ms": 320 if index < total else 600,
                "emphasis": beat.emphasis[:4],
                "voice": None,
            },
            "visual_strategy": _STRATEGY_FOR_LAYOUT.get(layout, "typography_led"),
            "transition": {"type": "cut", "duration_ms": 0},
            "shots": [{
                "id": f"sh_{index}_1",
                "start": 0.0,
                "duration": beat.duration_sec,
                "camera": {"type": "static"},
                "caption": {"text": _on_screen_body(beat.narration, 60),
                            "position": "lower_third", "safe_area": True},
                "layers": layers,
            }],
        }


_IR_OUTPUT_PRESETS = {
    "youtube_16x9", "youtube_shorts_9x16", "tiktok_9x16", "instagram_reels_9x16",
    "x_16x9", "bilibili_16x9", "xiaohongshu_3x4", "wechat_channels_9x16", "custom",
}

_SAFE_VIDEO_TYPES = {
    "explainer", "product_demo", "knowledge", "news", "data_story", "tutorial",
    "social_short", "essay", "documentary", "avatar_presenter", "music_visualizer",
    "custom",
}

_EMOTION_BY_BEAT = {
    "hook": "curious", "claim": "confident", "evidence": "measured",
    "tension": "serious", "payoff": "warm", "problem": "serious",
    "overview": "calm", "step": "calm", "recap": "warm",
    "headline_number": "measured", "supporting": "measured", "caveat": "serious",
    "pain": "serious", "capability": "confident", "walkthrough": "calm",
    "result": "warm", "turn": "curious", "proof": "measured", "cta": "warm",
    "definition": "calm", "why": "confident", "example": "calm",
    "boundary": "serious", "context": "calm", "development": "calm",
    "contrast": "serious", "detail": "measured", "close": "warm",
}


def _safe_video_type(value: str) -> str:
    return value if value in _SAFE_VIDEO_TYPES else "custom"


def _cumulative(beats: list[ScriptBeat], index: int) -> float:
    return round(sum(beat.duration_sec for beat in beats[:index]), 2)


def _emotion_for(kind: str) -> str:
    return _EMOTION_BY_BEAT.get(kind, "calm")


def _pick_semantic(beat: ScriptBeat, default: str) -> str:
    """Counting beats get the count animation; everything else follows the pool."""
    if beat.kind in {"headline_number", "result", "proof"} and _first_number(
            beat.narration):
        return "count"
    return default if default in _VALID_SEMANTICS else "reveal"


def _first_number(text: str) -> str | None:
    match = _DIGITS.search(text or "")
    return match.group(0) if match else None


def _on_screen_body(text: str, limit: int = 46) -> str:
    """One sentence maximum. A slide that repeats the whole narration is unreadable
    and, worse, makes the voiceover redundant."""
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if not cleaned:
        return ""
    sentence = re.split(r"(?<=[。！？.!?])\s*", cleaned)[0]
    if len(sentence) <= limit:
        return sentence
    # Cut on a clause boundary. This was `sentence[:limit-1] + "…"`, which put
    # "……去往别人的…" in the body column — a chopped word plus an ellipsis, the
    # clearest possible sign that a machine ran out of characters. When the
    # sentence has no boundary inside the budget, keep the *whole* clause and let
    # the layout engine's height auto-fit handle it: slightly long text reads
    # correctly, truncated text does not.
    window = sentence[:limit]
    for pivot in ("，", ",", "、", "：", ":", "；", ";", " ", "—"):
        cut = window.rfind(pivot)
        if cut >= max(8, limit // 4):
            return window[:cut].rstrip()
    return sentence


def _svg_flow(label: str, index: int) -> str:
    """A three-node flow diagram in ``currentColor``.

    Colours come from ``currentColor`` because the IR must not hard-code a
    palette: the renderer wraps this in a styled div, so the same markup reads
    correctly under any theme.
    """
    words = [w for w in re.split(r"[\s,，、]+", label or "") if w][:3] or ["A", "B", "C"]
    while len(words) < 3:
        words.append("—")
    boxes = []
    for i, word in enumerate(words):
        x = 8 + i * 92
        boxes.append(
            f'<rect x="{x}" y="46" width="76" height="40" rx="6" fill="none" '
            f'stroke="currentColor" stroke-width="1.5" opacity="{0.9 - i * 0.18}"/>'
            f'<text x="{x + 38}" y="71" text-anchor="middle" fill="currentColor" '
            f'font-size="13">{_escape_svg(word[:6])}</text>'
        )
        if i < 2:
            boxes.append(
                f'<line x1="{x + 76}" y1="66" x2="{x + 92}" y2="66" '
                f'stroke="currentColor" stroke-width="1.5" opacity="0.7"/>'
                f'<path d="M{x + 88} 62 L{x + 94} 66 L{x + 88} 70" fill="none" '
                f'stroke="currentColor" stroke-width="1.5" opacity="0.7"/>'
            )
    return (
        f'<svg viewBox="0 0 300 132" width="100%" height="100%" '
        f'preserveAspectRatio="xMidYMid meet" role="img" '
        f'aria-label="flow {index}">{"".join(boxes)}</svg>'
    )


def _escape_svg(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
