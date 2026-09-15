"""Render determinism — the same IR must produce the same pixels twice.

Determinism is not pedantry; it is what makes visual regression possible. If a
frame shifts by half a pixel on every run, every golden comparison fails and the
team learns to ignore the diff — at which point the safety net is decorative.

Sources of nondeterminism this module removes:

* **fonts** — a browser that cannot find the declared family substitutes another,
  and every metric changes. We therefore name a fixed stack and never rely on a
  webfont that may not have loaded at screenshot time.
* **animation time** — CSS animations start when the element is painted, so two
  runs can capture different frames. We render to a *fixed animation time*
  instead: every animation is emitted as paused, then advanced to one known
  timestamp. That is the frame strategy decision recorded in DECISIONS.md D-012.
* **the clock** — anything reading `Date.now()` differs per run. Nothing in the
  generated document does.
* **randomness** — any variation must derive from an explicit seed, never from
  `Math.random()`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Fonts declared by the renderer, in priority order. These are chosen because
#: they are present on Windows, macOS and common Linux images, which keeps CI
#: screenshots comparable to local ones. A webfont would silently change every
#: golden image the moment it failed to load.
STABLE_FONT_STACK = (
    "'Segoe UI','Microsoft YaHei UI','PingFang SC','Hiragino Sans GB',"
    "'Noto Sans CJK SC',system-ui,-apple-system,sans-serif"
)

STABLE_MONO_STACK = (
    "'Cascadia Mono','Consolas','Menlo','DejaVu Sans Mono',ui-monospace,monospace"
)


@dataclass(frozen=True)
class RenderSeed:
    """Everything a render varies by, captured explicitly."""

    project_id: str
    scene_index: int
    variation_seed: int = 0
    theme: str = "default"
    layout: str = "auto"

    @property
    def value(self) -> int:
        payload = (
            f"{self.project_id}|{self.scene_index}|{self.variation_seed}|"
            f"{self.theme}|{self.layout}"
        )
        return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8], 16)


@dataclass
class DeterminismReport:
    """Recorded so a nondeterministic render can be debugged rather than cursed."""

    seed: RenderSeed
    checks: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        if passed:
            self.checks.append(f"{name}{(': ' + detail) if detail else ''}")
        else:
            self.violations.append(f"{name}{(': ' + detail) if detail else ''}")


#: Chromium flags that remove machine-specific rendering differences.
DETERMINISTIC_BROWSER_FLAGS: list[str] = [
    "--disable-gpu",
    # Subpixel antialiasing uses the monitor's physical layout; two machines
    # with the same OS can rasterise text differently with it on.
    "--disable-lcd-text",
    "--force-device-scale-factor=1",
    "--force-color-profile=srgb",
    "--hide-scrollbars",
    "--disable-features=LazyFrameLoading,LazyImageLoading",
    # Off by default in headless, but saying so survives a future default flip.
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    "--run-all-compositor-stages-before-draw",
    "--disable-new-content-rendering-timeout",
    "--font-render-hinting=none",
]

def browser_run_flags(profile_dir: str | Path) -> list[str]:
    """Flags for one headless run, including a private profile directory.

    A private ``--user-data-dir`` is what makes a render independent of the
    machine rather than of its configuration: no bookmarks bar, no extension,
    no signed-in profile, no "restore pages" prompt. More practically, on a
    locked-down or service-account machine the default profile directory may not
    be usable at all, and Chromium's response is to write no image rather than
    to explain itself.

    The first-run switches matter for the same reason. A freshly installed
    browser has never been launched, and its first-run experience can hold the
    process open long enough that ``--screenshot`` fires against nothing.
    """
    return [
        *DETERMINISTIC_BROWSER_FLAGS,
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-sync",
        "--disable-component-update",
    ]


#: Header injected into every document. `image-rendering` and text smoothing are
#: pinned because they are the two things most likely to differ across machines.
DETERMINISTIC_BASE_CSS = (
    "*{-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;"
    "text-rendering:optimizeLegibility}"
    "html,body{margin:0;padding:0;overflow:hidden;background-repeat:no-repeat}"
    "img{image-rendering:auto}"
)


def validate_document(html: str, *, seed: RenderSeed) -> DeterminismReport:
    """Check a generated document for nondeterminism we can detect statically.

    Real determinism is proven by rendering twice and comparing bytes; this is
    the cheap pre-check that catches the obvious offenders before we pay for two
    screenshots.
    """
    report = DeterminismReport(seed=seed)

    report.check(
        "no Math.random", "Math.random" not in html,
        "document uses Math.random" if "Math.random" in html else "",
    )
    report.check(
        "no Date.now / new Date",
        "Date.now" not in html and "new Date" not in html,
    )
    report.check(
        "no network fetch",
        not any(token in html for token in ("fetch(", "XMLHttpRequest")),
    )
    # Webfonts load asynchronously, so a screenshot may race them.
    report.check(
        "no @font-face / webfont link",
        "@font-face" not in html and "fonts.googleapis" not in html,
    )
    report.check(
        "fixed font stack declared",
        STABLE_FONT_STACK.split(",")[0] in html,
    )
    # Every animation must be paused and driven to a fixed time.
    has_anim = "animation:" in html
    has_paused = "animation-play-state:paused" in html or "HVW_FIXED_TIME" in html
    report.check(
        "animations pinned to a fixed time",
        (not has_anim) or has_paused,
        "found animation without play-state:paused" if has_anim and not has_paused else "",
    )
    return report


def seed_from(project_id: str | None, index: int, extra: dict[str, Any] | None = None) -> RenderSeed:
    return RenderSeed(
        project_id=project_id or "untitled",
        scene_index=index,
        variation_seed=int((extra or {}).get("variation_seed", 0)),
        theme=str((extra or {}).get("theme", "default")),
        layout=str((extra or {}).get("layout", "auto")),
    )
