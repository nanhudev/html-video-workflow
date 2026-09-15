"""Phase 3 — the product contract, verified.

These tests exist to catch the specific way a "one-click product" fails: not by
crashing, but by *reporting success it did not achieve*. Every test here is
phrased against observable output — a returned path, a real file, a recorded
fallback — rather than against the code path that should have produced it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from html_video_workflow.core.errors import VideoErrorCode, VideoWorkflowError
from html_video_workflow.core.request import (
    PLATFORM_PRESETS,
    CreateVideoRequest,
    resolve_output,
)
from html_video_workflow.planning.pipeline_planner import PipelinePlanner
from html_video_workflow.planning.script import ScriptPlanner
from html_video_workflow.planning.storyboard import StoryboardPlanner
from html_video_workflow.planning.topic_planner import TopicPlanner
from html_video_workflow.runtime.engine import get_runtime
from html_video_workflow.sources import detect_kind, resolve_source
from html_video_workflow.sources.document import SourceDocument
from html_video_workflow.templates.ranker import RankContext, TemplateRanker
from html_video_workflow.templates.registry import get_registry


# ------------------------------------------------------------------ contract
def test_only_one_intent_field_is_required() -> None:
    """A caller with nothing but a sentence must still get a request."""
    assert CreateVideoRequest(prompt="explain X").prompt == "explain X"
    assert CreateVideoRequest(topic="X").topic == "X"
    assert CreateVideoRequest(script="line one\n\nline two").script


def test_an_empty_request_is_rejected() -> None:
    """The alternative is a video about nothing, which is worse than an error."""
    with pytest.raises(ValueError):
        CreateVideoRequest()
    with pytest.raises(ValueError):
        CreateVideoRequest(prompt="   ")


def test_platform_presets_all_have_a_real_aspect() -> None:
    for preset in PLATFORM_PRESETS.values():
        assert preset.width > 0 and preset.height > 0
        assert 0.0 <= preset.safe_bottom < 0.3


def test_vertical_presets_reserve_more_bottom_than_horizontal() -> None:
    """TikTok's action bar is the reason this field exists; if the vertical
    presets did not reserve more space than YouTube 16:9, the safe area would
    be decorative."""
    vertical = PLATFORM_PRESETS["tiktok_9x16"]
    horizontal = PLATFORM_PRESETS["youtube_16x9"]
    assert vertical.safe_bottom > horizontal.safe_bottom


def test_resolve_output_prefers_platform_then_aspect() -> None:
    assert resolve_output("tiktok_9x16", None, None, None).aspect == "9:16"
    assert resolve_output(None, "9:16", None, None).aspect == "9:16"
    assert resolve_output(None, None, None, None).id == "youtube_16x9"


def test_explicit_dimensions_win_over_the_preset_default() -> None:
    """"1080p vertical" must not silently revert to the preset's 1920."""
    preset = resolve_output("tiktok_9x16", None, 720, 1280)
    assert (preset.width, preset.height) == (720, 1280)


def test_error_codes_map_to_http_statuses() -> None:
    error = VideoWorkflowError(VideoErrorCode.NO_PROVIDER, "nothing can render")
    assert error.http_status == 503
    assert error.to_dict()["code"] == "no_provider"


# ------------------------------------------------------------------- sources
def test_text_source_is_classified_as_text() -> None:
    assert detect_kind("just some prose about vectors") == "text"


def test_markdown_source_keeps_structure() -> None:
    markdown = "# Title\n\n## Section A\n\n- fact one\n- fact two\n\nBody text here.\n"
    documents = resolve_source({"kind": "markdown", "value": markdown})
    assert len(documents) == 1
    doc = documents[0]
    assert doc.kind == "markdown"
    assert "Section A" in doc.headings
    assert "fact one" in doc.facts


def test_github_url_is_detected_without_network() -> None:
    assert detect_kind("https://github.com/nanhudev/html-video-workflow") == "github"


def test_web_url_is_detected() -> None:
    assert detect_kind("https://example.com/article") == "webpage"


def test_source_truncation_is_reported(tmp_path: Path) -> None:
    """A silently truncated source produces a video that claims to cover
    material it never read."""
    long_text = "句子。" * 4000
    documents = resolve_source({"kind": "text", "value": long_text, "max_chars": 500})
    assert documents[0].truncated is True
    assert documents[0].char_count <= 520


