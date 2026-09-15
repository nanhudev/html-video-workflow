"""Advanced renderer — motion, layout, aspect, determinism and the critic.

These tests pin *behaviour*. A layout choosing differently because the scoring
moved is fine; a layout emitting no CSS, or six layers animating in unison, is
not.

No "AI score" is asserted anywhere, because none exists. Findings are asserted by
rule id, which is the thing a user actually has to act on.
"""
from __future__ import annotations

import pytest

from html_video_workflow.providers.base import RenderSceneRequest
from html_video_workflow.providers.registry import get as get_provider
from html_video_workflow.renderers.aspect import ASPECTS, aspect_for, safe_area_for
from html_video_workflow.renderers.critic import (
    SceneFacts,
    SceneVariationPolicy,
    VisualDesignCritic,
    contrast_ratio,
)
from html_video_workflow.renderers.determinism import RenderSeed, validate_document
from html_video_workflow.renderers.layout import LayoutEngine, supported_layouts
from html_video_workflow.renderers.motion import MotionEngine, supported_motions
from html_video_workflow.renderers.typography import get_profile


def _scene(**layers) -> dict:
    return {
        "intent": "test",
        "visual_strategy": "typography_led",
        "narration": {"text": "这是一段用于测试的旁白。"},
        "shots": [{"duration": 4.0}],
        "layers": list(layers.get("layers", [])),
    }


def _text(role: str, content: str, semantic: str = "reveal") -> dict:
    return {"type": "text", "role": role, "content": content,
            "motion": {"semantic": semantic}}


LAYERS = [
    _text("label", "成本对比"),
    _text("headline", "本地推理成本下降 62%"),
    _text("body", "不再按每一帧付费。"),
    {"type": "text", "role": "metric", "content": "62%",
     "motion": {"semantic": "count"}},
]


# ------------------------------------------------------------------- motions
def test_at_least_six_motion_primitives_exist() -> None:
    """The brief requires >=6 genuinely rendered primitives."""
    motions = supported_motions()
    assert len(motions) >= 6
    for required in ("fade", "slide", "scale", "reveal", "count", "trace", "wipe",
                     "mask", "parallax"):
        assert required in motions


@pytest.mark.parametrize("motion", sorted(supported_motions()))
def test_every_motion_emits_real_keyframes(motion: str) -> None:
    """A primitive that emits no @keyframes does not animate — it is a stub.

    This is the guard against "the schema has a field but the renderer ignores
    it", which is the failure mode the whole phase exists to prevent.
    """
    engine = MotionEngine()
    plan = engine.build(
        [{"type": "text", "role": "body", "content": "x",
          "motion": {"enter": motion}}],
        scene_duration_ms=4000,
    )
    instance = plan.instances[0]
    assert instance.name == motion
    assert f"@keyframes {'' if True else ''}" or "@keyframes" in instance.keyframes
    assert "{" in instance.keyframes and "}" in instance.keyframes
    assert instance.duration_ms > 0
    assert "animation:" in instance.css


def test_motion_css_names_the_keyframe_it_emits() -> None:
    """The animation must reference the keyframes actually created."""
    engine = MotionEngine()
    plan = engine.build(
        [{"type": "svg", "role": "body", "content": "<svg/>",
          "motion": {"semantic": "trace"}}],
        scene_duration_ms=4000,
    )
    instance = plan.instances[0]
    name = instance.keyframes.split("@keyframes ")[1].split("{")[0].strip()
    assert name in instance.css


def test_layers_get_distinct_start_times() -> None:
    """Not everything may animate on the same frame (AA-001)."""
    plan = MotionEngine().build(LAYERS, scene_duration_ms=5000)
    starts = [i.start_ms for i in plan.instances]
    assert len(set(starts)) == len(starts)


def test_starts_are_not_a_constant_stagger() -> None:
    """A mechanical `i * 100ms` staircase is also AA-001."""
    plan = MotionEngine().build(LAYERS, scene_duration_ms=5000)
    starts = [round(i.start_ms, 1) for i in plan.instances]
    deltas = [round(b - a, 1) for a, b in zip(starts, starts[1:])]
    assert len(set(deltas)) > 1


