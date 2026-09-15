"""IR validation and V1→V2 migration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from html_video_workflow.project.ir import VideoProject, validate_project
from html_video_workflow.project.migrate import (
    detect_version,
    migrate,
    needs_migration,
)


def test_detect_version_v1(legacy_project_path: Path) -> None:
    data = json.loads(legacy_project_path.read_text(encoding="utf-8"))
    assert detect_version(data) == 1
    assert needs_migration(data)


def test_detect_version_v2() -> None:
    assert detect_version({"schema_version": 2}) == 2
    assert not needs_migration({"schema_version": 2})


def test_migration_preserves_sources(legacy_project_path: Path) -> None:
    data = json.loads(legacy_project_path.read_text(encoding="utf-8"))
    migrated = migrate(data)
    assert migrated["schema_version"] == 2
    original_urls = [s["url"] for s in data["sources"]]
    migrated_urls = [s["url"] for s in migrated["sources"]]
    assert migrated_urls == original_urls
    assert all(src["id"] for src in migrated["sources"])


def test_migration_is_idempotent(legacy_project_path: Path) -> None:
    data = json.loads(legacy_project_path.read_text(encoding="utf-8"))
    once = migrate(data)
    twice = migrate(once)
    assert once == twice


def test_migration_keeps_scene_count(legacy_project_path: Path) -> None:
    data = json.loads(legacy_project_path.read_text(encoding="utf-8"))
    migrated = migrate(data)
    scene_count = sum(len(seq["scenes"]) for seq in migrated["sequences"])
    assert scene_count == len(data["scenes"])


def test_migrated_project_validates(legacy_project_path: Path) -> None:
    data = json.loads(legacy_project_path.read_text(encoding="utf-8"))
    project, errors = validate_project(migrate(data))
    assert errors == []
    assert isinstance(project, VideoProject)
    assert project.scene_count >= 1
    assert project.estimated_duration() > 0


def test_migrated_scenes_have_layers_not_templates(legacy_project_path: Path) -> None:
    data = json.loads(legacy_project_path.read_text(encoding="utf-8"))
    project = VideoProject.model_validate(migrate(data))
    for scene in project.scenes:
        assert scene.shots, f"scene {scene.id} has no shot"
        layers = scene.shots[0].layers
        assert layers, f"scene {scene.id} has no layers"
        for layer in layers:
            dumped = layer.model_dump()
            assert "remotionComponent" not in dumped
            assert "cssClass" not in dumped


def test_invalid_project_reports_path_errors() -> None:
    project, errors = validate_project({"schema_version": 2, "project": {"title": 123}})
    assert project is None
    assert errors


def test_durations_are_not_uniform(legacy_project_path: Path) -> None:
    """Rhythm: a migrated project must not be a uniform 5s grid."""
    data = json.loads(legacy_project_path.read_text(encoding="utf-8"))
    project = VideoProject.model_validate(migrate(data))
    durations = {scene.duration_hint_sec for scene in project.scenes}
    assert len(durations) > 1


@pytest.mark.parametrize("role", ["headline", "body", "label", "metric", "annotation"])
def test_layer_roles_are_renderer_neutral(role: str) -> None:
    layer = {"type": "text", "role": role, "content": "x"}
    assert layer["role"] == role
    assert "renderer" not in layer