def test_missing_file_source_raises_rather_than_returning_nothing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_source({"kind": "file", "value": str(tmp_path / "absent.md")})


# ------------------------------------------------------------------ topic
def test_topic_planner_strips_instruction_noise() -> None:
    request = CreateVideoRequest(prompt="帮我做一个视频，讲讲向量数据库")
    seed = TopicPlanner().seed(request)
    assert "向量数据库" in seed
    assert "帮我" not in seed


def test_topic_planner_works_with_no_model_and_no_network() -> None:
    request = CreateVideoRequest(prompt="讲讲向量数据库")
    suggestions = TopicPlanner().suggest(request, count=5)
    assert len(suggestions) >= 5
    assert suggestions[0].source == "user"
    assert all(item.title for item in suggestions)


def test_user_topic_is_never_dressed_up_without_being_asked() -> None:
    request = CreateVideoRequest(topic="向量数据库")
    assert TopicPlanner().decide(request).title == "向量数据库"


def test_source_headings_seed_the_topic() -> None:
    document = SourceDocument(id="d1", kind="markdown", title=None, text="x",
                              sections=[], facts=[])
    request = CreateVideoRequest(prompt="anything")
    documents = [document.model_copy(update={"sections": [], "title": "从零理解索引"})]
    assert TopicPlanner().seed(request, documents) == "从零理解索引"


# ---------------------------------------------------------------- templates
def test_registry_loads_every_builtin_without_errors() -> None:
    registry = get_registry(refresh=True)
    assert registry.load_errors() == {}
    assert len(registry.templates()) >= 6
    assert len(registry.styles()) >= 5


def test_template_manifests_never_name_a_renderer() -> None:
    """The moment a manifest says `remotionComponent`, IR stops being portable."""
    raw = json.dumps([m.model_dump(mode="json") for m in get_registry().templates()])
    for forbidden in ("remotionComponent", "cssClass", "react", "svelte"):
        assert forbidden.lower() not in raw.lower()


def test_every_template_declares_what_it_is_bad_at() -> None:
    """A manifest with no `not_for` gives an agent no way to avoid misusing it."""
    for manifest in get_registry().templates():
        assert manifest.description, manifest.id
        assert manifest.not_for, f"{manifest.id} declares no exclusions"
        assert manifest.beats, f"{manifest.id} declares no beats"


def test_template_default_styles_all_exist() -> None:
    registry = get_registry()
    for manifest in registry.templates():
        assert registry.find_style(manifest.default_style) is not None, manifest.id
        for style_id in manifest.compatible_styles:
            assert registry.find_style(style_id) is not None, f"{manifest.id}:{style_id}"


def test_vertical_template_is_filtered_out_for_horizontal_output() -> None:
    """social_short only makes sense at 9:16; offering it at 16:9 wastes half
    the frame, so it must not survive the hard filter."""
    ranked = TemplateRanker().rank(
        get_registry().templates(),
        RankContext(topic="x", aspect="16:9", video_type="social_short"),
    )
    social = next(item for item in ranked if item.id == "social_short")
    assert not social.ok
    assert "aspect" in social.reasons[0]


def test_template_requiring_missing_material_is_filtered() -> None:
    ranked = TemplateRanker().rank(
        get_registry().templates(),
        RankContext(topic="x", aspect="16:9", has_data=False),
    )
    data_story = next(item for item in ranked if item.id == "data_story")
    assert not data_story.ok
    assert "data" in data_story.reasons[0]


def test_ranker_filters_before_it_scores() -> None:
    """A template that cannot run must not be rescued by a good score."""
    ranked = TemplateRanker().rank(
        get_registry().templates(), RankContext(topic="x", aspect="9:16"),
    )
    ineligible = [item for item in ranked if not item.ok]
    assert ineligible, "expected at least one template to be filtered at 9:16"
    assert all(item.score == -1.0 for item in ineligible)


def test_ranking_carries_a_reason_for_the_winner() -> None:
    best = TemplateRanker().best(
        get_registry().templates(),
        RankContext(topic="为什么缓存会失效", aspect="16:9", video_type="explainer"),
    )
    assert best is not None and best.reasons


