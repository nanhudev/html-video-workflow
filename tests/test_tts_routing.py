"""Auto Router v1 — TTS-aware scoring, feature needs and fallback recording.

These tests pin the *behaviour* of the router rather than its numbers. A router
that selects a different provider because weights moved is fine; a router that
selects a placeholder for a job that asked for quality, or that drops a
fallback silently, is not.
"""
from __future__ import annotations

import pytest

from html_video_workflow.hardware.profile import GpuInfo, HardwareProfile
from html_video_workflow.pipeline.router import (
    PRESETS,
    QUALITY_TIER_SCORE,
    _fallback_order,
    _is_low_fidelity,
    _language_match,
    _tts_features,
    rank,
)
from html_video_workflow.providers.base import Capability, ProviderType


def _cpu_only() -> HardwareProfile:
    """A machine with no GPU — forces the VRAM hard filter to be a no-op."""
    return HardwareProfile(
        os="Windows",
        os_version="10",
        arch="AMD64",
        cpu_model="test",
        cpu_physical_cores=4,
        cpu_logical_cores=8,
        ram_total_mb=16384,
        ram_free_mb=8192,
        gpus=[GpuInfo(vendor="unknown", model=None, vram_mb=None)],
    )


# --------------------------------------------------------------- language match
def test_language_match_is_exact_when_region_agrees() -> None:
    kind, note = _language_match(["zh-CN", "en-US"], "zh-CN")
    assert kind == "exact"
    assert note and "zh-CN" in note


def test_language_match_rejects_a_different_region() -> None:
    """zh-TW is not zh-CN. Same script, different reading.

    Treating a shared language prefix as a match is how a Mandarin narration
    gets read with the wrong phonology and nobody notices until a native
    speaker listens to the finished video.
    """
    kind, note = _language_match(["zh-TW"], "zh-CN")
    assert kind == "none"
    assert note and "zh-CN" in note


def test_language_match_accepts_script_only_tag_as_loose() -> None:
    kind, note = _language_match(["zh", "en"], "zh-CN")
    assert kind == "prefix"
    assert note and "region may differ" in note


def test_language_match_is_unconstrained_without_a_request() -> None:
    kind, note = _language_match(["zh-CN"], None)
    assert kind == "unconstrained"
    assert note is None


def test_language_match_admits_when_support_is_undeclared() -> None:
    kind, note = _language_match([], "zh-CN")
    assert kind == "unknown"
    assert note == "language support undeclared"


def test_unconstrained_language_never_rejects_a_provider() -> None:
    decision = rank(ProviderType.TTS, preset="fast", language=None)
    assert decision.selected is not None


# ------------------------------------------------------------------ fidelity
def test_low_fidelity_is_read_from_spec_tags() -> None:
    class _Spec:
        tags = ["mock", "low_fidelity"]

    class _Provider:
        spec = _Spec()

    assert _is_low_fidelity(_Provider(), Capability(id="x", type=ProviderType.TTS))
    # A provider without the tag is not penalised, even if it is a mock.
    _Spec.tags = ["mock"]
    assert not _is_low_fidelity(_Provider(), Capability(id="x", type=ProviderType.TTS))


def _real_tts_available() -> bool:
    """Is there a TTS engine here that is not a placeholder?

    The claim under test is "a fidelity preset must not pick the mock". That
    only means something when a real engine exists to be picked instead — on a
    machine whose only engine *is* the mock (Linux has no SAPI), choosing it is
    the correct answer, and skipping is honest where passing would be a lie.
    """
    from html_video_workflow.providers.registry import capabilities

    return any(cap.available and cap.type == ProviderType.TTS
               and cap.id != "mock_tts" for cap in capabilities())


needs_real_tts = pytest.mark.skipif(
    not _real_tts_available(),
    reason="no non-placeholder TTS engine is available on this machine")


@needs_real_tts
@pytest.mark.parametrize("preset", ["high_quality", "max_quality"])
def test_quality_presets_never_choose_a_placeholder(preset: str) -> None:
    """A fidelity preset must not resolve to a mock engine.

    Regression: mock_tts won every preset on speed alone, because its
    ``speed_score=10`` outweighed the naturalness weighting. A user asking for
    ``high_quality`` was routed to a placeholder tone — the single most
    user-visible way a router can be wrong while looking successful.
    """
    decision = rank(ProviderType.TTS, preset=preset, language="zh-CN",
                    hardware=_cpu_only())
    assert decision.selected is not None
    assert decision.selected != "mock_tts"