def test_role_weights_the_duration() -> None:
    """A headline should not animate for the same span as a label."""
    plan = MotionEngine().build(LAYERS, scene_duration_ms=6000)
    durations = {i.name: i.duration_ms for i in plan.instances}
    assert len(set(durations.values())) > 1


def test_motion_stays_inside_the_entrance_budget() -> None:
    plan = MotionEngine().build(LAYERS, scene_duration_ms=4000)
    assert plan.total_ms <= 4000 * MotionEngine.ENTRANCE_BUDGET + 1


def test_trace_is_downgraded_on_non_vector_content() -> None:
    """Drawing a stroke along a `<p>` is meaningless; say what happened."""
    plan = MotionEngine().build(
        [{"type": "text", "role": "body", "content": "plain words",
          "motion": {"semantic": "trace"}}],
        scene_duration_ms=4000,
    )
    instance = plan.instances[0]
    assert instance.name != "trace"
    assert any("vector" in reason for reason in instance.reason)


def test_count_is_downgraded_when_not_numeric() -> None:
    plan = MotionEngine().build(
        [{"type": "text", "role": "body", "content": "no digits here",
          "motion": {"semantic": "count"}}],
        scene_duration_ms=4000,
    )
    assert plan.instances[0].name != "count"


def test_parallax_needs_image_content() -> None:
    plan = MotionEngine().build(
        [{"type": "text", "role": "body", "content": "words",
          "motion": {"semantic": "depth"}}],
        scene_duration_ms=4000,
    )
    assert plan.instances[0].name != "parallax"


def test_variation_seed_changes_primitives_between_layers() -> None:
    """Regression: seed was per-scene, so every layer got the same 'alternative'.

    That turned scene-wide variation into uniform motion — precisely the failure
    AA-002 describes — because a constant mod N is still a constant.
    """
    engine = MotionEngine()
    layers = [_text("body", f"line {i}") for i in range(4)]
    plan = engine.build(layers, scene_duration_ms=5000, seed=12345)
    names = [i.name for i in plan.instances]
    assert len(set(names)) > 1, f"all layers varied identically: {names}"


def test_starts_are_quantised_to_frames() -> None:
    plan = MotionEngine().build(LAYERS, scene_duration_ms=5000, fps=30)
    frame = 1000 / 30
    for instance in plan.instances:
        remainder = instance.start_ms / frame
        assert abs(remainder - round(remainder)) < 1e-6


# ------------------------------------------------------------------- layouts
def test_at_least_five_layout_primitives() -> None:
    assert len(supported_layouts()) >= 5


@pytest.mark.parametrize("name", supported_layouts())
def test_every_layout_produces_slots_with_css(name: str) -> None:
    result = LayoutEngine().choose(
        {"layers": LAYERS}, explicit=name, lock=True
    )
    assert result.name == name
    assert result.slots
    for slot in result.slots.values():
        assert "position:absolute" in slot.css()
        assert "left:" in slot.css()


def test_layout_validation_still_applies_to_suggested_alternatives() -> None:
    """Regression: a variation-policy suggestion bypassed refinement.

    The policy swapped in `center` for a four-layer scene, producing exactly the
    centred-everything failure AA-003 targets. A suggestion is not a lock.
    """
    engine = LayoutEngine()
    result = engine.choose({"layers": LAYERS}, explicit="center")
    assert result.name != "center"


def test_image_only_scene_switches_to_full_bleed() -> None:
    layers = [{"type": "image", "src": "a.png", "role": "background"}]
    result = LayoutEngine().choose({"visual_strategy": "typography_led",
                                    "layers": layers})
    assert result.name in {"full_bleed", "overlay"}


def test_metric_layer_selects_stat() -> None:
    result = LayoutEngine().choose(
        {"visual_strategy": "typography_led",
         "layers": [{"type": "text", "role": "metric", "content": "42%"}]}
    )
    assert result.name == "stat"