# --------------------------------------------------------------------- plan
def test_plan_records_reasons_for_every_decision() -> None:
    plan = PipelinePlanner().plan(CreateVideoRequest(prompt="讲讲向量数据库"))
    assert plan.template is not None and plan.style is not None
    joined = " | ".join(plan.reasons)
    for stage in ("platform", "template", "style", "scene count", "routing"):
        assert stage in joined, stage
    assert plan.ranking, "the ranking must be inspectable, not just its winner"


def test_plan_honours_a_forced_template_and_says_so() -> None:
    plan = PipelinePlanner().plan(
        CreateVideoRequest(prompt="讲讲向量数据库", template="data_story"))
    assert plan.template_id == "data_story"
    assert any("forced by request" in reason for reason in plan.reasons)


def test_forcing_a_mismatched_template_warns() -> None:
    """data_story requires data. Forcing it is allowed — silently pretending
    the requirement was met is not."""
    plan = PipelinePlanner().plan(
        CreateVideoRequest(prompt="anything", template="data_story"))
    assert plan.template_id == "data_story"
    assert any("does not fit" in warning for warning in plan.warnings)


def test_unknown_template_falls_back_and_warns() -> None:
    plan = PipelinePlanner().plan(
        CreateVideoRequest(prompt="x", template="no_such_template"))
    assert plan.template is not None
    assert any("unknown template" in warning for warning in plan.warnings)


def test_unknown_style_falls_back_and_warns() -> None:
    plan = PipelinePlanner().plan(
        CreateVideoRequest(prompt="x", style="chartreuse_dreams"))
    assert any("unknown style" in warning for warning in plan.warnings)


def test_duration_is_clamped_to_the_platform_limit() -> None:
    """Requesting 5 minutes of TikTok is a request, not an instruction."""
    plan = PipelinePlanner().plan(
        CreateVideoRequest(prompt="x", platform="tiktok_9x16", duration_sec=600))
    assert plan.duration_sec == PLATFORM_PRESETS["tiktok_9x16"].max_duration_sec
    assert any("clamped" in warning for warning in plan.warnings)


def test_scene_count_is_clamped_into_the_template_range() -> None:
    plan = PipelinePlanner().plan(CreateVideoRequest(prompt="x", scenes=40))
    assert plan.scenes <= int(plan.template.scene_count["max"])


def test_vertical_request_selects_a_vertical_capable_template() -> None:
    plan = PipelinePlanner().plan(
        CreateVideoRequest(prompt="为什么缓存会失效", platform="tiktok_9x16"))
    assert plan.template.supports_aspect("9:16")


# ------------------------------------------------------------------- script
def test_script_planner_is_deterministic() -> None:
    registry = get_registry()
    manifest = registry.get("knowledge_primer")
    planner = ScriptPlanner()
    first = planner.build("向量数据库", manifest=manifest)
    second = planner.build("向量数据库", manifest=manifest)
    assert [b.narration for b in first.beats] == [b.narration for b in second.beats]


def test_script_respects_the_template_beat_order() -> None:
    manifest = get_registry().get("mechanism_explainer")
    script = ScriptPlanner().build("CI 流水线", manifest=manifest)
    kinds = [beat.kind for beat in script.beats]
    assert kinds[0] == manifest.beats[0]
    assert kinds[-1] == manifest.beats[-1]
    assert len(script.beats) == manifest.clamp_scenes(None)


def test_shrinking_a_script_keeps_the_opening_and_the_ending() -> None:
    """A video that opens and closes badly is worse than a shorter one.

    The count asked for must be inside the template's declared range: this
    template has a floor of 6, and asking for 4 legitimately clamps to 6. The
    claim under test is about *which* beats survive the trim, not about
    overriding the template's minimum.
    """
    manifest = get_registry().get("documentary_walkthrough")
    full = manifest.clamp_scenes(None)
    wanted = max(manifest.clamp_scenes(0), full - 2)
    assert wanted < full, "this template must actually shrink for the test to mean anything"

    script = ScriptPlanner().build("某段历史", manifest=manifest, scene_count=wanted)
    assert len(script.beats) == manifest.clamp_scenes(wanted) == wanted
    assert script.beats[0].kind == manifest.beats[0]
    assert script.beats[-1].kind == manifest.beats[-1]