def test_a_placeholder_is_never_a_destination_while_anything_real_is_left() -> None:
    """`low_fidelity` means "pick me only if nothing real is left".

    This replaces an earlier test that asserted the opposite — that `fast` may
    pick the mock because speed is its point. That was the wrong contract. A
    placeholder does not produce fast speech, it produces *no* speech: the tone
    it writes is the right length, so audio QC passes and the render reports
    success, and the only trace is one word in a provider list. `mock_tts`
    scores 10/10 on speed, which was enough to beat a genuine engine under
    `balanced` and `fast` — so on this machine a Chinese request was narrated by
    a beep while an installed zh-CN voice sat unused.
    """
    decision = rank(ProviderType.TTS, preset="fast", language="zh-CN",
                    hardware=_cpu_only())
    if not _real_tts_available():
        pytest.skip("no real TTS engine here, so only the mock could be chosen")
    assert decision.selected is not None
    assert decision.selected != "mock_tts"
    chosen = next(c for c in decision.candidates if c.chosen)
    assert not chosen.placeholder
    assert any("last resort, never a destination" in reason
               for reason in chosen.reason)


def test_the_placeholder_survives_as_the_last_resort(monkeypatch) -> None:
    """When nothing real is usable, the pipeline must still run.

    The rule above must not be implemented by removing placeholders from the
    pool — that would leave a machine with nothing installed unable to render at
    all. This is the other half of the guarantee, and it is asserted against a
    pool containing only placeholders so it holds on any machine.
    """
    from html_video_workflow.pipeline import router as router_module
    from html_video_workflow.providers.registry import get as get_provider

    mock = get_provider("mock_tts")
    monkeypatch.setattr(router_module, "by_type", lambda _type: [mock])

    decision = rank(ProviderType.TTS, preset="balanced", language="zh-CN",
                    hardware=_cpu_only())
    assert decision.selected == "mock_tts"
    chosen = next(c for c in decision.candidates if c.chosen)
    assert chosen.placeholder


def test_renderer_quality_preset_avoids_the_placeholder() -> None:
    decision = rank(ProviderType.RENDERER, preset="high_quality", hardware=_cpu_only())
    assert decision.selected is not None
    assert decision.selected != "mock_renderer"


def test_low_fidelity_penalty_scales_with_the_preset() -> None:
    """The demotion stays a weight; the *selection rule* is what guarantees it.

    The two are complementary, not alternatives. The weight orders providers
    inside the pool, which is what makes the explanation read sensibly. The rule
    — a placeholder cannot be chosen while something real is usable — is what
    makes the guarantee hold, because a weight can always be outscored and
    `mock_tts`'s speed score is high enough to do exactly that.
    """
    assert PRESETS["fast"].fidelity_penalty == 0.0
    assert PRESETS["high_quality"].fidelity_penalty > PRESETS["balanced"].fidelity_penalty
    assert PRESETS["max_quality"].fidelity_penalty > PRESETS["high_quality"].fidelity_penalty


# ------------------------------------------------------------------- features
def test_tts_features_only_counts_an_explicit_yes() -> None:
    """`unknown` is not support.

    A provider that has not declared emotion support must not win a scoring
    round for emotion — otherwise a request routes to an engine that will drop
    the field, and the loss is invisible until someone watches the video.
    """
    capability = Capability(
        id="x",
        type=ProviderType.TTS,
        details={
            "supports_emotion": "yes",
            "supports_style": "unknown",
            "supports_pitch": "no",
        },
    )
    features = _tts_features(capability)
    assert features["supports_emotion"] is True
    assert features["supports_style"] is False
    assert features["supports_pitch"] is False
    # Undeclared keys default to unsupported rather than to a guess.
    assert features["supports_voice_clone"] is False


def test_missing_feature_is_reported_and_never_silent() -> None:
    """A downranked provider must stay visible with the reason it lost."""
    decision = rank(
        ProviderType.TTS, preset="high_quality", language="zh-CN",
        needs=["emotion"], hardware=_cpu_only(),
    )
    chosen = next(c for c in decision.candidates if c.chosen)
    on_this_machine = {
        "sapi", "mock_tts", "aivisspeech", "neural_sidecar", "openai_compatible_tts",
    }
    if chosen.id in on_this_machine and not _supports(chosen, "emotion"):
        assert any("cannot apply" in reason for reason in chosen.reason)


def _supports(candidate, feature: str) -> bool:
    assert candidate.capability is not None
    return str(candidate.capability.details.get(f"supports_{feature}", "no")).lower() == "yes"


def test_requesting_features_never_makes_a_stage_impossible() -> None:
    """Needs are a preference, not a filter.

    A stage that cannot satisfy an optional feature must still run — degrading
    audibly beats producing no video at all.
    """
    decision = rank(
        ProviderType.TTS, preset="fast", language="zh-CN",
        needs=["emotion", "style", "voice_clone"], hardware=_cpu_only(),
    )
    assert decision.selected is not None
    assert decision.candidates


