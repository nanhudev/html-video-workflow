"""Project storage — files on disk are the source of truth, DB is only an index."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from ..config.paths import projects_dir
from ..utils.logging import get_logger
from .ir import VideoProject
from .migrate import migrate

log = get_logger("project.store")


def new_project_id() -> str:
    stamp = time.strftime("%Y%m%d")
    return f"prj_{stamp}_{uuid.uuid4().hex[:8]}"


def project_dir(project_id: str) -> Path:
    path = projects_dir() / project_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "runtime").mkdir(exist_ok=True)
    return path


def save_project(project: VideoProject | dict[str, Any],
                 project_id: str | None = None) -> tuple[str, Path]:
    """Persist a project and return ``(id, path)``.

    The id is stamped onto the returned dict/object *and* the caller's object is
    updated in place, so an in-memory project can never disagree with the file it
    just wrote. Without this, a caller that saves an id-less project and then
    hands the same object to the runtime gets two different ids, and the job
    manifest ends up in a different directory from the run's work files.
    """
    data = project if isinstance(project, dict) else project.model_dump()
    data = migrate(data)
    if not data.get("id"):
        data["id"] = project_id or new_project_id()
    path = project_dir(data["id"]) / "project.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if isinstance(project, VideoProject):
        project.id = data["id"]
    else:
        project["id"] = data["id"]
    return data["id"], path


def load_project(project_id: str) -> VideoProject:
    path = project_dir(project_id) / "project.json"
    if not path.exists():
        raise FileNotFoundError(f"Project not found: {project_id} ({path})")
    data = json.loads(path.read_text(encoding="utf-8"))
    return VideoProject.model_validate(migrate(data))


def load_project_file(path: str | Path) -> VideoProject:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return VideoProject.model_validate(migrate(data))


def list_projects() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in sorted(projects_dir().iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        manifest = entry / "project.json"
        if not manifest.exists():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta = data.get("project", {})
        scenes = sum(len(s.get("scenes", [])) for s in data.get("sequences", []))
        items.append(
            {
                "id": data.get("id") or entry.name,
                "title": meta.get("title") or "Untitled",
                "language": meta.get("language") or "zh-CN",
                "scene_count": scenes,
                "updated_at": meta.get("updated_at")
                or time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(manifest.stat().st_mtime)),
                "path": str(manifest),
            }
        )
    return items


def write_runtime_json(project_id: str, name: str, payload: Any) -> Path:
    path = project_dir(project_id) / "runtime" / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return path


def read_runtime_json(project_id: str, name: str) -> Any | None:
    path = project_dir(project_id) / "runtime" / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