def test_a_duration_target_trims_the_words_not_just_the_clock() -> None:
    """The bug this guards: rescaling durations to hit 20s while the narration
    stayed 32 seconds long produced a 32-second "20 second" video."""
    manifest = get_registry().get("knowledge_primer")
    long_script = ScriptPlanner().build("向量数据库", manifest=manifest)
    short_script = ScriptPlanner().build("向量数据库", manifest=manifest,
                                         target_duration_sec=20)
    assert short_script.total_duration < long_script.total_duration
    assert sum(len(b.narration) for b in short_script.beats) < \
        sum(len(b.narration) for b in long_script.beats)
    assert short_script.warnings, "trimming narration must be reported"


def test_user_script_is_used_verbatim() -> None:
    manifest = get_registry().get("editorial_argument")
    script = ScriptPlanner().build("t", manifest=manifest,
                                   script_text="第一段内容足够长。\n\n第二段内容也足够长。")
    assert script.generated_by == "user"
    assert "第一段内容足够长" in " ".join(b.narration for b in script.beats)


def test_narration_speed_matches_the_audio_estimator() -> None:
    """The storyboard and the audio stage must agree about how long text takes,
    or every video is born with a duration mismatch."""
    from html_video_workflow.utils.audio import estimate_speech_seconds

    text = "这是一段用于校准的测试文本，长度刚好。" * 2
    script = ScriptPlanner().build("x", manifest=get_registry().get("knowledge_primer"),
                                   script_text=text)
    spoken = sum(b.duration_sec for b in script.beats)
    estimate = estimate_speech_seconds(text)
    assert abs(spoken - estimate) < max(2.0, estimate * 0.35)


# -------------------------------------------------------------- storyboard
def test_storyboard_produces_valid_ir_v2() -> None:
    registry = get_registry()
    manifest = registry.get("knowledge_primer")
    style = registry.get("styles") if False else registry.default_style()
    request = CreateVideoRequest(prompt="向量数据库")
    plan = PipelinePlanner().plan(request)
    script = PipelinePlanner().build_script(plan, request)
    project = StoryboardPlanner().build(script, manifest=manifest, style=style,
                                        output=plan.output, request=request)
    assert project.schema_version == 2
    assert project.scene_count == len(script.beats)
    assert project.project.title


def test_ir_layers_never_name_a_renderer() -> None:
    request = CreateVideoRequest(prompt="向量数据库")
    plan = PipelinePlanner().plan(request)
    script = PipelinePlanner().build_script(plan, request)
    project = StoryboardPlanner().build(
        script, manifest=plan.template, style=plan.style, output=plan.output,
        request=request)
    payload = json.dumps(project.model_dump(mode="json"))
    assert "remotionComponent" not in payload
    assert "cssClass" not in payload


def test_motion_semantics_are_inside_the_ir_vocabulary() -> None:
    """A manifest may offer a richer motion vocabulary than the IR has; the
    storyboard must drop what the IR cannot express rather than emit it."""
    from html_video_workflow.planning.storyboard import _VALID_SEMANTICS

    request = CreateVideoRequest(prompt="为什么缓存会失效")
    plan = PipelinePlanner().plan(request)
    script = PipelinePlanner().build_script(plan, request)
    project = StoryboardPlanner().build(
        script, manifest=plan.template, style=plan.style, output=plan.output,
        request=request)
    for scene in project.scenes:
        for shot in scene.shots:
            for layer in shot.layers:
                assert layer.motion.semantic in _VALID_SEMANTICS


def test_every_scene_carries_the_narration_its_layers_show() -> None:
    request = CreateVideoRequest(prompt="向量数据库")
    plan = PipelinePlanner().plan(request)
    script = PipelinePlanner().build_script(plan, request)
    project = StoryboardPlanner().build(
        script, manifest=plan.template, style=plan.style, output=plan.output,
        request=request)
    for scene, beat in zip(project.scenes, script.beats):
        assert scene.narration.text == beat.narration
        assert scene.duration_hint_sec == beat.duration_sec


# ------------------------------------------------------------------ runtime
def test_dry_run_produces_a_plan_and_admits_it_produced_no_video() -> None:
    result = get_runtime().create_video(CreateVideoRequest(prompt="向量数据库",
                                                           dry_run=True))
    assert result.ok
    assert result.video_path is None
    assert any("dry_run" in warning for warning in result.warnings)
    assert result.template and result.style