# ------------------------------------------------------------------ fallbacks
def test_fallback_order_prefers_the_declared_chain() -> None:
    """The declared chain encodes a deliberate degradation order."""
    candidates = [
        type("C", (), {"id": pid, "score": 1.0})() for pid in ("sapi", "aivisspeech")
    ]
    order = _fallback_order("tts", "mock_tts", candidates)
    assert order[:2] == ["aivisspeech", "sapi"]


def test_fallback_order_appends_undeclared_but_available_providers() -> None:
    """A project must not be stranded because its engine is not in the list."""
    candidates = [
        type("C", (), {"id": pid, "score": 1.0})() for pid in ("sapi", "custom_engine")
    ]
    order = _fallback_order("tts", "mock_tts", candidates)
    assert "custom_engine" in order
    assert order[-1] == "custom_engine"


def test_fallback_order_excludes_the_selected_provider() -> None:
    candidates = [type("C", (), {"id": pid, "score": 1.0})() for pid in ("sapi",)]
    assert "sapi" not in _fallback_order("tts", "sapi", candidates)


def test_fallback_order_ignores_rejected_candidates() -> None:
    candidates = [
        type("C", (), {"id": "mostly_broken", "score": -1.0})(),
        type("C", (), {"id": "sapi", "score": 3.0})(),
    ]
    order = _fallback_order("tts", "mock_tts", candidates)
    assert "mostly_broken" not in order
    assert order == ["sapi"]


def test_decision_carries_a_fallback_list() -> None:
    decision = rank(ProviderType.TTS, preset="balanced", language="zh-CN")
    assert isinstance(decision.fallbacks, list)
    assert decision.selected not in decision.fallbacks


# ------------------------------------------------------------------ hierarchy
def test_a_fidelity_preset_ranks_a_natural_engine_above_a_fast_robotic_one() -> None:
    """The narration tradeoff a user did not ask for.

    ``speech_naturalness`` stacks on the generic naturalness weight for TTS, so
    a fast robotic engine cannot out-score a natural one at the same quality
    tier. Without it, ``balanced`` was decided by speed alone.
    """
    assert PRESETS["high_quality"].speech_naturalness > 0
    assert PRESETS["max_quality"].speech_naturalness > PRESETS["high_quality"].speech_naturalness
    # The tier scale must stay monotonic for the inference to be meaningful.
    tiers = ["robotic", "basic", "good", "high", "studio"]
    scores = [QUALITY_TIER_SCORE[t] for t in tiers]
    assert scores == sorted(scores)
    assert QUALITY_TIER_SCORE["none"] < QUALITY_TIER_SCORE["robotic"]


# ------------------------------------------------------------------ decisions
def test_decision_is_serialisable_and_explains_itself() -> None:
    decision = rank(ProviderType.TTS, preset="balanced", language="zh-CN")
    payload = decision.to_dict()
    assert payload["stage"] == "tts"
    assert payload["selected"] is not None
    for candidate in payload["candidates"]:
        assert candidate["reason"], f"{candidate['id']} lost without a reason"
        # Exposed so a caller — the Studio, the API, a support ticket — can tell
        # a real engine from a stand-in without re-deriving it from tags.
        assert "placeholder" in candidate


def test_locked_provider_wins_regardless_of_score() -> None:
    """A user lock is an instruction, not a suggestion."""
    decision = rank(
        ProviderType.TTS, preset="high_quality", language="zh-CN",
        locked="mock_tts", hardware=_cpu_only(),
    )
    assert decision.selected == "mock_tts"
    chosen = next(c for c in decision.candidates if c.chosen)
    assert any("locked" in reason for reason in chosen.reason)


def test_every_candidate_gets_a_reason_even_when_rejected() -> None:
    """`Rejected` without a reason leaves the user with nothing to fix."""
    decision = rank(ProviderType.TTS, preset="balanced", language="zh-CN")
    for candidate in decision.candidates:
        assert candidate.reason, f"{candidate.id} produced no explanation"


def test_preset_named_provider_never_appears_in_a_preset() -> None:
    """A preset is weights, never a provider name.

    The moment ``high_quality`` means "pick Fish Speech", the router becomes a
    lookup table that goes stale every time a new engine ships.
    """
    provider_names = {
        "sapi", "mock_tts", "moss", "aivisspeech", "neural_sidecar",
        "openai_compatible_tts", "fish_speech", "cosyvoice", "mock_renderer",
        "legacy_html", "advanced_html",
    }
    for preset, weights in PRESETS.items():
        for value in weights.__dict__.values():
            assert not (isinstance(value, str) and value in provider_names), (
                f"preset {preset} names a provider: {value}"
            )
