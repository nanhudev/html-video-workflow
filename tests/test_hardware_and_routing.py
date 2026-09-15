"""Hardware profiling and routing explainability."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from html_video_workflow.hardware.profile import probe_hardware
from html_video_workflow.pipeline.router import plan_pipeline, rank, resolve_preset
from html_video_workflow.providers.base import ProviderType


def test_probe_returns_real_values() -> None:
    profile = probe_hardware(use_cache=False)
    assert profile.os
    assert profile.arch
    assert profile.cpu_logical_cores and profile.cpu_logical_cores > 0
    assert profile.probed_at is not None


def test_probe_does_not_invent_gpu_facts() -> None:
    profile = probe_hardware(use_cache=False)
    for gpu in profile.gpus:
        assert gpu.vendor in {"nvidia", "amd", "intel", "apple", "unknown", "software"}
        if gpu.vram_mb is not None:
            assert gpu.vram_mb > 0


def test_tooling_probe_reports_ffmpeg() -> None:
    profile = probe_hardware(use_cache=False)
    assert "ffmpeg" in profile.tooling
    tool = profile.tooling["ffmpeg"]
    if tool.available:
        assert tool.path and tool.version


def test_resolve_preset_is_a_known_preset() -> None:
    assert resolve_preset("auto") in {"fast", "balanced", "high_quality", "max_quality"}
    assert resolve_preset("fast") == "fast"


def test_rank_returns_reasons_for_every_candidate() -> None:
    decision = rank(ProviderType.TTS, preset="fast", language="zh-CN")
    assert decision.candidates
    for candidate in decision.candidates:
        assert candidate.reason, f"{candidate.id} has no reason"


def test_rank_rejects_missing_credential_provider() -> None:
    decision = rank(ProviderType.LLM, preset="balanced", language="zh-CN")
    by_id = {candidate.id: candidate for candidate in decision.candidates}
    assert "openai_compatible" in by_id
    assert by_id["openai_compatible"].score < 0
    assert any("credential" in reason.lower() for reason in by_id["openai_compatible"].reason)


def test_rank_prefers_available_provider() -> None:
    decision = rank(ProviderType.TTS, preset="fast", language="zh-CN")
    assert decision.selected is not None
    chosen = next(c for c in decision.candidates if c.chosen)
    assert chosen.score >= 0


def test_plan_returns_selection_and_reasons() -> None:
    plan = plan_pipeline(language="zh-CN", preset="auto")
    assert plan["preset"] in {"fast", "balanced", "high_quality", "max_quality"}
    for stage in ("llm", "tts", "renderer", "subtitle"):
        assert stage in plan["selection"]
        assert stage in plan["reasons"]
    assert plan["selection"]["renderer"] is not None


def test_plan_never_selects_unavailable_provider() -> None:
    plan = plan_pipeline(language="zh-CN", preset="high_quality")
    tts = plan["selection"]["tts"]
    assert tts is not None
    assert tts != "moss"  # moss binary is absent in CI


def test_unknown_language_can_still_route() -> None:
    decision = rank(ProviderType.TTS, preset="fast", language="xx-XX")
    assert decision.candidates


@pytest.mark.skipif(
    not sys.platform.startswith("win"),
    reason="drive-letter normalisation (/d/x -> D:/x) is a Windows concern; "
           "on POSIX a leading slash already means what it says")
def test_home_env_accepts_windows_posix_and_gitbash_paths() -> None:
    """`HVW_HOME` must not silently become a relative directory.

    Regression: `HVW_HOME=/d/html-video-workflow` (what Git Bash users type) was
    passed straight to `Path()`, which treats a leading slash as relative on
    Windows. The runtime then created a literal ``\\d\\html-video-workflow``
    directory inside the repository and wrote cache there, quietly filling the
    C: drive - the exact opposite of the "keep big files on D:" requirement.
    """
    import pytest

    from html_video_workflow.config.paths import _normalize_env_home

    assert _normalize_env_home("/d/html-video-workflow") == Path("D:/html-video-workflow")
    assert _normalize_env_home(r"D:\html-video-workflow") == Path("D:/html-video-workflow")
    assert _normalize_env_home("D:/html-video-workflow") == Path("D:/html-video-workflow")
    assert _normalize_env_home("  /e/hvw  ") == Path("E:/hvw")

    # A relative path is a configuration error, not something to guess at.
    with pytest.raises(ValueError, match="not an absolute path"):
        _normalize_env_home("html-video-workflow")