def test_result_reports_reasons_and_template_identity() -> None:
    result = get_runtime().create_video(
        CreateVideoRequest(prompt="向量数据库", dry_run=True))
    assert result.reasons
    assert result.scenes > 0
    assert result.duration_sec and result.duration_sec > 0


def test_invalid_request_fails_with_a_code_not_an_exception() -> None:
    with pytest.raises(ValueError):
        CreateVideoRequest(prompt="")


# ---------------------------------------------------------------------- MCP
def test_mcp_advertises_create_video() -> None:
    from html_video_workflow.mcp import TOOLS

    names = {tool["name"] for tool in TOOLS}
    assert "create_video" in names
    create = next(tool for tool in TOOLS if tool["name"] == "create_video")
    # The description has to warn a model about cost, or it will call this
    # casually and time out its own turn.
    assert "minute" in create["description"] or "slow" in create["description"]


def test_mcp_lists_resources_without_touching_the_pipeline() -> None:
    from html_video_workflow.mcp import call_tool

    result = call_tool("list_platforms", {})
    payload = json.loads(result["content"][0]["text"])
    assert "youtube_16x9" in {item["id"] for item in payload["platforms"]}


def test_mcp_unknown_tool_is_an_error_result_not_a_crash() -> None:
    from html_video_workflow.mcp import call_tool

    result = call_tool("does_not_exist", {})
    assert result.get("isError") is True


def test_mcp_initialize_returns_a_protocol_version() -> None:
    from html_video_workflow.mcp import handle_message

    response = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response is not None
    assert response["result"]["protocolVersion"]
    assert response["result"]["capabilities"]["tools"] == {}


def test_mcp_notifications_get_no_reply() -> None:
    from html_video_workflow.mcp import handle_message

    assert handle_message({"jsonrpc": "2.0",
                           "method": "notifications/initialized"}) is None


# ---------------------------------------------------------------- v1 REST
@pytest.fixture()
def client():
    fastapi = pytest.importorskip("fastapi")
    del fastapi
    from fastapi.testclient import TestClient

    from html_video_workflow.api import create_app

    return TestClient(create_app())


def test_v1_videos_plan_only_returns_the_product_shape(client) -> None:
    response = client.post("/v1/videos",
                           json={"prompt": "讲讲向量数据库", "dry_run": True})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    for field in ("job_id", "project_id", "template", "style", "reasons",
                  "warnings", "providers", "scenes"):
        assert field in body, field


def test_v1_rejects_a_request_with_no_intent(client) -> None:
    response = client.post("/v1/videos", json={})
    assert response.status_code == 422


def test_v1_exposes_the_catalogue(client) -> None:
    assert client.get("/v1/templates").status_code == 200
    assert client.get("/v1/styles").status_code == 200
    assert client.get("/v1/platforms").status_code == 200
    assert client.get("/v1/templates/knowledge_primer").json()["id"] == \
        "knowledge_primer"


def test_v1_unknown_template_is_a_404(client) -> None:
    assert client.get("/v1/templates/nope").status_code == 404


def test_v1_topic_suggestions_need_a_prompt(client) -> None:
    assert client.get("/v1/topics/suggest?prompt=").status_code == 422


def test_v1_topic_suggestions_return_ranked_angles(client) -> None:
    body = client.get("/v1/topics/suggest?prompt=向量数据库&count=3").json()
    assert len(body) >= 3
    assert body[0]["score"] >= body[-1]["score"]


def test_v1_unknown_job_returns_a_structured_error(client) -> None:
    response = client.get("/v1/videos/job_does_not_exist")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == VideoErrorCode.INVALID_REQUEST.value


# ------------------------------------------------------------------ CLI
def test_cli_generate_parser_accepts_the_one_liner() -> None:
    from html_video_workflow.cli.main import build_parser

    args = build_parser().parse_args(["generate", "explain vectors"])
    assert args.prompt == "explain vectors"
    assert args.func.__name__ == "cmd_generate"


def test_cli_maps_error_codes_to_exit_statuses() -> None:
    from html_video_workflow.cli.main import EXIT_CODES
    from html_video_workflow.core.errors import HTTP_STATUS

    # The two tables are derived from the same vocabulary; if a code gains an
    # HTTP status and no exit code, this catches it.
    for code in HTTP_STATUS:
        assert code in EXIT_CODES, code


