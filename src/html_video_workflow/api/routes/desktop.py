"""Desktop integration: "打开文件位置" and the finished-work list.

Small, and load-bearing. The last thing a first-time user does is look for the
file they just made, and if the answer is "it is somewhere under your data
directory" then the product failed at the final step.

The path check is not boilerplate. These endpoints are reachable from a browser
page, so without a containment test they are a general-purpose file opener for
whatever else is on the machine. Everything is confined to the app home, and
``resolve_within`` resolves symlinks and ``..`` before comparing.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from ...config.paths import hv_home, outputs_dir
from ...utils.desktop import DesktopUnavailable, open_file, resolve_within, reveal

router = APIRouter(prefix="/v1", tags=["desktop"])

_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".srt": "text/plain; charset=utf-8",
    ".json": "application/json",
}


class PathRequest(BaseModel):
    path: str


def _describe(video: Path) -> dict[str, Any]:
    stat = video.stat()
    thumb = video.with_suffix(".jpg")
    return {
        "name": video.name,
        "path": str(video),
        "size_mb": round(stat.st_size / 1048576, 2),
        "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "thumbnail": str(thumb) if thumb.exists() else None,
        # The title is the part before the job id, which is how `stages.py`
        # names the file. Losing the suffix is not a guess: it is the format.
        "title": video.stem.rsplit("-job_", 1)[0],
    }


@router.get("/outputs")
def list_outputs(limit: int = 50) -> dict[str, Any]:
    """Finished videos, newest first. Reads the filesystem, not a database."""
    directory = outputs_dir()
    if not directory.is_dir():
        return {"directory": str(directory), "items": []}
    videos = sorted(directory.glob("*.mp4"), key=lambda p: p.stat().st_mtime,
                    reverse=True)
    items = []
    for video in videos[: max(1, min(limit, 500))]:
        try:
            items.append(_describe(video))
        except OSError:  # pragma: no cover - a file vanishing mid-scan
            continue
    return {"directory": str(directory), "items": items}


@router.get("/outputs/{filename}")
def serve_output(filename: str) -> Response:
    """Stream a finished file back to the browser, with byte-range support.

    The wizard plays the result inline. Without this the only way to see the
    video would be "open the folder and double-click it", which is one more
    step than a product should ask for — and it is not even possible if the
    browser is on another machine.

    Range support is not optional for video: without it a `<video>` element
    plays from the start but scrubbing does nothing, which reads as a broken
    player rather than a missing feature.
    """
    try:
        target = resolve_within(str(outputs_dir() / filename), outputs_dir())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在：{filename}")
    media_type = _MEDIA_TYPES.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(target, media_type=media_type,
                        headers={"Accept-Ranges": "bytes",
                                 "Cache-Control": "no-cache"})


@router.post("/desktop/reveal")
def reveal_path(payload: PathRequest) -> dict[str, Any]:
    """Show a file in the OS file manager, selecting it."""
    target = _contained(payload.path)
    try:
        detail = reveal(target)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"文件不存在：{exc}") from exc
    except DesktopUnavailable as exc:
        # 501 rather than 500: nothing is broken, this machine simply has no
        # file manager to show. The path travels back so the UI can display it.
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return {"ok": True, "detail": detail, "path": str(target)}


@router.post("/desktop/open")
def open_path(payload: PathRequest) -> dict[str, Any]:
    """Open a file or folder with the OS default handler."""
    target = _contained(payload.path)
    try:
        detail = open_file(target)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"文件不存在：{exc}") from exc
    except DesktopUnavailable as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return {"ok": True, "detail": detail, "path": str(target)}


def _contained(raw: str) -> Path:
    try:
        return resolve_within(raw, hv_home())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
