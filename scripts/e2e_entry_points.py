"""Exercise the SDK, REST and MCP entry points, reporting each one separately.

The CLI one-click lives in ``scripts/e2e_one_click.py``; this is the rest of the
public surface. Each entry point posts its own commit status, so a red build
says *which* entry point broke rather than just that the job failed — the
runner's console log is not readable without a browser session.

All three are expected to produce a real MP4 through ``VideoRuntime.create_video``
and nothing else.

Usage (CI only)::

    python scripts/e2e_entry_points.py
"""
from __future__ import annotations

import pathlib
import sys
import traceback

STATUSES: list[tuple[str, str, str]] = []

PROMPT = "Why local AI matters"
SHAPE = {"width": 320, "height": 180, "duration_sec": 6, "scenes": 1}


def remember(context: str, state: str, description: str) -> None:
    text = " ".join((description or "").split())
    try:
        print(f"[status] {context} -> {state}: {text}", flush=True)
    except Exception:  # noqa: BLE001 - the status outlives the console
        pass
    STATUSES.append((context, state, text))


def check_sdk() -> bool:
    from html_video_workflow import create_video

    result = create_video(PROMPT, out_dir="e2e-out-sdk", **SHAPE)
    if not result.ok:
        remember("e2e/sdk", "failure",
                 f"[{result.error_code}] {result.error}")
        return False
    if not result.video_path or not pathlib.Path(result.video_path).exists():
        remember("e2e/sdk", "failure", f"no MP4 at {result.video_path!r}")
        return False
    size = pathlib.Path(result.video_path).stat().st_size
    remember("e2e/sdk", "success",
             f"positional prompt -> {size} bytes at {result.video_path}")
    return True


def check_rest() -> bool:
    from fastapi.testclient import TestClient

    from html_video_workflow.api.app import create_app

    client = TestClient(create_app())
    body = {"prompt": PROMPT, "out_dir": "e2e-out-api", **SHAPE}

    sync = client.post("/v1/videos", json=body, params={"wait": "true"})
    if sync.status_code != 200 or not sync.json().get("ok"):
        remember("e2e/rest", "failure",
                 f"wait=true -> {sync.status_code}: {sync.text[:110]}")
        return False
    video = sync.json().get("video_path")
    if not video or not pathlib.Path(video).exists():
        remember("e2e/rest", "failure", f"wait=true produced no MP4: {video!r}")
        return False

    async_ = client.post("/v1/videos", json=body, params={"wait": "false"})
    job_id = async_.json().get("job_id") if async_.status_code == 200 else None
    if not job_id:
        remember("e2e/rest", "failure",
                 f"wait=false -> {async_.status_code}: {async_.text[:110]}")
        return False

    # The unknown-job lookup is part of the contract too: it must be a 404 with
    # a machine-readable code, not a 401/500 or a bare string.
    missing = client.get("/v1/videos/job_never_issued")
    if missing.status_code != 404:
        remember("e2e/rest", "failure",
                 f"GET /v1/videos/<unknown> -> {missing.status_code}, expected 404")
        return False

    remember("e2e/rest", "success",
             f"wait=true -> MP4; wait=false -> {job_id}; unknown job -> 404")
    return True


def check_mcp() -> bool:
    import json

    from html_video_workflow.mcp import handle_message

    def call(method: str, **params):
        return handle_message({"jsonrpc": "2.0", "id": 1,
                               "method": method, "params": params})

    tools = call("tools/list")["result"]["tools"]
    names = {tool["name"] for tool in tools}
    required = {"create_video", "suggest_topics", "list_templates",
                "list_styles", "list_platforms", "video_status"}
    absent = sorted(required - names)
    if absent:
        remember("e2e/mcp", "failure", f"missing tools: {', '.join(absent)}")
        return False

    templates = json.loads(call("tools/call", name="list_templates")
                           ["result"]["content"][0]["text"]).get("templates")
    if not templates:
        remember("e2e/mcp", "failure", "list_templates returned nothing")
        return False

    result = call("tools/call", name="create_video",
                  arguments={"prompt": PROMPT, "out_dir": "e2e-out-mcp",
                             **SHAPE})
    payload = json.loads(result["result"]["content"][0]["text"])
    if not payload.get("ok"):
        remember("e2e/mcp", "failure",
                 f"create_video -> [{payload.get('error_code')}] "
                 f"{payload.get('error')}")
        return False

    remember("e2e/mcp", "success",
             f"{len(tools)} tools; create_video produced "
             f"{payload.get('video_path')}")
    return True


def main() -> int:
    ok = True
    for name, check in (("sdk", check_sdk), ("rest", check_rest),
                        ("mcp", check_mcp)):
        try:
            ok &= bool(check())
        except Exception as exc:  # noqa: BLE001 - report, then keep going
            traceback.print_exc()
            remember(f"e2e/{name}", "failure",
                     f"{name} raised {type(exc).__name__}: {exc}")
            ok = False
    return 0 if ok else 1


def report() -> None:
    import subprocess

    for context, state, description in STATUSES:
        subprocess.run([sys.executable, "scripts/ci_status.py",
                        context, state, description[:130]], check=False)


if __name__ == "__main__":
    # Windows hands a piped stdout the locale encoding, and a provider's error
    # text here is Chinese. An encoding failure while reporting would be
    # indistinguishable from a broken entry point, so relax the failure mode.
    try:
        from html_video_workflow.utils.console import make_streams_unfailing

        make_streams_unfailing()
    except Exception:  # noqa: BLE001 - reporting must survive even this
        pass

    code = 1
    try:
        code = main()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        remember("e2e/entry-points", "failure",
                 "harness crashed: "
                 + traceback.format_exc().strip().splitlines()[-1][:100])
    finally:
        try:
            report()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    raise SystemExit(code)