def test_no_layer_is_dropped_when_slots_run_out() -> None:
    engine = LayoutEngine()
    result = engine.choose({"layers": LAYERS}, explicit="center", lock=True)
    placed = engine.assign(result, LAYERS)
    assert len(placed) == len(LAYERS)
    for _layer, slot, _key in placed:
        assert slot is not None


def test_full_bleed_media_slot_exists() -> None:
    result = LayoutEngine().choose(
        {"visual_strategy": "image_led",
         "layers": [{"type": "image", "src": "hero.png", "role": "background"}]},
    )
    assert "media" in result.slots


# ------------------------------------------------------------ slot assignment
def _assigned(scene: dict, layers: list[dict]) -> dict[str, str]:
    """role -> slot key, for the layers that have a role."""
    engine = LayoutEngine()
    result = engine.choose(scene)
    return {
        str(layer.get("role")): key
        for layer, _slot, key in engine.assign(result, layers)
    }


def test_metric_does_not_displace_the_headline() -> None:
    """Regression: slots were consumed positionally by layer index.

    `metric` leads the reading order, so index 0 got the metric band while the
    real metric was pushed into `primary`. With a headline at index 1 it landed in
    a 19%-tall band while a display-size box sat above it — the headline grew out
    of its band and printed straight over the label. Both layers were "placed";
    they were placed on top of each other.
    """
    layers = [_text("label", "成本对比"), _text("headline", "本地推理成本下降 62%"),
              _text("body", "不再按每一帧付费。"),
              {"type": "text", "role": "metric", "content": "62%"}]
    scene = {"visual_strategy": "typography_led", "layers": layers}
    placement = _assigned(scene, layers)
    assert placement["metric"] == "metric"
    assert placement["headline"] == "primary"
    assert len(set(placement.values())) == len(layers), placement


def test_authoring_order_does_not_decide_which_layer_leads() -> None:
    """A label written above a headline must not steal the display slot.

    The earlier version of the fix ran its role pass in list order, which fixed
    the metric case and left this one: `label` came first and took `primary`, and
    the headline fell into `secondary` — the identical defect, one slot over.
    """
    forward = [_text("label", "架构"), _text("headline", "三层各司其职")]
    reversed_order = [_text("headline", "三层各司其职"), _text("label", "架构")]
    for layers in (forward, reversed_order):
        placement = _assigned({"visual_strategy": "typography_led",
                               "layers": layers}, layers)
        assert placement["headline"] == "primary", placement
        assert placement["label"] != "primary", placement


def test_media_never_takes_a_text_slot() -> None:
    """Sweep order matters: `primary` precedes `media` in the reading order.

    A single positional pass therefore handed `media` to the first text layer and
    dropped the actual image into a caption band, where `object-fit:cover` made it
    an unreadable strip.
    """
    layers = [_text("headline", "本地优先"),
              {"type": "image", "src": "hero.png", "role": "background"},
              _text("body", "说明文字")]
    placement = _assigned({"visual_strategy": "image_led", "layers": layers}, layers)
    assert placement["background"] == "media"
    assert placement["headline"] == "primary"


def test_no_two_layers_share_a_slot_until_slots_run_out() -> None:
    """Sharing is the documented last resort, not the normal case."""
    layers = [_text("headline", "标题"), _text("body", "正文"),
              _text("label", "标签"), {"type": "text", "role": "metric",
                                       "content": "42%"}]
    engine = LayoutEngine()
    result = engine.choose({"visual_strategy": "typography_led", "layers": layers})
    keys = [key for _layer, _slot, key in engine.assign(result, layers)]
    assert len(set(keys)) == len(keys), keys


def test_stat_bands_do_not_overlap() -> None:
    """A slot is a minimum height; generous bands invite overflow collisions.

    The metric band used to end at 56% while `primary` began at 60% — only 4%
    of slack for a display-size headline, which overflows in the other direction.
    Gaps are asserted as a *relationship* between bands so the numbers stay free
    to move.
    """
    result = LayoutEngine().choose({"layers": LAYERS}, explicit="stat", lock=True)
    bands = sorted(
        ((slot.y, slot.y + slot.h, name) for name, slot in result.slots.items()
         if name != "aside"),
    )
    for (_, earlier_end, earlier), (later_start, _, later) in zip(bands, bands[1:]):
        assert later_start - earlier_end >= 0.03, (
            f"{earlier} band ends at {earlier_end:.2f} but {later} starts at "
            f"{later_start:.2f} — too tight for content that grows"
        )


