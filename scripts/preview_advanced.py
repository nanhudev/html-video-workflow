"""Render sample frames with the advanced renderer so we can look at them."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "src")

os.environ.setdefault("HVW_HOME", "D:/html-video-workflow")

from html_video_workflow.providers.base import RenderSceneRequest  # noqa: E402
from html_video_workflow.providers.registry import get as get_provider  # noqa: E402

SCENES: list[dict] = [
    {
        "intent": "compare local vs cloud inference cost",
        "visual_strategy": "typography_led",
        "narration": {"text": "把推理搬回本地之后，每一帧不再向云端付费。"},
        "shots": [{"duration": 5.0}],
        "layers": [
            {"type": "text", "role": "label", "content": "成本对比",
             "motion": {"semantic": "reveal"}},
            {"type": "text", "role": "headline", "content": "本地推理成本下降 62%",
             "motion": {"semantic": "mask"}},
            {"type": "text", "role": "body", "content": "不再按每一帧付费。",
             "motion": {"semantic": "slide"}},
            {"type": "text", "role": "metric", "content": "62%",
             "motion": {"semantic": "count"}},
        ],
    },
    {
        "intent": "three pillars of the local pipeline",
        "visual_strategy": "typography_led",
        "narration": {"text": "决定交给代理，描述交给中间表示，执行交给提供者。"},
        "shots": [{"duration": 5.0}],
        "layers": [
            {"type": "text", "role": "label", "content": "架构",
             "motion": {"semantic": "fade"}},
            {"type": "text", "role": "headline", "content": "三层各司其职",
             "motion": {"semantic": "wipe"}},
            {"type": "text", "role": "body", "content": "代理决定\n中间表示描述\n提供者执行",
             "motion": {"semantic": "reveal"}},
        ],
    },
    {
        "intent": "a single number worth staring at",
        "visual_strategy": "typography_led",
        "narration": {"text": "八毫秒，一次本地旁白合成的全部延迟。"},
        "shots": [{"duration": 4.5}],
        "layers": [
            {"type": "text", "role": "headline", "content": "延迟",
             "motion": {"semantic": "fade"}},
            {"type": "text", "role": "metric", "content": "8 ms",
             "motion": {"semantic": "scale"}},
        ],
    },
]


def main() -> int:
    out = Path("D:/html-video-workflow/preview")
    out.mkdir(parents=True, exist_ok=True)
    provider = get_provider("advanced_html")
    manifest = []

    for index, scene in enumerate(SCENES, start=1):
        request = RenderSceneRequest(
            scene=scene,
            project_meta={"title": "advanced renderer preview",
                          "style_profile": "editorial",
                          "project_id": "prv_preview"},
            theme="editorial",
            out_dir=str(out),
            width=1600,
            height=900,
            index=index,
            total=len(SCENES),
        )
        response = provider.render_scene(request)
        manifest.append({
            "scene": index,
            "png": response.image_path,
            "metrics": response.metrics,
            "message": response.message,
        })
        print(f"scene {index}: {response.image_path}")
        print("   layout :", response.metrics.get("layout"))
        print("   motions:", response.metrics.get("motions"))
        print("   motion_ms:", response.metrics.get("motion_ms"))
        for finding in response.metrics.get("findings", []):
            print(f"   [{finding['severity']}] {finding['rule']}: {finding['message']}")

    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
