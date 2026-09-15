"""BrowserCapture — get pixels out of a headless browser.

Two strategies exist, and the choice between them is the frame-strategy decision
recorded as **D-012**:

1. **`screenshot`** — one screenshot per scene, with animations pinned to a fixed
   time. Because every animation is emitted paused and then advanced to a known
   timestamp (see `determinism`), a screenshot is a *deterministic* frame rather
   than "whatever happened to be on screen". This is the default.

2. **`frame_sequence`** — the browser advances a virtual clock while we capture.
   This produces real motion within a scene, but it is only reproducible to the
   precision of the virtual-time budget, so golden comparisons must tolerate
   more drift.

There is no third option involving screen recording of a live window. It has been
tried in this genre of tooling and it makes renders machine-dependent: dropped
frames change the output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..utils.logging import get_logger

log = get_logger("renderers.capture")


@dataclass(frozen=True)
class CaptureResult:
    strategy: str
    ok: bool
    reason: str = ""
    outputs: list[str] = field(default_factory=list)


def capture_strategies() -> list[str]:
    return ["screenshot", "frame_sequence"]


class BrowserCapture:
    """Owns nothing but the mechanics of invoking a browser."""

    #: Wall-clock ceiling for one scene. Generous because virtual time, once
    #: past ~5s of animation, costs real CPU to simulate.
    TIMEOUT_SEC = 180

    def __init__(self) -> None:
        #: Created lazily, one per capture session, and deliberately *fresh*:
        #: a profile carried over from a previous render is a machine-specific
        #: input, which is the one thing this module exists to remove.
        self._profile_dir: str | None = None

    def profile_dir(self) -> str:
        """A writable, private browser profile for this capture session."""
        import tempfile

        if self._profile_dir is None:
            self._profile_dir = tempfile.mkdtemp(prefix="hvw-browser-")
        return self._profile_dir

    @staticmethod
    def _resolve_browser() -> Any:
        """Resolve through the module so tests can repoint it.

        Binding the function at import time would freeze the reference, and the
        renderer would keep reporting "ready" long after the browser was removed.
        See the identical note in `providers/renderer/legacy_html.py`.
        """
        from ..hardware import profile as hw_profile

        return hw_profile.resolve_browser()

    def screenshot(
        self,
        html_path: Any,
        png_path: Any,
        *,
        width: int,
        height: int,
        settle_ms: int = 1200,
    ) -> CaptureResult:
        """One deterministic frame.

        `--virtual-time-budget` advances timers before the screenshot is taken,
        so late-loading layout settles. It does not make the frame
        deterministic by itself — that comes from the paused animations in the
        document — but without it the first paint can arrive before fonts layout.
        """
        browser = self._resolve_browser()
        if not getattr(browser, "available", False) or not getattr(browser, "path", None):
            return CaptureResult(
                strategy="screenshot",
                ok=False,
                reason="no Chromium-compatible browser available",
            )

        from .determinism import browser_run_flags

        png_path = str(png_path)
        cmd = [
            browser.path,
            "--headless=new",
            *browser_run_flags(self.profile_dir()),
            f"--window-size={width},{height}",
            f"--virtual-time-budget={settle_ms}",
            f"--screenshot={png_path}",
            str(html_path),
        ]
        return self._run(cmd, "screenshot", [png_path])

    def frame_sequence(
        self,
        html_path: Any,
        out_dir: Any,
        *,
        width: int,
        height: int,
        frames: int = 1,
        duration_ms: int = 4000,
    ) -> CaptureResult:
        """Capture several instants of one scene.

        Each frame is still pinned to an explicit time; we are sampling the
        timeline rather than recording a live session. `frames` beyond the
        animation's own length yield duplicates, which downstream composition
        tolerates but gains nothing from.
        """
        browser = self._resolve_browser()
        if not getattr(browser, "available", False) or not getattr(browser, "path", None):
            return CaptureResult(
                strategy="frame_sequence",
                ok=False,
                reason="no Chromium-compatible browser available",
            )

        from .determinism import browser_run_flags

        outputs: list[str] = []
        step = max(1, duration_ms // max(1, frames))
        for index in range(frames):
            target = step * index
            png = str(out_dir / f"frame-{index:03d}.png")
            cmd = [
                browser.path,
                "--headless=new",
                *browser_run_flags(self.profile_dir()),
                f"--window-size={width},{height}",
                # Enough virtual time to reach `target` plus layout settling.
                f"--virtual-time-budget={target + 800}",
                f"--screenshot={png}",
                f"{html_path}#t={target}",
            ]
            result = self._run(cmd, "frame_sequence", [png])
            if not result.ok:
                return result
            outputs.append(png)
        return CaptureResult(
            strategy="frame_sequence", ok=True, outputs=outputs,
            reason=f"{frames} frames over {duration_ms}ms",
        )

    def _run(self, cmd: list[str], strategy: str, outputs: list[str]) -> CaptureResult:
        import subprocess

        try:
            completed = subprocess.run(
                cmd, capture_output=True, text=True, errors="replace", timeout=self.TIMEOUT_SEC
            )
        except subprocess.TimeoutExpired:
            return CaptureResult(
                strategy=strategy, ok=False,
                reason=f"browser timed out after {self.TIMEOUT_SEC}s",
            )
        except OSError as exc:
            return CaptureResult(strategy=strategy, ok=False, reason=f"could not start: {exc}")

        missing = [
            path for path in outputs
            if not _exists_nonempty(path)
        ]
        if missing:
            tail = (completed.stderr or completed.stdout or "").strip()[-300:]
            return CaptureResult(
                strategy=strategy,
                ok=False,
                reason=f"browser produced no image (rc={completed.returncode}): {tail}",
            )
        return CaptureResult(strategy=strategy, ok=True, outputs=outputs)


def _exists_nonempty(path: str) -> bool:
    from pathlib import Path

    candidate = Path(path)
    return candidate.exists() and candidate.stat().st_size > 0
