"""A dependency-free MCP server over stdio.

Written against the MCP JSON-RPC surface directly rather than pulling in the
``mcp`` SDK: this project's promise is that a fresh clone runs with two
dependencies, and an adapter layer is the wrong place to break it. If the
official SDK is installed later, this server can be swapped out without the
Runtime noticing — the tool contract is what matters.

Tools mirror the product API exactly. Anything an agent can do here, the CLI,
the REST API and the SDK can do too.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Callable

from .. import __version__
from ..core.request import CreateVideoRequest

PROTOCOL_VERSION = "2024-11-05"

#: Tool definitions. Descriptions are written for a model deciding *whether* to
#: call the tool, so each one states the cost and the failure mode.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "create_video",
        "description": (
            "Generate a complete video (MP4) from a prompt, topic, script or "
            "source document. Runs the whole pipeline locally: topic → template "
            "→ script → storyboard → HTML render → TTS → FFmpeg → QC. This can "
            "take 1-3 minutes of CPU time for a ~20 second video; set "
            "dry_run=true first to see the plan without rendering."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string",
                           "description": "What the video should be about."},
                "topic": {"type": "string",
                          "description": "Short topic title, if already decided."},
                "source": {"type": "string",
                           "description": "URL, GitHub repo or local file path to "
                                          "ground the video in."},
                "script": {"type": "string",
                           "description": "Pre-written narration; skips script "
                                          "planning."},
                "title": {"type": "string"},
                "language": {"type": "string", "default": "zh-CN"},
                "platform": {
                    "type": "string",
                    "description": "Delivery target, e.g. youtube_16x9, "
                                   "youtube_shorts_9x16, tiktok_9x16, "
                                   "xiaohongshu_3x4.",
                },
                "aspect": {"type": "string",
                           "enum": ["16:9", "9:16", "1:1", "4:5", "3:4"]},
                "width": {"type": "integer",
                          "description": "Override the output width. Pair with "
                                         "`height`; the default comes from the "
                                         "platform preset or the aspect ratio."},
                "height": {"type": "integer"},
                "duration_sec": {"type": "number",
                                 "description": "Target duration. Narration is "
                                                "trimmed to fit."},
                "scenes": {"type": "integer"},
                "template": {"type": "string",
                             "description": "Force a template id (see "
                                            "list_templates)."},
                "style": {"type": "string",
                          "description": "Force a style id (see list_styles)."},
                "voice": {"type": "string"},
                "captions": {"type": "boolean", "default": True},
                "preset": {"type": "string",
                           "enum": ["auto", "fast", "balanced", "high_quality",
                                    "max_quality"]},
                "dry_run": {"type": "boolean", "default": False,
                            "description": "Plan only; produce no video."},
                "strict": {"type": "boolean", "default": False,
                           "description": "Treat a QC failure as an error."},
                "out_dir": {"type": "string",
                            "description": "Directory to copy the finished MP4 "
                                           "into."},
            },
        },
    },
    {
        "name": "suggest_topics",
        "description": ("Propose concrete angles for a half-formed idea. Offline, "
                        "deterministic, no model required."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "count": {"type": "integer", "default": 5},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "list_templates",
        "description": ("Video *structures* (not skins): narrative beats, scene "
                        "count range, layout vocabulary, and what each is bad at."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_styles",
        "description": "Visual style profiles: palette, type, motion bias.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_platforms",
        "description": ("Delivery presets with resolution, aspect and safe-area "
                        "insets per platform."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "video_status",
        "description": "Status and result of a previously started job.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
]


def _text(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False,
                                                            indent=2, default=str)}]}


def _create_video(args: dict[str, Any]) -> dict[str, Any]:
    from ..runtime.engine import get_runtime

    source = args.get("source")
    request = CreateVideoRequest(
        prompt=args.get("prompt"),
        topic=args.get("topic"),
        source={"kind": "auto", "value": source} if source else None,
        script=args.get("script"),
        title=args.get("title"),
        language=args.get("language") or "zh-CN",
        platform=args.get("platform"),
        aspect=args.get("aspect"),
        width=args.get("width"),
        height=args.get("height"),
        duration_sec=args.get("duration_sec"),
        scenes=args.get("scenes"),
        template=args.get("template"),
        style=args.get("style"),
        voice=args.get("voice"),
        captions=args.get("captions", True),
        preset=args.get("preset") or "auto",
        out_dir=args.get("out_dir"),
        dry_run=bool(args.get("dry_run")),
        strict=bool(args.get("strict")),
        created_by="mcp",
    )
    return get_runtime().create_video(request).to_dict()


def _suggest_topics(args: dict[str, Any]) -> dict[str, Any]:
    from ..planning.topic_planner import TopicPlanner

    request = CreateVideoRequest(prompt=args["prompt"])
    rows = TopicPlanner().suggest(request, count=int(args.get("count") or 5))
    return {"suggestions": [item.model_dump(mode="json") for item in rows]}


def _list_templates(_: dict[str, Any]) -> dict[str, Any]:
    from ..templates.registry import get_registry

    return {"templates": [m.model_dump(mode="json") for m in get_registry().templates()]}


def _list_styles(_: dict[str, Any]) -> dict[str, Any]:
    from ..templates.registry import get_registry

    return {"styles": [s.model_dump(mode="json") for s in get_registry().styles()]}


def _list_platforms(_: dict[str, Any]) -> dict[str, Any]:
    from ..core.request import PLATFORM_PRESETS

    return {"platforms": [p.model_dump(mode="json") for p in PLATFORM_PRESETS.values()]}


def _video_status(args: dict[str, Any]) -> dict[str, Any]:
    from ..runtime.engine import get_runtime

    result = get_runtime().job_result(str(args["job_id"]))
    if result is None:
        return {"ok": False, "error": f"unknown job: {args['job_id']}"}
    return result.to_dict()


HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "create_video": _create_video,
    "suggest_topics": _suggest_topics,
    "list_templates": _list_templates,
    "list_styles": _list_styles,
    "list_platforms": _list_platforms,
    "video_status": _video_status,
}


def call_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute one tool. Returns the MCP result object (never raises)."""
    handler = HANDLERS.get(name)
    if handler is None:
        return {"isError": True, "content": [{"type": "text",
                                             "text": f"unknown tool: {name}"}]}
    try:
        return _text(handler(args or {}))
    except Exception as exc:  # noqa: BLE001 - a tool error is data, not a crash
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"isError": True, "content": [{"type": "text",
                                             "text": json.dumps(payload,
                                                                ensure_ascii=False)}]}


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC message. Returns None for notifications."""
    method = message.get("method")
    message_id = message.get("id")

    if method == "initialize":
        return _ok(message_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "html-video-workflow", "version": __version__},
        })
    if method in {"notifications/initialized", "initialized"}:
        return None
    if method == "ping":
        return _ok(message_id, {})
    if method == "tools/list":
        return _ok(message_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        return _ok(message_id, call_tool(str(params.get("name")),
                                         params.get("arguments") or {}))
    if message_id is None:
        return None
    return {"jsonrpc": "2.0", "id": message_id,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def _ok(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def serve_stdio(stdin=None, stdout=None) -> int:
    """Read newline-delimited JSON-RPC from stdin, write responses to stdout.

    ``stdout`` must carry protocol traffic only. Logging goes to stderr through
    the normal logger — a stray ``print`` here corrupts the stream and the client
    simply stops working, which is a miserable thing to debug.
    """
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle_message(message)
        if response is None:
            continue
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(serve_stdio())
