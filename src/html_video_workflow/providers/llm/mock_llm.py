"""MockLLM — deterministic offline planner used by tests and CI.

It produces a *valid* Video IR V2 project so the whole pipeline can be smoked
without any network access. Output is flagged ``mock`` everywhere it appears.
"""
from __future__ import annotations

import json
import re

from ..base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProbeResult,
    ProbeState,
    ProviderSpec,
)
from ..registry import register

_SCENE_TEMPLATES = (
    ("hook", "先换一个问题", "reveal"),
    ("claim", "核心判断是什么", "progression"),
    ("evidence", "可以验证的依据", "connect"),
    ("payoff", "下一步怎么做", "focus"),
)


#: Prompt wrappers used by the CLI/API when delegating to a planner.
_PROMPT_PREFIXES = (
    "create a short video project about:",
    "create a video project about:",
    "create a project about:",
)


def _topic_from(prompt: str) -> str:
    text = prompt.strip()
    for quote in ('"', '"', '"', "'"):
        if quote in text:
            parts = re.findall(rf"{quote}([^{quote}]+){quote}", text)
            if parts:
                return parts[0].strip()
    lowered = text.lower()
    for prefix in _PROMPT_PREFIXES:
        if lowered.startswith(prefix):
            return text[len(prefix):].strip()[:48]
    return text[:48].strip() or "未命名主题"


@register
class MockLLMProvider(LLMProvider):
    spec = ProviderSpec(
        id="mock_llm",
        type="llm",
        name="Mock LLM",
        vendor="html-video-workflow",
        version="1.0.0",
        local=True,
        implementation="inprocess",
        quality_score=0.0,
        speed_score=10.0,
        naturalness_score=0.0,
        startup_cost="low",
        install_state="builtin",
        tags=["mock", "ci", "offline"],
    )

    def probe(self) -> ProbeResult:
        return ProbeResult(state=ProbeState.READY, reason="Always available (mock)")

    def complete(self, request: LLMRequest) -> LLMResponse:
        topic = _topic_from(request.prompt)
        project = build_mock_project(topic)
        return LLMResponse(
            provider=self.id,
            text=json.dumps(project, ensure_ascii=False, indent=2),
            model="mock-llm-1",
            usage={"mock": True},
        )


def build_mock_project(topic: str, scenes: int = 4) -> dict:
    """Build a small but real IR V2 project, with editorial beats not equal timing."""
    chosen = list(_SCENE_TEMPLATES)[: max(1, min(scenes, len(_SCENE_TEMPLATES)))]
    sequence_scenes = []
    beats = []
    clock = 0.0
    for index, (kind, label, semantic) in enumerate(chosen, start=1):
        duration = round(3.4 + 0.9 * index, 2)  # deliberate variation
        beats.append(
            {"id": f"b{index}", "t": round(clock, 2), "kind": kind, "label": label}
        )
        clock += duration
        sequence_scenes.append(
            {
                "id": f"sc_{index}",
                "intent": f"{label}：{topic}",
                "duration_hint_sec": duration,
                "narration": {
                    "text": f"第 {index} 段。{topic}——{label}。",
                    "speaker": "narrator",
                    "language": "zh-CN",
                    "emotion": "calm",
                    "pace": round(0.94 + 0.02 * index, 2),
                    "pause_after_ms": 240 + 20 * index,
                    "emphasis": [label],
                },
                "visual_strategy": "typography_led",
                "shots": [
                    {
                        "id": f"sh_{index}_1",
                        "start": 0.0,
                        "duration": duration,
                        "camera": {"type": "static"},
                        "layers": [
                            {
                                "type": "text",
                                "role": "label",
                                "content": f"{index:02d} / {label}",
                                "layout": {"x": 0.075, "y": 0.16, "w": 0.5, "h": 0.05,
                                           "anchor": "top_left"},
                                "motion": {"semantic": "reveal", "duration_ms": 420},
                                "style": {"color": "accent"},
                            },
                            {
                                "type": "text",
                                "role": "headline",
                                "content": f"{label}",
                                "layout": {"x": 0.075, "y": 0.26, "w": 0.68, "h": 0.24,
                                           "anchor": "top_left"},
                                "motion": {"semantic": semantic, "duration_ms": 640,
                                           "delay_ms": 120},
                            },
                            {
                                "type": "text",
                                "role": "body",
                                "content": topic,
                                "layout": {"x": 0.075, "y": 0.56, "w": 0.6, "h": 0.16,
                                           "anchor": "top_left"},
                                "motion": {"semantic": "reveal", "duration_ms": 560,
                                           "delay_ms": 260},
                                "style": {"color": "muted"},
                            },
                            {
                                "type": "shape",
                                "role": "background",
                                "kind": "rule",
                                "layout": {"x": 0.075, "y": 0.78, "w": 0.22, "h": 0.01,
                                           "anchor": "bottom_left"},
                                "motion": {"semantic": "progression", "duration_ms": 700,
                                           "delay_ms": 200},
                                "style": {"color": "accent"},
                            },
                        ],
                    }
                ],
            }
        )
    return {
        "schema_version": 2,
        "id": None,  # assigned by the store so repeated runs never collide
        "project": {
            "title": topic,
            "subtitle": "Mock generated project",
            "language": "zh-CN",
            "video_type": "explainer",
            "style_profile": "editorial",
        },
        "sources": [],
        "brand": {"name": "VIDEO RUNTIME"},
        "output": {"preset": "youtube_16x9", "width": 1280, "height": 720, "fps": 30},
        "story": {"logline": topic, "beats": beats},
        "sequences": [{"id": "sq_1", "intent": "主序列", "scenes": sequence_scenes}],
        "audio": {"narration_voice": {"provider": "auto"}},
        "assets": {"items": []},
        "quality": {"checks": ["file_exists", "duration", "streams"]},
        "provenance": {"generator": "mock_llm", "created_by": "cli"},
    }