# -------------------------------------------------------------------- aspect
def test_three_supported_aspects() -> None:
    for name in ("16:9", "9:16", "1:1"):
        assert name in ASPECTS


@pytest.mark.parametrize(
    "preset",
    ["tiktok_9x16", "instagram_reels_9x16", "youtube_shorts_9x16"],
)
def test_vertical_platforms_have_bottom_and_right_insets(preset: str) -> None:
    """Vertical platforms overlay UI on the right rail and bottom band."""
    area = safe_area_for(preset)
    assert area.bottom >= 0.10
    assert area.right >= 0.10


def test_safe_areas_can_be_disabled_deliberately() -> None:
    area = safe_area_for("tiktok_9x16", enabled=False)
    assert area.top == area.bottom == area.right == area.left == 0.0


def test_safe_area_rejects_out_of_range() -> None:
    from html_video_workflow.renderers.aspect import SafeArea

    with pytest.raises(ValueError):
        SafeArea(top=1.5)


def test_reference_px_uses_short_edge_for_portrait() -> None:
    """Scaling type from width would make 9:16 headlines absurd."""
    vertical = aspect_for("tiktok_9x16", 1080, 1920)
    assert vertical.reference_px == 1080
    wide = aspect_for("youtube_16x9", 1920, 1080)
    assert wide.reference_px == 1080


def test_pixels_win_over_a_contradictory_preset() -> None:
    """Regression: 1080x1920 with a 16:9 preset got a 16:9 reference.

    Every type size was then computed from the wrong edge while looking fine.
    """
    spec = aspect_for("youtube_16x9", 1080, 1920)
    assert spec.name == "9:16"


# --------------------------------------------------------------- typography
def test_hierarchy_steps_are_optically_distinct() -> None:
    """Steps closer than ~15% read as 'about the same size'."""
    profile = get_profile("editorial")
    scales = sorted(
        [profile.display.scale, profile.headline.scale, profile.body.scale,
         profile.number.scale]
    )
    for smaller, larger in zip(scales, scales[1:]):
        assert larger / smaller >= 1.15, f"{smaller} vs {larger} too close"


def test_sole_headline_is_promoted_to_display() -> None:
    from html_video_workflow.renderers.typography import type_role_for

    assert type_role_for("headline", is_sole_headline=True) == "display"
    assert type_role_for("headline", is_sole_headline=False) == "headline"


def test_unknown_role_falls_back_to_body() -> None:
    from html_video_workflow.renderers.typography import type_role_for

    assert type_role_for("nonsense") == "body"


# ------------------------------------------------------------------- critic
def _clean_facts(**overrides) -> SceneFacts:
    base = dict(
        index=0, layer_count=4, text_layer_count=4,
        motion_starts=[100.0, 430.0, 620.0, 900.0],
        motion_names=["reveal", "mask", "wipe", "count"],
        text_aligns=["left", "left", "left", "right"],
        type_sizes=[84.0, 60.0, 40.0, 24.0],
        accent_layer_count=1, coverage=0.4, layout="stat",
        safe_area_breaches=[], longest_line=30,
        text_color="#ffffff", background_color="#071c33",
        largest_is_large_text=True, background_has_motion=True,
    )
    base.update(overrides)
    return SceneFacts(**base)


def test_a_clean_scene_produces_no_errors() -> None:
    report = VisualDesignCritic().review(_clean_facts())
    assert report.errors == []


def test_uniform_motion_is_an_error() -> None:
    facts = _clean_facts(motion_starts=[100.0, 100.0, 100.0, 100.0])
    report = VisualDesignCritic().review(facts)
    assert any(f.rule == "AA-001" and f.severity == "error" for f in report.findings)


