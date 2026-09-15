"""BrowserRenderService — the abstraction above "how do we get pixels".

The renderer provider should not know whether pixels come from a local Chrome, a
containerised Playwright, or a remote farm. This service is that seam, and it
exists mainly so a future remote renderer can be added without touching the
compiler or the provider.

Today there is exactly one implementation (local Chromium). The abstraction earns
its place by being honest about *availability*: `probe()` never reports ready
without asking the real browser.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..utils.logging import get_logger
from .capture import BrowserCapture, CaptureResult

log = get_logger("renderers.service")


@dataclass(frozen=True)
class RenderRequest:
    html_path: str
    out_dir: str
    width: int
    height: int
    strategy: str = "screenshot"
    frames: int = 1
    duration_ms: int = 4000
    #: Where the caller wants the frame written. The pipeline names its frames
    #: `scene-NNN.png` and expects the renderer to honour that name, so the
    #: caller must be able to say so rather than discovering `frame.png` later.
    image_path: str | None = None


@dataclass(frozen=True)
class RenderResult:
    ok: bool
    images: list[str]
    strategy: str
    reason: str = ""
    seconds: float = 0.0


class BrowserRenderService:
    """Local-browser implementation of the render seam."""

    def __init__(self, capture: BrowserCapture | None = None) -> None:
        self.capture = capture or BrowserCapture()

    @property
    def backend(self) -> str:
        return "local-chromium"

    def probe(self) -> tuple[bool, str]:
        """Ask the real browser, every time. Nothing is cached here.

        Caching a browser probe is how a renderer reports "ready" for twenty
        minutes after someone uninstalled Chrome, then fails mid-job.
        """
        browser = BrowserCapture._resolve_browser()
        if getattr(browser, "available", False) and getattr(browser, "path", None):
            return True, f"{browser.name} @ {browser.path}"
        return False, "no Chromium-compatible browser found"

    def render(self, request: RenderRequest) -> RenderResult:
        import time
        from pathlib import Path

        out_dir = Path(request.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        started = time.perf_counter()
        if request.strategy == "frame_sequence":
            result: CaptureResult = self.capture.frame_sequence(
                request.html_path,
                out_dir,
                width=request.width,
                height=request.height,
                frames=request.frames,
                duration_ms=request.duration_ms,
            )
        else:
            png = Path(request.image_path) if request.image_path else out_dir / "frame.png"
            png.parent.mkdir(parents=True, exist_ok=True)
            result = self.capture.screenshot(
                request.html_path,
                png,
                width=request.width,
                height=request.height,
            )
        elapsed = time.perf_counter() - started

        return RenderResult(
            ok=result.ok,
            images=result.outputs if result.ok else [],
            strategy=result.strategy,
            reason=result.reason,
            seconds=round(elapsed, 3),
        )


class NullRenderService(BrowserRenderService):
    """Always-unavailable service, for tests and for a headless CI fallback.

    Reporting failure honestly beats pretending: a caller that uses this gets a
    clear "no backend" instead of silently-empty output.
    """

    def __init__(self, reason: str = "no render backend configured") -> None:
        self._reason = reason
        self.capture = BrowserCapture()

    @property
    def backend(self) -> str:
        return "null"

    def probe(self) -> tuple[bool, str]:
        return False, self._reason

    def render(self, request: RenderRequest) -> RenderResult:  # noqa: D102
        del request
        return RenderResult(ok=False, images=[], strategy="null", reason=self._reason)


def build_service(settings: dict[str, Any] | None = None) -> BrowserRenderService:
    """Pick a backend from configuration.

    Only `local` is implemented. Selecting anything else returns a service that
    says it cannot render, rather than silently falling back to local and hiding
    a misconfiguration.
    """
    backend = str((settings or {}).get("render_backend") or "local").lower()
    if backend in {"local", "chromium", "chrome"}:
        return BrowserRenderService()
    return NullRenderService(reason=f"render backend '{backend}' is not available")