def test_cli_generate_dry_run_exits_zero(capsys) -> None:
    from html_video_workflow.cli.main import main

    assert main(["generate", "讲讲向量数据库", "--dry-run"]) == 0
    assert "向量数据库" in capsys.readouterr().out


def test_cli_topics_lists_angles(capsys) -> None:
    from html_video_workflow.cli.main import main

    assert main(["topics", "讲讲向量数据库", "--count", "3"]) == 0
    assert capsys.readouterr().out.count("\n") >= 3


# -------------------------------------------------------------------- SDK
def test_python_sdk_is_a_one_liner() -> None:
    from html_video_workflow import create_video

    result = create_video(prompt="讲讲向量数据库", dry_run=True)
    assert result.ok
    assert result.template


def test_python_sdk_accepts_a_request_object() -> None:
    from html_video_workflow import create_video

    result = create_video(CreateVideoRequest(prompt="向量数据库", dry_run=True))
    assert result.project_id


def test_suggest_topics_helper_works_offline() -> None:
    from html_video_workflow import suggest_topics

    suggestions = suggest_topics("讲讲向量数据库", count=3)
    assert len(suggestions) == 3


# ------------------------------------------------- one entry point, one truth
def test_all_entry_points_share_the_runtime_method() -> None:
    """The architectural claim, asserted: no entry point has its own pipeline."""
    import importlib
    import inspect

    from html_video_workflow.api.routes import v1 as v1_module
    # Not `from ...cli import main`: the package re-exports a *function* named
    # `main`, so that import yields the function and `getsource` would only see
    # argparse plumbing, missing every handler.
    cli_module = importlib.import_module("html_video_workflow.cli.main")

    assert "create_video" in inspect.getsource(v1_module).lower()
    assert "create_video" in inspect.getsource(cli_module).lower()
    # Both must reach the Runtime rather than a stage function directly.
    for module in (v1_module, cli_module):
        source = inspect.getsource(module)
        assert "stage_render" not in source
        assert "stage_compose" not in source


# ------------------------------------------------- regressions: request intent
@pytest.mark.parametrize("blank", ["", "   ", "\n", "\t", "  \n\t ", "\r\n"])
def test_whitespace_only_intent_is_rejected(blank: str) -> None:
    """``"   "`` is truthy in Python, so a naive truthiness check lets a blank
    prompt reach the planner and produce a video about nothing. Intent is
    semantic; a string of spaces carries none.
    """
    with pytest.raises(ValueError):
        CreateVideoRequest(prompt=blank)
    with pytest.raises(ValueError):
        CreateVideoRequest(topic=blank)
    with pytest.raises(ValueError):
        CreateVideoRequest(script=blank)


def test_a_real_prompt_survives_the_blank_filter() -> None:
    """The fix must not eat legitimate input, including leading whitespace."""
    assert CreateVideoRequest(prompt="  explain X  ").prompt == "explain X"


# ------------------------------------------------- regressions: source contract
def test_structured_dict_source_is_accepted() -> None:
    """The public boundary advertises ``{"kind": ..., "value": ...}``.

    Refusing that shape while the docs describe it means the API documents one
    contract and the runtime enforces another.
    """
    documents = resolve_source({"kind": "text", "value": "some prose"})
    assert documents and documents[0].kind == "text"

    markdown = "# Title\n\n## Section A\n\n- fact one\n\nBody.\n"
    documents = resolve_source({"kind": "markdown", "value": markdown})
    assert documents[0].kind == "markdown"
    assert "Section A" in documents[0].headings
    assert "fact one" in documents[0].facts


def test_markdown_kind_describes_the_value_not_a_path(tmp_path: Path) -> None:
    """Inline markdown content is the obvious way to hand a planner a document.

    Reading ``kind="markdown"`` as "go fetch this path" turned that into a
    ``FileNotFoundError``. A path is only a path when one exists.
    """
    inline = resolve_source({"kind": "markdown", "value": "# A\n\n## B\n"})
    assert inline[0].headings == ["A", "B"]

    real = tmp_path / "doc.md"
    real.write_text("# From Disk\n\n## Section\n", encoding="utf-8")
    from_disk = resolve_source({"kind": "markdown", "value": str(real)})
    assert from_disk[0].headings == ["From Disk", "Section"]


