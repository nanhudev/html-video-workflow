"""The CI one-click end-to-end check, with a diagnosis that cannot be lost.

The runner's console log needs a browser session or a personal token to read, so
when this step goes red the *reason* has to travel through a channel that
anonymous read access can see. Commit statuses are that channel.

Every step below is therefore wrapped so that any failure — a missing file, a
CLI that never ran, an unexpected exception — still posts what was observed
before dying. A previous version of this check failed on CI and reported
nothing at all, which cost a full build cycle to discover.

What it does:

1. reports which providers the runner can actually use,
2. runs the documented one-click command,
3. if that fails, runs it again with the deterministic placeholder voice, which
   separates "the pipeline is broken" from "this runner has no voice installed",
4. posts every observation as a commit status before exiting.

Exit status is 0 only when the documented command produced a real MP4.

Usage (CI only)::

    python scripts/e2e_one_click.py
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import traceback

OUT_DIR = "e2e-out"
PROMPT = "Why local AI matters"
BASE_ARGS = ["--width", "320", "--height", "180", "--duration", "6",
             "--scenes", "1", "--out", OUT_DIR, "--json"]

#: (context, state, description) queued for upload
STATUSES: list[tuple[str, str, str]] = []


def remember(context: str, state: str, description: str) -> None:
    """Queue a status, and print it so the log is useful when it is readable."""
    text = " ".join((description or "").split())
    print(f"[status] {context} -> {state}: {text}", flush=True)
    STATUSES.append((context, state, text))


def run(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    print("$", " ".join(args), flush=True)
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def ready_providers() -> str:
    """Which providers the runner can actually use, in one short line."""
    try:
        proc = run(["html-video", "providers", "--json"], timeout=300)
        rows = json.loads(proc.stdout or "[]")
    except Exception as exc:  # noqa: BLE001 - a finding, not a crash
        return f"providers unreadable: {type(exc).__name__}: {exc}"

    ready = [f"{row.get('type')}:{row.get('id')}" for row in rows
             if isinstance(row, dict) and row.get("state") == "ready"]
    return ("ready -> " + ", ".join(ready)) if ready else \
        "NO provider in state 'ready'"


def attempt(label: str, extra: list[str] | None = None) -> dict:
    """Run the one-click command once and describe exactly what happened."""
    extra = extra or []
    out = pathlib.Path(f"cli-result-{label}.json")
    err = pathlib.Path(f"cli-stderr-{label}.txt")

    args = ["html-video", "generate", PROMPT, *BASE_ARGS, *extra]
    try:
        proc = run(args)
    except Exception as exc:  # noqa: BLE001
        detail = f"could not run the CLI: {type(exc).__name__}: {exc}"
        remember(f"e2e/{label}", "failure", detail)
        return {"ok": False, "detail": detail}

    out.write_text(proc.stdout or "", encoding="utf-8")
    err.write_text(proc.stderr or "", encoding="utf-8")

    raw = (proc.stdout or "").strip()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        tail = (proc.stderr or "").strip()[-200:] or raw[-200:]
        detail = f"exit {proc.returncode}, printed no JSON: {tail}"
        remember(f"e2e/{label}", "failure", detail)
        return {"ok": False, "detail": detail, "returncode": proc.returncode}

    if not payload.get("ok"):
        detail = (f"[{payload.get('error_code') or '?'}] "
                  f"{payload.get('error') or 'no error message'}")
        remember(f"e2e/{label}", "failure", detail)
        return {"ok": False, "detail": detail, "returncode": proc.returncode}

    video = payload.get("video_path")
    if not video or not pathlib.Path(video).exists():
        detail = f"reported ok but there is no MP4 at {video!r}"
        remember(f"e2e/{label}", "failure", detail)
        return {"ok": False, "detail": detail}

    try:
        probe = run(["ffprobe", "-v", "error", "-show_entries",
                     "format=duration", "-of",
                     "default=noprint_wrappers=1:nokey=1", video], timeout=120)
        duration = float((probe.stdout or "").strip())
    except Exception as exc:  # noqa: BLE001
        detail = f"ffprobe could not read {video!r}: {type(exc).__name__}"
        remember(f"e2e/{label}", "failure", detail)
        return {"ok": False, "detail": detail, "video": video}

    size = pathlib.Path(video).stat().st_size
    remember(f"e2e/{label}", "success", f"{size} bytes, {duration:.2f}s")
    return {"ok": True, "video": video, "size": size, "duration": duration}


def dry_run_diagnosis() -> None:
    """Plan only. Shows which providers the router picked, or refused to pick."""
    args = ["html-video", "generate", PROMPT, *BASE_ARGS, "--dry-run"]
    try:
        proc = run(args, timeout=300)
        payload = json.loads((proc.stdout or "").strip() or "{}")
    except Exception as exc:  # noqa: BLE001
        remember("e2e/dry-run", "failure",
                 f"dry run unusable: {type(exc).__name__}")
        return

    if not payload.get("ok"):
        remember("e2e/dry-run", "failure",
                 f"[{payload.get('error_code') or '?'}] "
                 f"{payload.get('error') or 'no error message'}")
        return
    providers = ", ".join(f"{k}={v}" for k, v in
                          (payload.get("providers") or {}).items())
    reasons = " / ".join(payload.get("reasons") or [])[:60]
    remember("e2e/dry-run", "success",
             f"planned with {providers or 'no providers'}; {reasons}")


def main() -> int:
    remember("e2e/providers", "success", ready_providers())

    documented = attempt("cli")
    if documented["ok"]:
        return 0

    # Tails of the captured streams, so a red build can be read without logs.
    err_tail = ""
    try:
        err_tail = pathlib.Path("cli-stderr-cli.txt").read_text(
            encoding="utf-8", errors="replace").strip()[-130:]
    except Exception:  # noqa: BLE001
        pass
    if err_tail:
        remember("e2e/cli/stderr", "failure", err_tail)

    # CI runners ship no installed voice. Repeating the same command with the
    # deterministic placeholder voice separates "the pipeline is broken" from
    # "this runner cannot speak".
    fallback = attempt("cli-mock-tts", ["--tts", "mock_tts"])
    dry_run_diagnosis()

    remember("e2e/cli", "failure",
             "documented command failed: " + documented["detail"]
             + " || mock_tts: " + ("worked" if fallback["ok"]
                                   else fallback["detail"]))
    return 1


def report() -> None:
    for context, state, description in STATUSES:
        subprocess.run([sys.executable, "scripts/ci_status.py",
                        context, state, description[:130]], check=False)


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    except Exception:  # noqa: BLE001 - the whole point is to survive and report
        traceback.print_exc()
        remember("e2e/cli", "failure",
                 "diagnostic crashed: "
                 + traceback.format_exc().strip().splitlines()[-1][:100])
    finally:
        # A status that is never posted is the failure mode this file exists to
        # prevent, so it is posted from `finally`, not from the happy path.
        try:
            report()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    raise SystemExit(code)
