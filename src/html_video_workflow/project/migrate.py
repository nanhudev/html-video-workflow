"""V1 → V2 migration.

V1 is the project format consumed by ``scripts/workflow.py``
(``references/project-schema.md``). Migration is idempotent and keeps every
source URL, so provenance is never lost.
"""
from __future__ import annotations

import time
from typing import Any

from .ir import SCHEMA_VERSION, VideoProject


def detect_version(data: dict[str, Any]) -> int:
    version = data.get("schema_version")
    if isinstance(version, int):
        return version
    # V1 never declared a version; it always had a bare `scenes` list.
    if isinstance(data.get("scenes"), list):
        return 1
    return SCHEMA_VERSION


def needs_migration(data: dict[str, Any]) -> bool:
    return detect_version(data) < SCHEMA_VERSION


def _layer(role: str, content: Any, y: float, **extra: Any) -> dict[str, Any]:
    layer: dict[str, Any] = {
        "type": "text",
        "role": role,
        "content": str(content),
        "layout": {"x": 0.075, "y": y, "w": 0.7, "h": 0.18, "anchor": "top_left"},
        "motion": {"semantic": "reveal", "duration_ms": 560},
    }
    layer.update(extra)
    return layer


def migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Convert a legacy project dict into IR V2 (idempotent)."""
    if detect_version(data) >= SCHEMA_VERSION:
        return data

    scenes_out: list[dict[str, Any]] = []
    beats: list[dict[str, Any]] = []
    clock = 0.0
    legacy_scenes = data.get("scenes") or []
    for index, scene in enumerate(legacy_scenes, start=1):
        layers: list[dict[str, Any]] = []
        cursor = 0.16
        if scene.get("eyebrow"):
            layers.append(
                _layer(
                    "label",
                    scene["eyebrow"],
                    cursor,
                    layout={"x": 0.075, "y": cursor, "w": 0.5, "h": 0.06,
                            "anchor": "top_left"},
                    motion={"semantic": "reveal", "duration_ms": 420},
                    style={"color": "accent"},
                )
            )
            cursor = 0.24
        if scene.get("title"):
            layers.append(
                _layer(
                    "headline",
                    scene["title"],
                    cursor,
                    layout={"x": 0.075, "y": cursor, "w": 0.72, "h": 0.26,
                            "anchor": "top_left"},
                    motion={"semantic": "reveal", "duration_ms": 620, "delay_ms": 120},
                )
            )
            cursor += 0.3
        if scene.get("body"):
            layers.append(
                _layer(
                    "body",
                    scene["body"],
                    cursor,
                    layout={"x": 0.075, "y": cursor, "w": 0.68, "h": 0.2,
                            "anchor": "top_left"},
                    motion={"semantic": "reveal", "duration_ms": 560, "delay_ms": 260},
                    style={"color": "muted"},
                )
            )
        if scene.get("tags"):
            layers.append(
                _layer(
                    "annotation",
                    " · ".join(str(t) for t in scene["tags"]),
                    0.8,
                    layout={"x": 0.075, "y": 0.8, "w": 0.55, "h": 0.06,
                            "anchor": "bottom_left"},
                    motion={"semantic": "reveal", "duration_ms": 460, "delay_ms": 420},
                    style={"color": "accent"},
                )
            )
        if scene.get("metric"):
            layers.append(
                _layer(
                    "metric",
                    scene["metric"],
                    0.7,
                    layout={"x": 0.62, "y": 0.7, "w": 0.3, "h": 0.12,
                            "anchor": "bottom_right"},
                    motion={"semantic": "count", "duration_ms": 700, "delay_ms": 380},
                    style={"color": "accent"},
                )
            )
            if scene.get("metric_label"):
                layers.append(
                    _layer(
                        "annotation",
                        scene["metric_label"],
                        0.845,
                        layout={"x": 0.62, "y": 0.845, "w": 0.3, "h": 0.05,
                                "anchor": "bottom_right"},
                        motion={"semantic": "reveal", "duration_ms": 420, "delay_ms": 520},
                        style={"color": "muted"},
                    )
                )

        narration = scene.get("narration") or ""
        # V1 scenes had no explicit duration; keep a varied hint so rhythm is
        # not a uniform grid.
        duration = round(4.0 + 0.6 * ((index * 3) % 5), 2)
        beats.append(
            {
                "id": f"b{index}",
                "t": round(clock, 2),
                "kind": "claim" if index > 1 else "hook",
                "label": scene.get("eyebrow") or f"scene {index:02d}",
            }
        )
        clock += duration
        scenes_out.append(
            {
                "id": f"sc_{index}",
                "intent": scene.get("title") or None,
                "duration_hint_sec": duration,
                "narration": {
                    "text": narration,
                    "speaker": "narrator",
                    "language": data.get("language") or "zh-CN",
                    "emotion": "calm",
                    "pause_after_ms": 240,
                },
                "visual_strategy": "typography_led",
                "shots": [
                    {
                        "id": f"sh_{index}_1",
                        "start": 0.0,
                        "duration": duration,
                        "camera": {"type": "static"},
                        "layers": layers,
                    }
                ],
                # keep legacy fields for lossless round-trip
                "title": scene.get("title"),
                "body": scene.get("body"),
                "eyebrow": scene.get("eyebrow"),
                "tags": scene.get("tags", []),
                "metric": scene.get("metric"),
                "metric_label": scene.get("metric_label"),
            }
        )

    voice = data.get("voice") or {}
    migrated: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project": {
            "title": data.get("title") or "Untitled",
            "subtitle": data.get("subtitle"),
            "language": data.get("language") or "zh-CN",
            "video_type": "explainer",
            "style_profile": "editorial",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "sources": [
            {
                "id": f"src_{i}",
                "title": source.get("title"),
                "url": source.get("url"),
                "trust": "user_provided",
            }
            for i, source in enumerate(data.get("sources") or [], start=1)
        ],
        "brand": {"name": data.get("author") or "VIDEO RUNTIME"},
        "output": {"preset": "youtube_16x9", "width": 1280, "height": 720, "fps": 30},
        "story": {"logline": data.get("title"), "beats": beats},
        "sequences": [{"id": "sq_1", "intent": "migrated from V1", "scenes": scenes_out}],
        "audio": {
            "narration_voice": {
                "engine": voice.get("engine") or "sapi",
                "name": voice.get("name") or "",
                "rate": voice.get("rate", 0),
            },
            "loudness_target_lufs": -16.0,
        },
        "assets": {"items": []},
        "quality": {"checks": ["file_exists", "duration", "streams", "audio_level"]},
        "provenance": {
            "generator": "migrate_v1_to_v2",
            "created_by": "cli",
            "original": {"schema_version": 1},
        },
    }
    return migrated


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate any supported version to the current IR."""
    if detect_version(data) >= SCHEMA_VERSION:
        return data
    return migrate_v1_to_v2(data)


def load_project(data: dict[str, Any]) -> VideoProject:
    """Migrate (if needed) and validate into a V2 model."""
    return VideoProject.model_validate(migrate(data))
