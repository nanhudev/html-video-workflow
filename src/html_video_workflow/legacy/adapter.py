"""Compatibility adapter for the original ``scripts/workflow.py``.

The legacy script is **not modified and not moved**. It is loaded by path so the
old CLI keeps working while the new Runtime can call the same capabilities as
Providers.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..config.paths import legacy_script, repo_root
from ..utils.logging import get_logger

log = get_logger("legacy.adapter")

_MODULE: Any | None = None


def load_legacy_module() -> Any:
    """Import scripts/workflow.py as a module (cached)."""
    global _MODULE
    if _MODULE is not None:
        return _MODULE
    path = legacy_script()
    if not path.exists():
        raise FileNotFoundError(f"Legacy workflow script not found: {path}")
    spec = importlib.util.spec_from_file_location("html_video_workflow_legacy", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"Unable to load legacy module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["html_video_workflow_legacy"] = module
    spec.loader.exec_module(module)
    _MODULE = module
    return module


def legacy_templates() -> list[str]:
    module = load_legacy_module()
    return list(getattr(module, "TEMPLATES", {}))


def legacy_validate(project: dict[str, Any]) -> None:
    module = load_legacy_module()
    module.validate_project(project)


def render_legacy(
    project_path: str | Path,
    template: str = "academic-blue",
    build_dir: str | Path | None = None,
    preview_only: bool = False,
) -> Path | None:
    """Render with the untouched legacy pipeline via a subprocess.

    Returns the produced MP4 path, or None for preview-only runs.
    """
    project_path = Path(project_path).resolve()
    build = Path(build_dir).resolve() if build_dir else repo_root() / "build"
    build.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(legacy_script()),
        "render",
        "--project",
        str(project_path),
        "--template",
        template,
        "--build",
        str(build),
    ]
    if preview_only:
        cmd.append("--preview-only")
    log.info("legacy render: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(repo_root()))
    if result.returncode != 0:
        raise RuntimeError(
            "Legacy render failed: "
            + ((result.stderr or result.stdout or "").strip()[-500:])
        )
    for line in (result.stdout or "").splitlines():
        if line.startswith("VIDEO="):
            return Path(line.split("=", 1)[1].strip())
    return None


def research_legacy(urls: list[str], output: str | Path, max_chars: int = 18000,
                    delay: float = 1.0) -> Path:
    output = Path(output)
    cmd = [
        sys.executable,
        str(legacy_script()),
        "research",
        "--output",
        str(output),
        "--max-chars",
        str(max_chars),
        "--delay",
        str(delay),
    ]
    for url in urls:
        cmd += ["--url", url]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(repo_root()))
    if result.returncode != 0:
        raise RuntimeError(
            "Legacy research failed: " + (result.stderr or result.stdout or "")[-500:]
        )
    return output


def gallery_legacy(project_path: str | Path, build_dir: str | Path) -> Path:
    cmd = [
        sys.executable,
        str(legacy_script()),
        "gallery",
        "--project",
        str(Path(project_path).resolve()),
        "--build",
        str(Path(build_dir).resolve()),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(repo_root()))
    if result.returncode != 0:
        raise RuntimeError(
            "Legacy gallery failed: " + (result.stderr or result.stdout or "")[-500:]
        )
    for line in (result.stdout or "").splitlines():
        if line.startswith("GALLERY="):
            return Path(line.split("=", 1)[1].strip())
    return Path(build_dir) / "gallery.html"
