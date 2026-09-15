"""Provider registry, honesty of probes and capability semantics."""
from __future__ import annotations

from html_video_workflow.providers import registry
from html_video_workflow.providers.base import (
    Capability,
    ProbeState,
    ProviderSpec,
    ProviderType,
)
from html_video_workflow.providers.renderer.document import build_scene_document
from html_video_workflow.providers.renderer.themes import LEGACY_THEMES, theme_ids


def test_builtin_providers_load() -> None:
    providers = registry.all_providers()
    ids = {provider.id for provider in providers}
    assert {"mock_llm", "mock_tts", "mock_renderer", "srt", "local_asset"} <= ids


def test_every_provider_declares_a_spec() -> None:
    for provider in registry.all_providers():
        assert isinstance(provider.spec, ProviderSpec)
        assert provider.spec.id == provider.id
        assert isinstance(provider.spec.type, ProviderType)


def test_probe_returns_a_state() -> None:
    for provider in registry.all_providers():
        result = provider.probe()
        assert isinstance(result.state, ProbeState)
        assert result.reason, f"{provider.id} probe returned no reason"
        assert result.available == (result.state == ProbeState.READY)


def test_missing_binary_is_not_reported_as_ready(monkeypatch) -> None:
    """A provider whose binary is absent must never claim readiness."""
    monkeypatch.setenv("MOSS_TTS_COMMAND", "definitely-not-installed-binary-xyz")
    moss = registry.get("moss")
    result = moss.probe()
    assert result.state == ProbeState.NOT_INSTALLED
    assert not result.available


def test_missing_api_key_is_missing_credentials() -> None:
    provider = registry.get("openai_compatible")
    result = provider.probe()
    assert result.state == ProbeState.MISSING_CREDENTIALS
    assert not result.available


def test_capability_cannot_upgrade_spec() -> None:
    provider = registry.get("mock_tts")
    capability = provider.capabilities()
    assert capability.quality_score <= provider.spec.quality_score
    assert capability.available is True


def test_mock_capability_is_marked_mock() -> None:
    spec = registry.get("mock_tts").spec
    assert "mock" in spec.tags


def test_legacy_themes_are_preserved() -> None:
    assert len(LEGACY_THEMES) == 10
    assert "academic-blue" in LEGACY_THEMES


def test_scene_document_is_renderer_neutral_html() -> None:
    theme = LEGACY_THEMES["academic-blue"]
    scene = {
        "layers": [
            {
                "type": "text",
                "role": "headline",
                "content": "Hello",
                "layout": {"x": 0.1, "y": 0.3, "w": 0.6, "h": 0.2, "anchor": "top_left"},
                "motion": {"semantic": "reveal"},
            }
        ]
    }
    html = build_scene_document(scene, theme, {"title": "T"}, width=1280, height=720)
    assert "<!doctype html>" in html
    assert "Hello" in html
    assert "remotion" not in html.lower()


def test_semantic_motion_is_not_a_uniform_fade() -> None:
    theme = LEGACY_THEMES["cinematic-dark"]
    semantics = ["count", "trace", "split"]
    frames = []
    for semantic in semantics:
        html = build_scene_document(
            {"layers": [{"type": "text", "role": "metric", "content": "1",
                         "motion": {"semantic": semantic}}]},
            theme,
            {},
        )
        frames.append(html)
    assert len({*frames}) == len(frames)


def test_unknown_provider_raises() -> None:
    from html_video_workflow.providers.base import ProviderError

    try:
        registry.get("does_not_exist")
    except ProviderError as exc:
        assert "does_not_exist" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ProviderError")


def test_capability_model_has_documented_scores() -> None:
    capability = Capability(id="x", type=ProviderType.TTS, available=True,
                            quality_score=8.2, speed_score=8.5, naturalness_score=8.6)
    assert capability.quality_score == 8.2
    assert capability.startup_cost in {"low", "medium", "high"}
