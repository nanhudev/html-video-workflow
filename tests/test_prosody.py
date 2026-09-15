"""Prosody planner and audio quality tests.

The prosody planner is rule-based specifically so it can be tested like this:
deterministic input, deterministic output, and a rationale attached to every
decision. These tests encode the *intent* of each rule, so a future change that
makes narration read like a machine again fails here rather than in review.
"""
from __future__ import annotations

import pytest

from html_video_workflow.pipeline.prosody import (
    ProsodyPlanner,
    ProsodySettings,
    plan_prosody,
)


# ------------------------------------------------------------------ splitting
def test_terminal_punctuation_splits_into_segments():
    plan = plan_prosody("第一句。第二句。第三句。", language="zh-CN")
    assert [s.text for s in plan.segments] == ["第一句。", "第二句。", "第三句。"]


def test_full_stop_earns_a_longer_pause_than_a_comma():
    """This is the core anti-robotic rule: punctuation must have weight."""
    terminal = plan_prosody("先说明背景。", language="zh-CN")
    soft = plan_prosody("先说明背景，", language="zh-CN")
    assert terminal.segments[0].pause_after_ms > soft.segments[0].pause_after_ms


def test_decimal_is_not_a_sentence_boundary():
    plan = plan_prosody("模型只有 3.5 GB 显存。", language="zh-CN")
    assert len(plan.segments) == 1
    assert "3.5" in plan.segments[0].text


def test_abbreviation_is_not_a_sentence_boundary():
    plan = plan_prosody("The file is at e.g. this path.", language="en-US")
    # "e.g." must not split; only the final period ends the sentence.
    assert len(plan.segments) == 1


def test_closing_quote_stays_with_its_sentence():
    plan = plan_prosody('他说“这样才能赢。”然后离开了。', language="zh-CN")
    joined = "".join(s.text for s in plan.segments)
    assert "然后离开了。" in joined
    assert all("“" not in s.text or "”" in s.text for s in plan.segments)


def test_long_sentence_is_subdivided_for_breathing_room():
    text = (
        "这是一段非常长的句子，它在没有任何停顿的情况下持续了很久很久，"
        "而且中间没有任何让听众换气的地方，所以必须切开它。"
    )
    assert len(text) > 46, "sample must exceed the subdivision threshold"
    plan = plan_prosody(text, language="zh-CN")
    assert len(plan.segments) > 1
    assert all(len(s.text) <= 90 for s in plan.segments)


def test_subdivision_threshold_is_configurable():
    """A 42-character sentence is under the default 46, so nothing splits."""
    text = "这是一段非常长的句子，它持续了很久，而且没有任何停顿，听众会感到疲惫，所以需要切开。"
    assert len(text) < 46
    default = plan_prosody(text, language="zh-CN")
    eager = plan_prosody(text, language="zh-CN",
                         settings=ProsodySettings(max_segment_chars=20))
    assert len(default.segments) == 1
    assert len(eager.segments) > 1


def test_short_text_is_not_chopped_up():
    plan = plan_prosody("短句。", language="zh-CN")
    assert len(plan.segments) == 1


# ------------------------------------------------------------------ emphasis
def test_emphasis_cue_is_detected_and_slows_the_pace():
    plan = plan_prosody("问题真正出在这里。", language="zh-CN")
    segment = plan.segments[0]
    assert "真正" in segment.emphasis
    assert segment.pace < 1.0, "an emphasised line should be read slower, not faster"


def test_english_emphasis_cue_is_detected_case_insensitively():
    plan = plan_prosody("This is the critical part.", language="en-US")
    assert any(cue.lower() == "critical" for cue in plan.segments[0].emphasis)


def test_emphasis_does_not_invent_matches():
    plan = plan_prosody("今天天气不错。", language="zh-CN")
    assert plan.segments[0].emphasis == []


# -------------------------------------------------------------------- pauses
def test_first_segment_gets_a_lead_in_and_last_gets_a_tail():
    plan = plan_prosody("第一句。第二句。", language="zh-CN")
    assert plan.segments[0].pause_before_ms > 0
    assert plan.segments[-1].pause_after_ms > plan.segments[0].pause_after_ms


