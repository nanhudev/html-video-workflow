"""Filesystem layout for the local-first runtime.

Everything heavy (venv, models, cache, projects, outputs, benchmarks) lives
outside the repository. By default we prefer a data drive (D:) when it exists,
because C: is usually the OS drive and video work is disk hungry.

Override with the ``HVW_HOME`` environment variable.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

ENV_HOME = "HVW_HOME"

#: Sub-directories created inside the home directory.
SUBDIRS = ("cache", "models", "projects", "outputs", "work", "logs")


def _normalize_env_home(env: str) -> Path | None:
    """Accept a Windows drive path, a POSIX path, or a Git-Bash drive alias.

    ``HVW_HOME=/d/html-video-workflow`` is what a user gets from Git Bash, but
    Python treats a leading ``/`` as relative on Windows, so it silently creates
    a literal ``\\d\\html-video-workflow`` directory *inside the repo* and writes
    gigabytes of cache there. Translate the alias, and reject anything that is
    still relative so the mistake fails loudly instead of filling the C: drive
    with a stray tree.
    """
    raw = env.strip().strip('"').strip("'")
    if not raw:
        return None
    # Git Bash / MSYS drive alias: /d/foo or /d/foo/bar -> D:/foo/bar
    if len(raw) >= 3 and raw[0] == "/" and raw[1].isalpha() and raw[2] == "/":
        raw = f"{raw[1].upper()}:{raw[2:]}"
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError(
            f"{ENV_HOME}={env!r} is not an absolute path. Use a Windows path "
            f"(D:\\html-video-workflow) or the Git Bash alias (/d/html-video-workflow)."
        )
    return path


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    env = os.environ.get(ENV_HOME)
    if env:
        normalized = _normalize_env_home(env)
        if normalized is not None:
            roots.append(normalized)
    # Prefer a secondary data drive when present.
    for drive in ("D:", "E:"):
        candidate = Path(drive + "/html-video-workflow")
        try:
            if Path(drive + "/").exists():
                roots.append(candidate)
        except OSError:
            continue
    roots.append(Path.home() / ".html-video-workflow")
    return roots


def resolve_home() -> Path:
    """Return the first usable home root (creating it if needed)."""
    errors: list[str] = []
    for root in _candidate_roots():
        try:
            root.mkdir(parents=True, exist_ok=True)
            return root
        except OSError as exc:  # pragma: no cover - depends on machine
            errors.append(f"{root}: {exc}")
    raise RuntimeError("Unable to resolve a writable home directory: " + "; ".join(errors))


@lru_cache(maxsize=1)
def hv_home() -> Path:
    return resolve_home()


def hv_path(*parts: str) -> Path:
    return hv_home().joinpath(*parts)


def ensure_layout() -> Path:
    """Create the full directory layout and return the home root."""
    home = hv_home()
    for name in SUBDIRS:
        (home / name).mkdir(parents=True, exist_ok=True)
    return home


def cache_dir() -> Path:
    return ensure_layout() / "cache"


def models_dir() -> Path:
    return ensure_layout() / "models"


def projects_dir() -> Path:
    return ensure_layout() / "projects"


def outputs_dir() -> Path:
    return ensure_layout() / "outputs"


def work_dir() -> Path:
    return ensure_layout() / "work"


def logs_dir() -> Path:
    return ensure_layout() / "logs"


def benchmarks_path() -> Path:
    return hv_home() / "benchmarks.json"


def hardware_path() -> Path:
    return hv_home() / "hardware.json"


def settings_path() -> Path:
    return hv_home() / "settings.json"


def database_path() -> Path:
    return hv_home() / "runtime.sqlite3"


def repo_root() -> Path:
    """Repository root, or the executable's folder in a packaged build.

    Three levels above this file is right for ``src/pkg/config/paths.py`` and
    wrong inside a bundle, where the same relative walk lands on PyInstaller's
    ``_internal`` directory. Both callers want "the folder the product lives
    in", so that is what they get.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def is_frozen() -> bool:
    """True when running from a packaged build rather than a source checkout."""
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """The directory a user sees: the folder containing the executable."""
    return repo_root()


def resource_dir() -> Path:
    """Where read-only assets were unpacked (templates, helper scripts).

    PyInstaller unpacks ``--add-data`` payloads under ``sys._MEIPASS``, which is
    a *different* directory from the executable in one-file builds and a
    ``_internal`` subfolder in one-dir builds. Asking the runtime rather than
    guessing is the only version of this that keeps working.
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return repo_root()


def bin_dir() -> Path | None:
    """A folder shipped next to the executable for bundled tools like ffmpeg.

    ``None`` in a source checkout: there the tools come from PATH, and
    pretending otherwise would send ``doctor`` looking for a directory that is
    not part of the repository.
    """
    if not is_frozen():
        return None
    candidate = bundle_root() / "bin"
    return candidate if candidate.is_dir() else None


def legacy_script() -> Path:
    """Path to the untouched legacy pipeline entry point."""
    return resource_dir() / "scripts" / "workflow.py"


def templates_dir() -> Path:
    return resource_dir() / "templates"


def schemas_dir() -> Path:
    return resource_dir() / "schemas"
