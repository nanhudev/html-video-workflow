"""Entry points that are not the installed console script.

``html-video`` is what a user is told to type, but a console script only exists
inside whichever environment was installed last — and it can survive in ``bin/``
after its own ``site-packages`` has been hollowed out, which is how a working
machine reported ``ModuleNotFoundError`` and blamed the project. Module
execution and the dev harness both need to work without it, so they are checked
here rather than assumed.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, relative: str):
    """Import a script by path. These files are not modules of the package."""
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ----------------------------------------------------------------- module entry
def test_the_cli_runs_as_a_module() -> None:
    """`python -m html_video_workflow.cli` is the documented fallback."""
    proc = subprocess.run(
        [sys.executable, "-m", "html_video_workflow.cli", "--help"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, proc.stderr[-400:]
    assert "usage: html-video" in proc.stdout


def test_the_cli_module_prints_the_full_command_set() -> None:
    """Not merely executable: it is the same CLI, not a stub."""
    proc = subprocess.run(
        [sys.executable, "-m", "html_video_workflow.cli", "--help"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    for command in ("doctor", "create", "generate", "studio"):
        assert command in proc.stdout, f"{command} missing from --help"


# -------------------------------------------------------------------- dev.py
def test_dev_detects_an_interpreter_that_cannot_import_the_package(
    tmp_path: Path,
) -> None:
    """Existence is not usability — an absent interpreter is simply unusable."""
    dev = _load("hvw_dev", "scripts/dev.py")
    assert dev._can_import(tmp_path / "nope" / "python.exe") is False


def test_dev_never_picks_an_interpreter_that_cannot_run_the_project() -> None:
    """Whatever it resolves must actually import the package.

    This is the failure being guarded against: a dead app-home virtualenv whose
    files are all present but which cannot run the code it claims to own.
    """
    dev = _load("hvw_dev", "scripts/dev.py")
    python = dev._python()
    probe = subprocess.run(
        [python, "-c", "import html_video_workflow"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert probe.returncode == 0, f"{python} cannot import the package"


def test_dev_cli_command_is_launchable() -> None:
    """The resolved CLI prefix runs, whichever form it picked."""
    dev = _load("hvw_dev", "scripts/dev.py")
    proc = subprocess.run(
        [*dev._cli(), "--help"], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, proc.stderr[-400:]
    assert "usage: html-video" in proc.stdout


# ----------------------------------------------------------- e2e_one_click.py
def test_the_e2e_check_resolves_a_cli_that_runs() -> None:
    """Its whole purpose is diagnosis; it must not fail for want of a binary."""
    e2e = _load("hvw_e2e", "scripts/e2e_one_click.py")
    proc = subprocess.run(
        [*e2e.cli_command(), "--help"], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, proc.stderr[-400:]


def test_the_e2e_check_reads_subprocess_output_without_crashing(tmp_path: Path) -> None:
    """A Chinese error message must not become an unexplained exception.

    The check exists to survive odd output, and `text=True` defaults to the
    console's locale encoding — which on a zh-CN Windows runner cannot decode
    half of what a provider may say.
    """
    e2e = _load("hvw_e2e", "scripts/e2e_one_click.py")
    script = tmp_path / "says_chinese.py"
    script.write_text(
        "import sys\n"
        "sys.stdout.buffer.write('语音合成失败：没有找到引擎\\n'.encode('utf-8'))\n",
        encoding="utf-8",
    )
    proc = e2e.run([sys.executable, str(script)], timeout=60)
    assert proc.returncode == 0
    assert "语音合成失败" in (proc.stdout or "")


@pytest.mark.parametrize("relative", ["scripts/dev.py", "scripts/e2e_one_click.py"])
def test_the_scripts_are_importable_without_launching_anything(
    relative: str,
) -> None:
    """Importing a diagnostic must not run it."""
    _load(f"hvw_{Path(relative).stem}", relative)
