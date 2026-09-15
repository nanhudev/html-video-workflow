"""Serve the Studio frontend from the same process as the API.

Why this exists at all: the Studio is a headline part of the product, and until
now the only way to see it was `npm run dev` in a checkout. That makes Node a
runtime requirement for an end user, which it must not be — the product's
promise is "one prompt in, one MP4 out", not "install a JavaScript toolchain".

So the built frontend is served by the API application, and the order of the two
questions below is deliberate:

1. is there a built frontend on disk (packaged copy, then a source checkout)?
2. if not, say so plainly rather than serving a blank 404.

The frontend uses hash routing, so no history-fallback is needed: every route
lives at ``#/...`` under ``index.html``.
"""
from __future__ import annotations

import os
from pathlib import Path

def _is_built(directory: Path) -> bool:
    """Is this a *built* frontend, or an empty ``dist`` left by a failed build?

    Vite always emits both an entry document and a hashed asset bundle, so
    requiring both distinguishes "the build finished" from "the build started".
    Checking only ``index.html`` would call a half-written directory ready.
    """
    return (directory / "index.html").is_file() and \
        (directory / "assets").is_dir()


def studio_candidates() -> list[Path]:
    """Every place a built Studio might legitimately live, best first."""
    candidates: list[Path] = []

    override = os.environ.get("HVW_STUDIO_DIST")
    if override:
        candidates.append(Path(override))

    package_root = Path(__file__).resolve().parent.parent
    # Shipped inside the wheel by the release build.
    candidates.append(package_root / "studio_dist")
    # A source checkout: <repo>/src/html_video_workflow/api/studio.py
    candidates.append(package_root.parents[1] / "apps" / "studio" / "dist")
    return candidates


def studio_dist(candidates: list[Path] | None = None) -> Path | None:
    """The built frontend, or ``None`` when it has not been built.

    ``candidates`` is injectable so a test can ask the question without
    depending on whether this particular checkout happens to have been built.
    """
    for candidate in (studio_candidates() if candidates is None else candidates):
        if _is_built(candidate):
            return candidate
    return None


def mount_studio(app) -> Path | None:
    """Attach the built frontend to ``app`` at ``/``.

    Mounted last on purpose: a mount at ``/`` swallows every path that is not
    already claimed, so the API routers must be registered first or this would
    serve ``index.html`` in place of ``/v1/videos``.

    Returns the directory that was mounted, or ``None`` when the frontend has
    not been built — which is not an error, just a fact worth reporting.
    """
    from fastapi.staticfiles import StaticFiles

    dist = studio_dist()
    if dist is None:
        return None
    app.mount("/", StaticFiles(directory=str(dist), html=True), name="studio")
    return dist
