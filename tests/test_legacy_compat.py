"""The untouched legacy pipeline must stay importable and callable."""
from __future__ import annotations

from html_video_workflow.legacy.adapter import (
    legacy_templates,
    legacy_validate,
    load_legacy_module,
)
from html_video_workflow.providers.renderer.themes import LEGACY_THEMES


def test_legacy_module_loads() -> None:
    module = load_legacy_module()
    assert hasattr(module, "render_project")
    assert hasattr(module, "validate_project")


def test_legacy_templates_match_renderer_themes() -> None:
    """The 10 legacy templates must remain exactly available in the new renderer."""
    assert set(legacy_templates()) == set(LEGACY_THEMES)


def test_legacy_validate_accepts_demo_project(legacy_project_path) -> None:
    import json

    data = json.loads(legacy_project_path.read_text(encoding="utf-8"))
    legacy_validate(data)  # must not raise


def test_legacy_script_is_unmodified_path(repo_root) -> None:
    script = repo_root / "scripts" / "workflow.py"
    assert script.exists()
    text = script.read_text(encoding="utf-8")
    # The Foundation work must not have rewritten the legacy entry point.
    assert "def render_project(" in text
    assert "TEMPLATES = {" in text


def test_sapi_helper_still_present(repo_root) -> None:
    assert (repo_root / "scripts" / "sapi_tts.ps1").exists()