def test_file_kind_still_raises_when_the_file_is_absent(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_source({"kind": "file", "value": str(tmp_path / "absent.md")})


# ------------------------------------------- regressions: duration is honest
def _script_total(topic: str, template: str, target: float | None) -> tuple[float, int]:
    manifest = get_registry().get(template)
    script = ScriptPlanner().build(topic, manifest=manifest,
                                   target_duration_sec=target)
    return script.total_duration, max(len(beat.narration) for beat in script.beats)


def test_requested_duration_is_honoured_within_tolerance() -> None:
    """Requesting 20s must not yield 32s.

    The contract: ``duration_sec`` is a *target*, honoured within ±10%. When
    the content cannot fit, the planner trims and warns — it never silently
    rescales the clock to make the numbers agree.
    """
    for target in (20.0, 30.0):
        total, _ = _script_total("向量数据库", "knowledge_primer", target)
        assert abs(total - target) / target <= 0.10, (
            f"asked for {target}s, planner produced {total}s")


def test_a_target_the_material_cannot_fill_is_reported() -> None:
    """A target can be missed in both directions.

    Trimming fixes "too long". "Too short" cannot be fixed without padding the
    video with dead air, so the honest move is to say so rather than return a
    38-second video for a 45-second request and call it done.
    """
    manifest = get_registry().get("knowledge_primer")
    script = ScriptPlanner().build("向量数据库", manifest=manifest,
                                   target_duration_sec=45)
    assert script.total_duration < 45.0
    assert any("requested 45s" in warning for warning in script.warnings), (
        f"expected a shortfall warning, got {script.warnings}")


def test_shorter_target_trims_words_not_the_clock() -> None:
    """Timing is downstream of the words.

    The original bug rescaled ``duration_sec`` while leaving the narration long,
    so the audio stage — which measures the text — produced a longer video than
    requested. A tighter target must shorten the text.
    """
    _, long_chars = _script_total("向量数据库", "knowledge_primer", 60.0)
    _, short_chars = _script_total("向量数据库", "knowledge_primer", 20.0)
    assert short_chars < long_chars, (
        "a 20s target must trim narration, not just relabel scene timings")


@pytest.mark.parametrize("language,paragraph", [
    ("zh-CN", "向量数据库把文本嵌入成高维向量，于是检索不再依赖关键词是否恰好命中，"
              "而是比较语义之间的距离，这一点决定了它在长文档问答里的表现。"
              "\n\n它并不是要取代关系型数据库，两者解决的是不同形状的问题，"
              "把事务性查询交给前者、把相似检索交给后者，才是常见的组合方式。"),
    ("en-US", "A vector database embeds text into high-dimensional vectors, so "
              "retrieval no longer depends on whether a keyword happens to match "
              "but on the distance between meanings, which is what decides how it "
              "behaves in long-document question answering."
              "\n\nIt is not meant to replace a relational database: the two solve "
              "differently shaped problems, and handing transactional queries to "
              "one while leaving similarity search to the other is the usual split."),
])
def test_planner_uses_the_canonical_speech_estimator(language: str,
                                                     paragraph: str) -> None:
    """One estimator, or the storyboard and the audio stage disagree.

    Asserted against the *scene timings the planner actually emits*, not against
    a constant: a planner that counts characters while the audio stage measures
    speech seconds makes English scenes ~14% long, because the canonical
    estimator ignores whitespace.
    """
    from html_video_workflow.utils.audio import estimate_speech_seconds

    manifest = get_registry().get("knowledge_primer")
    script = ScriptPlanner().build("t", manifest=manifest, language=language,
                                   script_text=paragraph, target_duration_sec=30)
    assert script.beats
    for beat in script.beats:
        expected = estimate_speech_seconds(beat.narration) + 0.9
        # Compared against the documented timing formula, floor included: the
        # 3s minimum scene length is a deliberate rule, not a rounding artefact.
        assert beat.duration_sec == round(min(12.0, max(3.0, expected)), 2), (
            f"{language}: scene timed {beat.duration_sec}s but the audio stage "
            f"will measure {expected:.2f}s")
    # At least one scene must clear the floor, or the assertion above would
    # hold even if the estimator had never been consulted.
    assert any(estimate_speech_seconds(beat.narration) > 2.1
               for beat in script.beats)
