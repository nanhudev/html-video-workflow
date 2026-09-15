"""``html-video`` command line entry point.

The CLI only talks to the Runtime — exactly like the REST API and the Studio.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..config.paths import hv_home, outputs_dir
from ..config.settings import known_secrets, load_env_file, load_settings, save_settings
from ..core.request import (
    PLATFORM_PRESETS,
    CreateVideoRequest,
    SourceInput,
    VideoResult,
)
from ..hardware.benchmark import run_core_benchmarks
from ..hardware.profile import probe_hardware
from ..legacy.adapter import gallery_legacy, legacy_templates, render_legacy
from ..pipeline.router import plan_pipeline
from ..project.ir import validate_project
from ..project.migrate import detect_version, migrate
from ..project.store import list_projects, load_project, load_project_file, save_project
from ..providers.base import ProviderType
from ..providers.registry import all_providers, by_type, capabilities
from ..runtime.engine import VideoRuntime, get_runtime
from ..sources import resolve_source
from ..utils.console import make_streams_unfailing
from ..utils.logging import configure_logging, get_logger

log = get_logger("cli")

STATE_ICON = {
    "ready": "OK",
    "not_installed": "--",
    "unavailable": "!!",
    "missing_credentials": "??",
    "error": "XX",
}


# --------------------------------------------------------------------- doctor
def cmd_doctor(args: argparse.Namespace) -> int:
    profile = probe_hardware(use_cache=not args.refresh)
    print(f"HTML Video Workflow — doctor  (home: {hv_home()})")
    print("-" * 62)
    print(f"{'OS':<14}{profile.os} {profile.os_version[:24]} ({profile.arch})")
    print(f"{'CPU':<14}{profile.cpu_model or 'unknown'} "
          f"({profile.cpu_logical_cores} logical)")
    print(f"{'RAM':<14}{(profile.ram_total_mb or 0) / 1024:.1f} GB total, "
          f"{(profile.ram_free_mb or 0) / 1024:.1f} GB free")
    if profile.gpus:
        for gpu in profile.gpus:
            vram = f"{gpu.vram_mb} MB" if gpu.vram_mb else "VRAM unknown"
            print(f"{'GPU':<14}{gpu.model or gpu.vendor} — {vram}")
    else:
        print(f"{'GPU':<14}none detected (CPU-only)")
    accel = ", ".join(
        f"{k}={'yes' if v else ('no' if v is False else 'n/a')}"
        for k, v in profile.accelerators.items()
    )
    print(f"{'Accel':<14}{accel}")
    print("-" * 62)
    for name, tool in profile.tooling.items():
        status = "OK" if tool.available else "!!"
        version = (tool.version or "")[:44]
        print(f"{status:<4}{name:<12}{version}")
    print("-" * 62)
    for capability in capabilities():
        icon = STATE_ICON.get(capability.state.value, "??")
        detail = capability.reason or ""
        print(f"{icon:<4}{capability.type.value:<10}{capability.id:<20}{detail[:60]}")
    print("-" * 62)
    plan = plan_pipeline(language=args.language, preset="auto", hardware=profile)
    print(f"Recommended preset : {plan['preset']}")
    for stage, provider in plan["selection"].items():
        print(f"  {stage:<10}{provider or 'NONE AVAILABLE'}")
    return 0


# ------------------------------------------------------------------ providers
def cmd_providers(args: argparse.Namespace) -> int:
    provider_type = args.type
    rows = capabilities()
    if provider_type:
        rows = [row for row in rows if row.type.value == provider_type]
    if args.json:
        print(json.dumps([row.model_dump(mode="json") for row in rows],
                         ensure_ascii=False, indent=2))
        return 0
    print(f"{'STATE':<6}{'TYPE':<11}{'ID':<20}{'LOCAL':<7}{'Q/S/N':<16}REASON")
    print("-" * 96)
    for row in rows:
        scores = f"{row.quality_score}/{row.speed_score}/{row.naturalness_score}"
        print(
            f"{STATE_ICON.get(row.state.value, '??'):<6}{row.type.value:<11}{row.id:<20}"
            f"{'yes' if row.local else 'api':<7}{scores:<16}{(row.reason or '')[:40]}"
        )
    return 0


# ------------------------------------------------------------------ benchmark
def cmd_benchmark(args: argparse.Namespace) -> int:
    print("Running core benchmarks (no models required)...")
    results = run_core_benchmarks()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------- validate
def cmd_validate(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    version = detect_version(data)
    print(f"Detected schema version: {version}")
    migrated = migrate(data)
    project, errors = validate_project(migrated)
    if errors:
        print("INVALID")
        for error in errors:
            print("  -", error)
        return 1
    assert project is not None
    print(f"VALID — {project.project.title!r}")
    print(f"  scenes    : {project.scene_count}")
    print(f"  duration  : ~{project.estimated_duration()}s")
    print(f"  language  : {project.project.language}")
    return 0


# -------------------------------------------------------------------- projects
def cmd_projects(args: argparse.Namespace) -> int:
    items = list_projects()
    if not items:
        print("No projects yet.")
        return 0
    for item in items:
        print(f"{item['id']:<28}{item['title'][:40]:<42}{item['scene_count']} scenes")
    return 0


# ---------------------------------------------------------------------- create
def cmd_create(args: argparse.Namespace) -> int:
    runtime = get_runtime()
    source = args.prompt
    if args.script:
        source = Path(args.script).read_text(encoding="utf-8")
    elif args.file:
        source = Path(args.file).read_text(encoding="utf-8")
    if not source:
        print("Provide a prompt, --script or --file")
        return 2

    overrides = {}
    if args.llm:
        overrides["llm"] = args.llm
    if args.tts:
        overrides["tts"] = args.tts
    if args.renderer:
        overrides["renderer"] = args.renderer

    plan = plan_pipeline(
        language=args.language, preset=args.preset, overrides=overrides
    )
    llm_id = plan["selection"].get("llm")
    print(f"Planner  : {llm_id} (preset {plan['preset']})")

    if args.file and Path(args.file).suffix.lower() in {".json"}:
        project = load_project_file(args.file)
    else:
        from ..providers.base import LLMRequest
        from ..pipeline.router import provider_for

        provider = provider_for("llm", llm_id)
        schema_hint = (
            "Return a Video IR V2 project JSON with schema_version=2, project, "
            "sequences[].scenes[] (id, intent, narration{text,language,emotion,pace,"
            "pause_after_ms,emphasis[]}, shots[].layers[]{type,role,content,layout,"
            "motion{semantic}}, duration_hint_sec)."
        )
        response = provider.complete(
            LLMRequest(
                prompt=f"Create a short video project about: {source}",
                system="You are a careful video editor. Return JSON only.",
                json_mode=True,
                schema_hint=schema_hint,
            )
        )
        try:
            data = json.loads(_extract_json(response.text))
        except json.JSONDecodeError as exc:
            print(f"LLM did not return valid JSON ({exc}); falling back to mock planner")
            from ..providers.llm.mock_llm import build_mock_project

            data = build_mock_project(source)
        data.setdefault("project", {})
        data["project"]["title"] = data["project"].get("title") or source[:40]
        project = load_project_file_from_dict(data)

    project_id, path = save_project(project)
    print(f"Project  : {project_id}")
    print(f"Path     : {path}")
    print(f"Scenes   : {project.scene_count}")

    if args.render:
        job = runtime.create_job(project, preset=args.preset, overrides=overrides)
        runtime.run_job(job, project)
        print(f"Job      : {job.id} — {job.status.value}")
        video = job.outputs.get("video")
        if video:
            print(f"VIDEO    : {video}")
        if job.quality and not job.quality.get("passed"):
            print(f"QC       : FAILED {job.quality.get('failed')}")
            return 1
    return 0


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def load_project_file_from_dict(data: dict[str, Any]):
    from ..project.migrate import load_project as load_any

    return load_any(data)


# -------------------------------------------------------------------- generate
#: CLI exit statuses. Derived from the same error codes the API turns into HTTP
#: statuses, so a failure means the same thing no matter how you called it.
EXIT_CODES: dict[str, int] = {
    "invalid_request": 2, "no_source": 2, "source_unreadable": 2,
    # A thing that is not there exits 2, the same as a bad argument: both mean
    # "look at what you asked for". 2 is also what a shell user expects from a
    # usage error, and there is nothing to distinguish here from the caller's
    # side beyond the message.
    "no_template": 2, "job_not_found": 2,
    "no_provider": 3, "planning_failed": 1,
    "render_failed": 1, "tts_failed": 1, "compose_failed": 1,
    "quality_failed": 4, "cancelled": 130, "internal": 1,
}


def _request_from_args(args: argparse.Namespace) -> CreateVideoRequest:
    source = None
    if args.source:
        source = SourceInput(kind=args.source_kind, value=args.source,
                             max_chars=args.max_chars)
    elif args.file:
        source = SourceInput(kind="file", value=args.file, max_chars=args.max_chars)
    try:
        return CreateVideoRequest(
            prompt=(args.prompt or None),
            topic=args.topic,
            source=source,
            script=(Path(args.script).read_text(encoding="utf-8")
                    if args.script else None),
            title=args.title,
            language=args.language,
            platform=args.platform,
            aspect=args.aspect,
            width=args.width,
            height=args.height,
            duration_sec=args.duration,
            scenes=args.scenes,
            template=args.template,
            style=args.style,
            voice=args.voice,
            captions=not args.no_captions,
            preset=args.preset,
            llm=args.llm,
            tts=args.tts,
            renderer=args.renderer,
            out_dir=args.out,
            wait=not args.no_wait,
            dry_run=args.dry_run,
            strict=args.strict,
            created_by="cli",
        )
    except Exception as exc:  # noqa: BLE001 - pydantic messages are the UX here
        print(f"invalid request: {exc}")
        raise SystemExit(EXIT_CODES["invalid_request"]) from exc


def cmd_generate(args: argparse.Namespace) -> int:
    """`html-video generate "..."` — the one command that produces an MP4."""
    runtime = get_runtime()
    result = runtime.create_video(_request_from_args(args))
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_result(result, verbose=args.verbose)
    if not result.ok:
        return EXIT_CODES.get(result.error_code or "internal", 1)
    return 0


def _print_result(result: "VideoResult", verbose: bool = False) -> None:
    print(f"{'job':<10}{result.job_id or '-'}")
    print(f"{'project':<10}{result.project_id or '-'}")
    print(f"{'title':<10}{result.title or '-'}")
    print(f"{'template':<10}{result.template or '-'} / style {result.style or '-'}")
    print(f"{'scenes':<10}{result.scenes}")
    if result.video_path:
        print(f"VIDEO      {result.video_path}")
        print(f"{'duration':<10}{result.duration_sec or 0:.1f}s "
              f"({result.width}x{result.height})")
        print(f"{'note':<10}duration measured by ffprobe on the exported file")
    if result.qc:
        verdict = "PASS" if result.qc.get("passed") else "FAIL"
        print(f"{'QC':<10}{verdict} warnings={result.qc.get('warned', 0)}")
    for fallback in result.fallbacks:
        print(f"fallback   {fallback.get('stage')}: "
              f"{fallback.get('from')} -> {fallback.get('to')}")
    for warning in result.warnings:
        print(f"warning    {warning}")
    if verbose:
        print("reasons:")
        for reason in result.reasons:
            print(f"  - {reason}")
    if not result.ok:
        print(f"FAILED     [{result.error_code}] {result.error}")


def cmd_templates(args: argparse.Namespace) -> int:
    from ..templates.registry import get_registry

    registry = get_registry()
    rows = registry.templates()
    if args.json:
        print(json.dumps([m.model_dump(mode="json") for m in rows],
                         ensure_ascii=False, indent=2))
        return 0
    print(f"{'ID':<26}{'SCENES':<10}{'STYLE':<16}{'BEST FOR'}")
    print("-" * 88)
    for manifest in rows:
        span = f"{manifest.scene_count.get('min', 3)}-{manifest.scene_count.get('max', 8)}"
        print(f"{manifest.id:<26}{span:<10}{manifest.default_style:<16}"
              f"{', '.join(manifest.best_for)[:34]}")
        if args.verbose:
            print(f"    {manifest.description}")
    errors = registry.load_errors()
    if errors:
        print("-" * 88)
        for path, message in errors.items():
            print(f"LOAD ERROR {path}: {message}")
    return 0


def cmd_styles(args: argparse.Namespace) -> int:
    from ..templates.registry import get_registry

    rows = get_registry().styles()
    if args.json:
        print(json.dumps([s.model_dump(mode="json") for s in rows],
                         ensure_ascii=False, indent=2))
        return 0
    for style in rows:
        print(f"{style.id:<16}{style.name:<16}{style.motion_bias:<11}"
              f"bg={style.color('bg', '?')} text={style.color('text', '?')}")
        if args.verbose:
            print(f"    {style.description}")
    return 0


def cmd_platforms(args: argparse.Namespace) -> int:
    rows = list(PLATFORM_PRESETS.values())
    if args.json:
        print(json.dumps([p.model_dump(mode="json") for p in rows],
                         ensure_ascii=False, indent=2))
        return 0
    for preset in rows:
        print(f"{preset.id:<24}{preset.aspect:<7}{preset.width}x{preset.height:<6}"
              f"safe_bottom={preset.safe_bottom:<6}{preset.label}")
    return 0


def cmd_topics(args: argparse.Namespace) -> int:
    from ..planning.topic_planner import TopicPlanner

    planner = TopicPlanner()
    source = SourceInput(kind=args.source_kind, value=args.source) if args.source else None
    request = CreateVideoRequest(prompt=args.prompt or None, topic=args.topic,
                                 source=source)
    documents = resolve_source(source) if source else []
    rows = planner.suggest(request, documents, count=args.count)
    if args.json:
        print(json.dumps([r.model_dump(mode="json") for r in rows],
                         ensure_ascii=False, indent=2))
        return 0
    for index, item in enumerate(rows, start=1):
        print(f"{index}. {item.title}  [{item.angle}/{item.video_type} "
              f"{item.score:.2f}]")
        if args.verbose:
            print(f"     {item.rationale}")
    return 0


# ---------------------------------------------------------------------- render
def cmd_render(args: argparse.Namespace) -> int:
    runtime = get_runtime()
    if args.legacy:
        final = render_legacy(args.project, args.template, args.build)
        print(f"VIDEO={final}")
        return 0
    project = (
        load_project(args.project)
        if not Path(args.project).exists()
        else load_project_file(args.project)
    )
    overrides = {}
    if args.tts:
        overrides["tts"] = args.tts
    if args.renderer:
        overrides["renderer"] = args.renderer
    job = runtime.create_job(project, preset=args.preset, overrides=overrides)
    runtime.run_job(job, project)
    print(f"Job   : {job.id} — {job.status.value}")
    for name, path in job.outputs.items():
        print(f"{name.upper():<6}: {path}")
    for fallback in job.fallbacks:
        print(f"fallback: {fallback['stage']} {fallback['from']} -> {fallback['to']}")
    if job.quality:
        print(f"QC    : {'PASS' if job.quality['passed'] else 'FAIL'} "
              f"warnings={job.quality['warned']}")
    return 0 if job.status.value == "completed" else 1


# ---------------------------------------------------------------------- status
def cmd_status(args: argparse.Namespace) -> int:
    runtime = get_runtime()
    job = runtime.get_job(args.job)
    if job is None:
        print(f"Unknown job: {args.job}")
        return 1
    print(f"{'job':<10}{job.id}")
    print(f"{'status':<10}{job.status.value}")
    print(f"{'progress':<10}{job.progress:.0%}")
    print(f"{'preset':<10}{job.plan.preset}")
    print(f"{'providers':<10}llm={job.plan.llm} tts={job.plan.tts} "
          f"renderer={job.plan.renderer}")
    for task in job.tasks:
        print(f"  - {task.stage:<10}{task.status.value:<11}"
              f"{len(task.steps)} steps  {task.progress:.0%}")
        for step in task.steps:
            marker = {"completed": "+", "failed": "!", "cached": "="}.get(
                step.status.value, "."
            )
            print(f"      [{marker}] {step.name}"
                  + (f"  ({step.error})" if step.error else ""))
    if job.outputs:
        print("outputs:")
        for key, value in job.outputs.items():
            print(f"  {key}: {value}")
    if args.follow:
        _print_events(job.id)
    return 0


def _print_events(job_id: str) -> None:
    from ..runtime.events import read_events

    seen = 0
    for event in read_events(job_id):
        seen += 1
        print(f"  {event['timestamp']} {event['stage']:<10}{event['event']}")
    print(f"({seen} events)")


# --------------------------------------------------------------------- gallery
def cmd_gallery(args: argparse.Namespace) -> int:
    templates = legacy_templates()
    print(f"Legacy templates: {', '.join(templates)}")
    if args.project:
        path = gallery_legacy(args.project, args.build)
        print(f"GALLERY={path}")
    return 0


# ----------------------------------------------------------------------- serve
def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed. Install with: pip install -e '.[api]'")
        return 1
    from ..api import create_app

    app = create_app()
    _announce_studio(app, args.host, args.port, required=False)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


def cmd_studio(args: argparse.Namespace) -> int:
    """Serve the Studio GUI. Node is *not* needed — the frontend is prebuilt."""
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed. Install with: pip install -e '.[api]'")
        return 1
    from ..api import create_app
    from ..api.studio import studio_dist

    if studio_dist() is None:
        # Refusing loudly beats serving a blank page and calling it success.
        print("The Studio frontend has not been built on this machine.")
        print()
        print("  from a source checkout:")
        print("      cd apps/studio && npm ci && npm run build")
        print("      html-video studio")
        print()
        print("  an installed wheel ships the built frontend, so this only")
        print("  happens when running from a checkout without building it.")
        return 1

    app = create_app()
    _announce_studio(app, args.host, args.port, required=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


def _announce_studio(app, host: str, port: int, *, required: bool) -> None:
    dist = getattr(app.state, "studio_dir", None)
    where = f"http://{host}:{port}"
    if dist:
        print(f"Studio  {where}/")
        print(f"API     {where}/docs")
    elif required:
        # cmd_studio already checked, so this is a race, not a normal path.
        print("Studio frontend disappeared between the check and the start.")
    else:
        print(f"API     {where}/docs")
        print("Studio  not built — run `html-video studio` for instructions")


# -------------------------------------------------------------------- settings
def cmd_settings(args: argparse.Namespace) -> int:
    settings = load_settings()
    if args.set:
        key, _, value = args.set.partition("=")
        section, _, field = key.partition(".")
        data = settings.model_dump()
        if section in data and isinstance(data[section], dict) and field:
            current = data[section].get(field)
            parsed: Any = value
            if isinstance(current, bool):
                parsed = value.lower() in {"1", "true", "yes"}
            elif isinstance(current, int):
                parsed = int(value)
            elif isinstance(current, float):
                parsed = float(value)
            data[section][field] = parsed
            from ..config.settings import Settings

            settings = Settings.model_validate(data)
            save_settings(settings)
            print(f"set {key} = {parsed}")
        else:
            print(f"Unknown setting: {key}")
            return 1
    print(json.dumps(settings.model_dump(), ensure_ascii=False, indent=2))
    masked = {k: v for k, v in known_secrets().items() if v}
    print("secrets:", json.dumps(masked, ensure_ascii=False))
    print(f"outputs dir: {outputs_dir()}")
    return 0


# ------------------------------------------------------------------------ main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="html-video", description="Local-first agentic video production runtime"
    )
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="probe hardware, tooling and providers")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--language", default="zh-CN")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("providers", help="list provider capabilities")
    p.add_argument("--type", choices=[t.value for t in ProviderType])
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_providers)

    p = sub.add_parser("benchmark", help="run core benchmarks")
    p.set_defaults(func=cmd_benchmark)

    p = sub.add_parser("validate", help="validate a project JSON (V1 or V2)")
    p.add_argument("file")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("projects", help="list stored projects")
    p.set_defaults(func=cmd_projects)

    p = sub.add_parser("create", help="create a project (and optionally render it)")
    p.add_argument("prompt", nargs="?", default="")
    p.add_argument("--script")
    p.add_argument("--file")
    p.add_argument("--preset", default="auto",
                   choices=["auto", "fast", "balanced", "high_quality", "max_quality"])
    p.add_argument("--language", default="zh-CN")
    p.add_argument("--llm")
    p.add_argument("--tts")
    p.add_argument("--renderer")
    p.add_argument("--render", action="store_true")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("generate", help="one prompt → one MP4",
                       description="Runs the whole pipeline: source → topic → "
                                   "template → script → storyboard → render → "
                                   "voice → compose → QC.")
    p.add_argument("prompt", nargs="?", default="",
                   help="what the video should be about")
    p.add_argument("--topic", help="short topic title (overrides prompt-derived)")
    p.add_argument("--source", help="URL, GitHub repo or file path to ground it in")
    p.add_argument("--source-kind", default="auto",
                   choices=["auto", "text", "markdown", "file", "webpage",
                            "github", "url"])
    p.add_argument("--max-chars", type=int, default=12000,
                   help="cap on ingested source characters")
    p.add_argument("--script", help="file with pre-written narration")
    p.add_argument("--file", help="alias for --source pointing at a local file")
    p.add_argument("--title")
    p.add_argument("--language", default="zh-CN")
    p.add_argument("--platform", choices=sorted(PLATFORM_PRESETS))
    p.add_argument("--aspect", choices=["16:9", "9:16", "1:1", "4:5", "3:4"])
    p.add_argument("--width", type=int,
                   help="override output width (e.g. 320 for a fast smoke test)")
    p.add_argument("--height", type=int, help="override output height")
    p.add_argument("--duration", type=float, help="target duration in seconds")
    p.add_argument("--scenes", type=int)
    p.add_argument("--template")
    p.add_argument("--style")
    p.add_argument("--voice")
    p.add_argument("--no-captions", action="store_true")
    p.add_argument("--preset", default="auto",
                   choices=["auto", "fast", "balanced", "high_quality", "max_quality"])
    p.add_argument("--llm")
    p.add_argument("--tts")
    p.add_argument("--renderer")
    p.add_argument("--out", help="output directory")
    p.add_argument("--no-wait", action="store_true",
                   help="return immediately with a job id")
    p.add_argument("--dry-run", action="store_true",
                   help="plan and build the IR but do not render")
    p.add_argument("--strict", action="store_true",
                   help="treat QC failure as an error")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("templates", help="list video templates")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_templates)

    p = sub.add_parser("styles", help="list style profiles")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_styles)

    p = sub.add_parser("platforms", help="list platform presets")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_platforms)

    p = sub.add_parser("topics", help="suggest angles for a topic")
    p.add_argument("prompt", nargs="?", default="")
    p.add_argument("--topic")
    p.add_argument("--source")
    p.add_argument("--source-kind", default="auto",
                   choices=["auto", "text", "markdown", "file", "webpage",
                            "github", "url"])
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_topics)

    p = sub.add_parser("render", help="render a project through the runtime")
    p.add_argument("project")
    p.add_argument("--preset", default="auto",
                   choices=["auto", "fast", "balanced", "high_quality", "max_quality"])
    p.add_argument("--tts")
    p.add_argument("--renderer")
    p.add_argument("--legacy", action="store_true",
                   help="use the untouched scripts/workflow.py pipeline")
    p.add_argument("--template", default="academic-blue")
    p.add_argument("--build", default="build")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("status", help="show job status")
    p.add_argument("job")
    p.add_argument("--follow", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("gallery", help="legacy template gallery")
    p.add_argument("--project")
    p.add_argument("--build", default="build/gallery")
    p.set_defaults(func=cmd_gallery)

    p = sub.add_parser("studio", help="open the Studio GUI (prebuilt, no Node)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--log-level", default="info")
    p.set_defaults(func=cmd_studio)

    p = sub.add_parser("serve", help="start the Runtime API (and the Studio)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--log-level", default="info")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("settings", help="show or change settings")
    p.add_argument("--set", help="section.field=value (e.g. routing.preset=fast)")
    p.set_defaults(func=cmd_settings)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Before anything can print. A console that cannot encode one character of
    # the output must not be able to turn a successful render into a failed
    # command — see `make_streams_unfailing`.
    make_streams_unfailing()
    load_env_file()
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging("DEBUG" if args.verbose else "INFO")
    try:
        return int(args.func(args) or 0)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        log.error("%s: %s", type(exc).__name__, exc)
        if args.verbose:
            raise
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