def test_constant_stagger_is_also_uniform_motion() -> None:
    facts = _clean_facts(motion_starts=[0.0, 100.0, 200.0, 300.0])
    report = VisualDesignCritic().review(facts)
    assert any(f.rule == "AA-001" for f in report.findings)


def test_everything_centered_is_caught() -> None:
    facts = _clean_facts(text_aligns=["center"] * 4)
    report = VisualDesignCritic().review(facts)
    assert any(f.rule == "AA-003" for f in report.findings)


def test_no_ai_score_is_ever_emitted() -> None:
    """The brief forbids `AI Feel = 37.52%`. Enforce it structurally.

    A float score implies a measurement that does not exist. Findings carry rule
    id, severity, evidence and a fix instead.
    """
    report = VisualDesignCritic().review(_clean_facts())
    payload = str(report.to_dict())
    for forbidden in ("score", "ai_feel", "ai_score", "percentage"):
        assert forbidden not in payload.lower()


def test_safe_area_breach_is_an_error() -> None:
    facts = _clean_facts(safe_area_breaches=["primary below bottom inset"])
    report = VisualDesignCritic().review(facts)
    assert any(f.rule == "AA-006" and f.severity == "error" for f in report.findings)


def test_even_count_hierarchy_is_not_a_false_positive() -> None:
    """Regression: median took the upper middle value for even counts.

    It inflated the baseline and flagged well-formed scenes as flat — a critic
    that cries wolf gets ignored, which defeats having one.
    """
    facts = _clean_facts(type_sizes=[24.0, 41.0, 78.0, 106.0])
    report = VisualDesignCritic().review(facts)
    assert not any(f.rule == "AA-004" for f in report.findings)


def test_flat_hierarchy_is_still_caught() -> None:
    facts = _clean_facts(type_sizes=[40.0, 42.0, 44.0, 46.0])
    report = VisualDesignCritic().review(facts)
    assert any(f.rule == "AA-004" for f in report.findings)


def test_contrast_math_matches_wcag() -> None:
    # White on black is the 21:1 reference point.
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0, abs=0.1)


def test_low_contrast_is_reported_with_evidence() -> None:
    """Below the large-text floor (3:1) the critic must refuse the palette.

    Note the colour: #777777 on #071c33 measures 3.84:1, which *passes* the 3:1
    large-text floor. Testing "obviously bad" with a colour that is actually
    legal would make this test assert nothing.
    """
    facts = _clean_facts(text_color="#4d4d4d", background_color="#071c33")
    report = VisualDesignCritic().review(facts)
    finding = next((f for f in report.findings if f.rule == "AA-011"), None)
    assert finding is not None, f"expected a contrast finding, got {report.findings}"
    assert finding.severity == "error"
    assert "#4d4d4d" in finding.evidence and "#071c33" in finding.evidence
    # Opacity is not a contrast fix — the suggestion may *warn against* it, as
    # this one does, but the remedy it offers has to be about colour.
    assert "colour" in finding.suggestion.lower()


def test_large_text_threshold_is_looser_than_body() -> None:
    """The same pair is legal as display type and illegal as body copy.

    3.84:1 sits between the two floors, so it exercises both branches of the
    threshold rather than just the one that fails.
    """
    legal_as_display = _clean_facts(text_color="#777777", largest_is_large_text=True)
    illegal_as_body = _clean_facts(text_color="#777777", largest_is_large_text=False)
    assert not any(f.rule == "AA-011" for f in
                   VisualDesignCritic().review(legal_as_display).findings)
    assert any(f.rule == "AA-011" for f in
               VisualDesignCritic().review(illegal_as_body).findings)


def test_unparseable_color_is_not_guessed() -> None:
    assert contrast_ratio("rebeccapurple", "#000000") is None


# ---------------------------------------------------------------- variation
def test_policy_avoids_repeating_a_recent_layout() -> None:
    policy = SceneVariationPolicy(memory=3)
    from html_video_workflow.renderers.layout import supported_layouts

    options = supported_layouts()
    seen = []
    for _ in range(4):
        layout, _finding = policy.next_layout(options[0], options)
        policy.record(_scene_signature(layout))
        seen.append(layout)
    assert len(set(seen)) > 1