def test_middle_segments_do_not_double_count_the_gap():
    """Only pause_after is set mid-plan; counting both would open a hole."""
    plan = plan_prosody("第一句。第二句。第三句。", language="zh-CN")
    assert plan.segments[1].pause_before_ms == 0


def test_pause_scale_changes_every_pause_proportionally():
    fast = plan_prosody("第一句。第二句。", language="zh-CN",
                        settings=ProsodySettings(pause_scale=0.5))
    slow = plan_prosody("第一句。第二句。", language="zh-CN",
                        settings=ProsodySettings(pause_scale=2.0))
    assert slow.total_pause_ms > fast.total_pause_ms
    assert slow.segments[0].pause_after_ms == pytest.approx(
        fast.segments[0].pause_after_ms * 4, rel=0.35
    )


def test_global_pace_is_applied_on_top_of_per_segment_pace():
    normal = plan_prosody("第一句。", language="zh-CN")
    quicker = plan_prosody("第一句。", language="zh-CN",
                           settings=ProsodySettings(pace=1.2))
    assert quicker.segments[0].pace > normal.segments[0].pace


def test_drop_leading_pause_removes_the_opening_beat():
    """A scene following another should not restart with a fresh lead-in."""
    plan = plan_prosody("继续说明。", language="zh-CN",
                        settings=ProsodySettings(drop_leading_pause=True))
    assert plan.segments[0].pause_before_ms == 0


# ---------------------------------------------------------------- rationale
def test_every_segment_explains_itself():
    plan = plan_prosody("问题真正出在这里，而不是模型本身。", language="zh-CN")
    for segment in plan.segments:
        assert segment.rationale, "a pause with no stated reason cannot be debugged"


def test_rationale_names_the_punctuation_that_caused_the_pause():
    plan = plan_prosody("第一句。", language="zh-CN")
    assert "。" in plan.segments[0].rationale


# -------------------------------------------------------------------- bounds
def test_empty_text_yields_an_empty_plan_not_a_crash():
    plan = plan_prosody("   \n  ", language="zh-CN")
    assert plan.segments == []
    assert plan.total_pause_ms == 0


def test_whitespace_is_normalised_but_paragraph_structure_survives():
    plan = plan_prosody("第一段。\n\n\n第二段。", language="zh-CN")
    assert len(plan.segments) == 2
    assert not any("\n" in s.text for s in plan.segments)


def test_plan_text_round_trips_the_content():
    source = "本地优先的设计必须让每一步都可验证。"
    plan = plan_prosody(source, language="zh-CN")
    assert plan.text.replace(" ", "") == source.replace(" ", "")


def test_estimated_speech_ms_is_positive_and_grows_with_text():
    short = plan_prosody("短。", language="zh-CN")
    long = plan_prosody("这是一段明显更长的旁白文本，用来验证估计时长会随之增长。",
                        language="zh-CN")
    assert short.estimated_speech_ms() > 0
    assert long.estimated_speech_ms() > short.estimated_speech_ms()


def test_planner_is_deterministic():
    """Determinism is why this is rule-based; a flaky plan is an untestable one."""
    first = plan_prosody("问题真正出在这里，而不是模型本身。", language="zh-CN")
    second = plan_prosody("问题真正出在这里，而不是模型本身。", language="zh-CN")
    assert first.model_dump() == second.model_dump()


def test_emotion_is_carried_onto_every_segment():
    plan = plan_prosody("第一句。第二句。", language="zh-CN", emotion="calm")
    assert all(s.emotion == "calm" for s in plan.segments)


def test_planner_records_which_planner_produced_the_plan():
    assert plan_prosody("文本。").planner == "rule_based"


# -------------------------------------------------------- customisation
def test_custom_emphasis_cues_are_honoured():
    settings = ProsodySettings(emphasis_cues=("钱",))
    plan = ProsodyPlanner(settings).plan("这里的关键是钱。", language="zh-CN")
    assert "钱" in plan.segments[0].emphasis


def test_max_segment_chars_controls_subdivision_aggressiveness():
    text = "第一部分，第二部分，第三部分，第四部分，第五部分，结束。"
    eager = plan_prosody(text, settings=ProsodySettings(max_segment_chars=10))
    relaxed = plan_prosody(text, settings=ProsodySettings(max_segment_chars=200))
    assert len(eager.segments) >= len(relaxed.segments)
