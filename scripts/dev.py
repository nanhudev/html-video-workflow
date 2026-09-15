#!/usr/bin/env python
"""Single development launcher.

One command to get a working environment, so contributors do not have to read
`DEVELOPMENT.md` and guess which interpreter to use.

    python scripts/dev.py setup      # create the venv, install deps, npm install
    python scripts/dev.py doctor     # hardware + toolchain + provider honesty
    python scripts/dev.py test       # pytest + studio typecheck
    python scripts/dev.py serve      # REST API on :8787
    python scripts/dev.py studio     # Vite dev server on :5173
    python scripts/dev.py render "topic"
    python scripts/dev.py clean      # drop the cache (keeps projects/outputs)

Everything heavy defaults to the data drive. Interpreter selection, the stale
`pip.exe` trap and `HVW_HOME` normalisation are handled here so they cannot bite
a new contributor.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "apps" / "studio"


def _data_home() -> Path:
    """Same rule as config/paths.py, so the launcher and the app agree."""
    env = os.environ.get("HVW_HOME")
    if env:
        raw = env.strip().strip('"').strip("'")
        if len(raw) >= 3 and raw[0] == "/" and raw[1].isalpha() and raw[2] == "/":
            raw = f"{raw[1].upper()}:{raw[2:]}"
        p = Path(raw)
        if not p.is_absolute():
            raise SystemExit(
                f"HVW_HOME={env!r} is not absolute. Use D:\\html-video-workflow "
                "or the Git Bash alias /d/html-video-workflow."
            )
        return p
    for drive in ("D:", "E:"):
        if Path(drive + "/").exists():
            return Path(drive + "/html-video-workflow")
    return Path.home() / ".html-video-workflow"


HOME = _data_home()
VENV = HOME / "venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
CLI = VENV / ("Scripts/html-video.exe" if os.name == "nt" else "bin/html-video")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["HVW_HOME"] = str(HOME)
    return env


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> int:
    printable = " ".join(str(c) for c in cmd)
    print(f"\n$ {printable}", flush=True)
    result = subprocess.run(cmd, cwd=str(cwd or ROOT), env=_env())
    if check and result.returncode != 0:
        raise SystemExit(f"command failed ({result.returncode}): {printable}")
    return result.returncode


def _require_venv() -> None:
    if not PY.exists():
        raise SystemExit(
            f"No interpreter at {PY}\nRun: python scripts/dev.py setup"
        )


def _npm() -> str:
    for name in ("npm.cmd", "npm"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit("npm not found on PATH — install Node.js 20+ first")


# ------------------------------------------------------------------ commands
def cmd_setup(args: argparse.Namespace) -> int:
    HOME.mkdir(parents=True, exist_ok=True)
    if not PY.exists():
        print(f"creating venv at {VENV}")
        _run([sys.executable, "-m", "venv", str(VENV)])
    # `python -m pip`, never `pip.exe`: a stray Scripts/pip.exe can belong to a
    # different environment entirely and silently install into the wrong place.
    _run([str(PY), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    _run([str(PY), "-m", "pip", "install", "-e", ".[api,dev]"])

    if not STUDIO.exists():
        print("no apps/studio directory — skipping the frontend")
        return 0
    _run([_npm(), "install"], cwd=STUDIO)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    _require_venv()
    return _run([str(CLI), "doctor"])


def cmd_test(args: argparse.Namespace) -> int:
    _require_venv()
    rc = _run([str(PY), "-m", "pytest", "tests", "-q"])
    if STUDIO.exists() and (STUDIO / "node_modules").exists():
        rc |= _run([_npm(), "run", "typecheck"], cwd=STUDIO, check=False)
    else:
        print("\n(studio deps absent — run `python scripts/dev.py setup`)")
    return rc


def cmd_serve(args: argparse.Namespace) -> int:
    _require_venv()
    return _run([str(CLI), "serve", "--host", args.host, "--port", str(args.port)])


def cmd_studio(args: argparse.Namespace) -> int:
    if not (STUDIO / "node_modules").exists():
        raise SystemExit("studio deps missing — run `python scripts/dev.py setup`")
    print(f"\nStudio: http://localhost:5173   (API should be on :{args.port})")
    return _run([_npm(), "run", "dev"], cwd=STUDIO)


def cmd_render(args: argparse.Namespace) -> int:
    _require_venv()
    argv = [str(CLI), "create", args.prompt, "--preset", args.preset]
    if args.render:
        argv.append("--render")
    return _run(argv)


def cmd_clean(args: argparse.Namespace) -> int:
    cache = HOME / "cache"
    if not cache.exists():
        print(f"no cache at {cache}")
        return 0
    files = sum(len(f) for _, _, f in os.walk(cache))
    if not args.yes:
        print(f"About to delete {files} cached files under {cache}")
        print("Projects, outputs and logs are NOT touched.")
        if input("Continue? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("aborted")
            return 1
    shutil.rmtree(cache, ignore_errors=True)
    cache.mkdir(parents=True, exist_ok=True)
    print(f"cleared {files} files from {cache}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="dev.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="create the venv and install everything")

    p = sub.add_parser("doctor", help="hardware + toolchain + provider honesty")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("test", help="pytest + studio typecheck")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("serve", help="run the REST API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("studio", help="run the Vite dev server")
    p.add_argument("--port", type=int, default=8787, help="API port to expect")
    p.set_defaults(func=cmd_studio)

    p = sub.add_parser("render", help="create and render a project")
    p.add_argument("prompt")
    p.add_argument("--preset", default="fast",
                   choices=["auto", "fast", "balanced", "high_quality", "max_quality"])
    p.add_argument("--render", action="store_true", default=True)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("clean", help="drop the render cache")
    p.add_argument("-y", "--yes", action="store_true", help="skip the prompt")
    p.set_defaults(func=cmd_clean)

    args = parser.parse_args()
    if args.command == "setup":
        return cmd_setup(args)
    print(f"HVW_HOME = {HOME}")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