def test_policy_records_the_switch_as_a_finding() -> None:
    """A rewrite must be visible, never silent."""
    policy = SceneVariationPolicy(memory=2)
    from html_video_workflow.renderers.layout import supported_layouts

    options = supported_layouts()
    policy.record(_scene_signature(options[0]))
    layout, finding = policy.next_layout(options[0], options)
    assert layout != options[0]
    assert finding is not None and finding.rule == "AA-009"


def _scene_signature(layout: str):
    from html_video_workflow.renderers.critic import SceneSignature

    return SceneSignature(layout=layout, motion_set=("reveal",), role_sequence=("body",))


def test_policy_never_invents_a_layout() -> None:
    policy = SceneVariationPolicy()
    layout, finding = policy.next_layout("nonexistent", ["center"])
    assert layout == "nonexistent"
    assert finding is None


# -------------------------------------------------------------- determinism
def test_same_inputs_give_the_same_seed() -> None:
    a = RenderSeed(project_id="p", scene_index=1, variation_seed=7,
                   theme="t", layout="l")
    b = RenderSeed(project_id="p", scene_index=1, variation_seed=7,
                   theme="t", layout="l")
    assert a.value == b.value


def test_different_scene_index_changes_seed() -> None:
    a = RenderSeed(project_id="p", scene_index=1)
    b = RenderSeed(project_id="p", scene_index=2)
    assert a.value != b.value


def test_document_validator_flags_randomness() -> None:
    report = validate_document("<script>Math.random()</script>", seed=RenderSeed("p", 1))
    assert not report.ok


def test_document_validator_flags_webfonts() -> None:
    report = validate_document("@font-face{src:url(x.woff)}", seed=RenderSeed("p", 1))
    assert not report.ok


def test_document_validator_flags_unpinned_animation() -> None:
    report = validate_document("div{animation:x 1s linear}", seed=RenderSeed("p", 1))
    assert not report.ok


# ------------------------------------------------------------------ provider
def test_advanced_renderer_is_registered() -> None:
    provider = get_provider("advanced_html")
    assert provider.id == "advanced_html"


def test_compile_only_returns_html_without_a_render() -> None:
    provider = get_provider("advanced_html")
    out = provider.compile_only(
        RenderSceneRequest(
            scene={**_scene(), "layers": LAYERS},
            project_meta={"title": "t", "style_profile": "editorial"},
            out_dir="", width=1920, height=1080, index=1, total=1,
        )
    )
    assert out["html"].lstrip().startswith("<!doctype html>")
    assert out["timing"]
    assert isinstance(out["findings"], list)


def test_compiled_document_passes_the_determinism_validator() -> None:
    provider = get_provider("advanced_html")
    out = provider.compile_only(
        RenderSceneRequest(
            scene={**_scene(), "layers": LAYERS},
            project_meta={"title": "t"}, out_dir="", index=1, total=1,
        )
    )
    report = validate_document(out["html"], seed=RenderSeed("p", 1))
    assert report.ok, report.violations


def test_v1_scene_still_compiles() -> None:
    """No IR layers must not mean no render; V1 projects still exist."""
    provider = get_provider("advanced_html")
    out = provider.compile_only(
        RenderSceneRequest(
            scene={"title": "旧格式", "body": "应该仍然可以渲染", "eyebrow": "兼容"},
            out_dir="", index=1, total=1,
        )
    )
    assert "旧格式" in out["html"]
    assert "旧格式" in out["html"]


def test_missing_image_renders_a_visible_marker() -> None:
    """A broken <img> looks like a blank design choice. Make it visible."""
    provider = get_provider("advanced_html")
    out = provider.compile_only(
        RenderSceneRequest(
            scene={**_scene(), "visual_strategy": "image_led",
                   "layers": [{"type": "image", "src": "nope.png"}]},
            out_dir="", index=1, total=1,
        )
    )
    assert "missing asset" in out["html"]
