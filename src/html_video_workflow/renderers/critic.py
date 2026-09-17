"""VisualDesignCritic and SceneVariationPolicy.

Rule-driven, and deliberately score-free. See
`references/anti_ai_visual_rules.md` for why there is no "AI Feel 62/100" here:
there is no unit for it, and inventing one would turn a set of heuristics into a
number people optimise instead of looking at the frame.

Each finding carries severity, evidence and a concrete suggestion, so a warning
is something you can act on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

Severity = Literal["error", "warning", "info"]

#: CJK characters are roughly twice as wide as Latin; measuring both in
#: characters is how a perfectly readable Chinese line gets flagged as too long.
_CJK = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")


def _measure(text: str) -> int:
    """ apparent line length, normalised to Latin half-widths."""
    cjk = len(_CJK.findall(text))
    return len(text) + cjk


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: Severity
    message: str
    evidence: str = ""
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence,
            "suggestion": self.suggestion,
        }

    def __str__(self) -> str:
        head = f"[{self.severity.upper():7}] {self.rule}: {self.message}"
        if self.evidence:
            head += f"\n            evidence: {self.evidence}"
        if self.suggestion:
            head += f"\n            fix: {self.suggestion}"
        return head


@dataclass
class CritiqueReport:
    """Findings for one scene. Not a score, on purpose."""

    scene_index: int
    findings: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def has_blocking(self) -> bool:
        """There is no threshold to tune here — see the module docstring."""
        return bool(self.errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_index": self.scene_index,
            "count": len(self.findings),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "findings": [f.to_dict() for f in self.findings],
        }


# --------------------------------------------------------------- contrast math
def _srgb_channel(value: float) -> float:
    channel = value / 255.0
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_srgb_channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def parse_color(color: str) -> tuple[int, int, int] | None:
    """Parse `#rgb`, `#rrggbb`, or `rgb(r,g,b)`. Returns None if unparseable.

    Named colours are not resolved, because guessing them would produce a
    confidence we do not have.
    """
    text = (color or "").strip().lower()
    if text.startswith("#"):
        body = text[1:]
        if len(body) == 3:
            body = "".join(ch * 2 for ch in body)
        if len(body) == 6:
            try:
                return tuple(int(body[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
            except ValueError:
                return None
        return None
    match = re.match(r"rgba?\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)", text)
    if match:
        return tuple(int(match.group(i)) for i in (1, 2, 3))  # type: ignore[return-value]
    return None


def contrast_ratio(foreground: str, background: str) -> float | None:
    fg = parse_color(foreground)
    bg = parse_color(background)
    if fg is None or bg is None:
        return None
    l1, l2 = _luminance(fg), _luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# --------------------------------------------------------------------- critic
@dataclass
class SceneFacts:
    """What the critic inspects. Produced by the SceneCompiler."""

    index: int = 0
    layer_count: int = 0
    text_layer_count: int = 0
    motion_starts: list[float] = field(default_factory=list)
    motion_names: list[str] = field(default_factory=list)
    text_aligns: list[str] = field(default_factory=list)
    type_sizes: list[float] = field(default_factory=list)
    accent_layer_count: int = 0
    coverage: float = 0.0
    layout: str = ""
    safe_area_breaches: list[str] = field(default_factory=list)
    longest_line: int = 0
    text_color: str = "#ffffff"
    background_color: str = "#000000"
    largest_is_large_text: bool = False
    background_has_motion: bool = False
    #: Placed slot geometry, as ``(key, x, y)`` per layer that draws its own
    #: content. Two layers that share a position render on top of one another,
    #: which is the one defect a viewer reads as "broken" rather than "plain", so
    #: it is checked here rather than trusted to the layout engine. This includes
    #: figures and shapes, not just text: a body paragraph and a flow diagram
    #: handed the same band is exactly how a shipped scene ended up illegible.
    slot_positions: list[tuple[str, float, float]] = field(default_factory=list)


class VisualDesignCritic:
    """Twelve lintable rules. Deterministic, unit-free, no pixels involved."""

    #: Below this, type has no optical hierarchy.
    MIN_HIERARCHY_RATIO = 1.6
    MAX_TEXT_LAYERS = 5
    MAX_COVERAGE = 0.75
    #: CJK lines read best under ~44 full-width chars ≈ 88 half-widths.
    MAX_LINE_WIDTH = 88

    def review(self, facts: SceneFacts) -> CritiqueReport:
        report = CritiqueReport(scene_index=facts.index)
        checks = (
            self._uniform_motion,
            self._identical_motion,
            self._everything_centered,
            self._flat_hierarchy,
            self._too_many_layers,
            self._safe_area,
            self._accent_everywhere,
            self._negative_space,
            self._long_lines,
            self._contrast,
            self._no_ambient_motion,
            self._overlapping_layers,
        )
        for check in checks:
            finding = check(facts)
            if finding is not None:
                report.add(finding)
        return report

    # ------------------------------------------------------------- AA-001
    def _uniform_motion(self, facts: SceneFacts) -> Finding | None:
        starts = facts.motion_starts
        if len(starts) < 3:
            return None
        # Two different failures, same symptom: everything at once, or a
        # mechanical constant-offset staircase.
        if len(set(starts)) == 1:
            return Finding(
                "AA-001", "error",
                "all layers animate at the same instant",
                f"{len(starts)} layers, 1 distinct start ({starts[0]:.0f}ms)",
                "weight start times by layer role and let some overlap",
            )
        deltas = [round(b - a, 1) for a, b in zip(starts, starts[1:])]
        if len(set(deltas)) == 1 and len(deltas) >= 2:
            return Finding(
                "AA-001", "error",
                "layer starts form a constant stagger",
                f"uniform {deltas[0]:.0f}ms between every layer",
                "vary the stagger: dominant layers wait less, supporting layers overlap",
            )
        return None

    # ------------------------------------------------------------- AA-002
    def _identical_motion(self, facts: SceneFacts) -> Finding | None:
        if len(facts.motion_names) >= 3 and len(set(facts.motion_names)) == 1:
            return Finding(
                "AA-002", "warning",
                f"every layer uses the same motion primitive ({facts.motion_names[0]})",
                f"{len(facts.motion_names)} layers, 1 primitive",
                "choose the primitive from each layer's semantic intent",
            )
        return None

    # ------------------------------------------------------------- AA-003
    def _everything_centered(self, facts: SceneFacts) -> Finding | None:
        aligns = [a for a in facts.text_aligns if a]
        if len(aligns) >= 3 and all(a == "center" for a in aligns):
            return Finding(
                "AA-003", "warning",
                "every text layer is centre-aligned",
                f"{len(aligns)} centered layers",
                "switch most scenes to editorial_left/right; reserve center for one message",
            )
        return None

    # ------------------------------------------------------------- AA-004
    def _flat_hierarchy(self, facts: SceneFacts) -> Finding | None:
        sizes = sorted(facts.type_sizes)
        if len(sizes) < 3:
            return None
        largest = sizes[-1]
        # True median, not `sizes[len // 2]`: for an even count that expression
        # silently takes the *upper* middle value, which inflates the baseline
        # and flags well-formed scenes as flat. A critic that cries wolf gets
        # ignored, which is worse than having no critic.
        middle = len(sizes) // 2
        median = sizes[middle] if len(sizes) % 2 else (sizes[middle - 1] + sizes[middle]) / 2
        if median <= 0:
            return None
        ratio = largest / median
        if ratio < self.MIN_HIERARCHY_RATIO:
            return Finding(
                "AA-004", "error",
                "type sizes are too close together to form a hierarchy",
                f"largest/median = {ratio:.2f} (need >= {self.MIN_HIERARCHY_RATIO})",
                "apply a TypographyProfile; promote a sole headline to `display`",
            )
        return None

    # ------------------------------------------------------------- AA-005
    def _too_many_layers(self, facts: SceneFacts) -> Finding | None:
        if facts.text_layer_count > self.MAX_TEXT_LAYERS:
            return Finding(
                "AA-005", "warning",
                f"{facts.text_layer_count} text layers exceeds what a scene can carry",
                f"limit is {self.MAX_TEXT_LAYERS}",
                "split the scene, or move detail into the narration",
            )
        return None

    # ------------------------------------------------------------- AA-006
    def _safe_area(self, facts: SceneFacts) -> Finding | None:
        if facts.safe_area_breaches:
            return Finding(
                "AA-006", "error",
                "content intrudes into the platform's overlay region",
                "; ".join(facts.safe_area_breaches),
                "enable safe areas, or move these layers inside them",
            )
        return None

    # ------------------------------------------------------------- AA-007
    def _accent_everywhere(self, facts: SceneFacts) -> Finding | None:
        if facts.layer_count >= 3 and facts.accent_layer_count >= facts.layer_count:
            return Finding(
                "AA-007", "warning",
                "every layer uses the accent colour",
                f"{facts.accent_layer_count}/{facts.layer_count} accent layers",
                "reserve the accent for one element so it still means something",
            )
        return None

    # ------------------------------------------------------------- AA-008
    def _negative_space(self, facts: SceneFacts) -> Finding | None:
        if facts.coverage > self.MAX_COVERAGE:
            return Finding(
                "AA-008", "info",
                "layers cover most of the frame, leaving no negative space",
                f"coverage {facts.coverage:.0%} of usable area",
                "remove a layer or shrink the boxes",
            )
        return None

    # ------------------------------------------------------------- AA-010
    def _long_lines(self, facts: SceneFacts) -> Finding | None:
        if facts.longest_line > self.MAX_LINE_WIDTH:
            return Finding(
                "AA-010", "info",
                f"body line is {facts.longest_line} half-widths long",
                f"target <= {self.MAX_LINE_WIDTH}",
                "narrow the slot or split the sentence",
            )
        return None

    # ------------------------------------------------------------- AA-011
    def _contrast(self, facts: SceneFacts) -> Finding | None:
        ratio = contrast_ratio(facts.text_color, facts.background_color)
        if ratio is None:
            # Unparseable colours are not the critic's business to guess at.
            return None
        threshold = 3.0 if facts.largest_is_large_text else 4.5
        if ratio < threshold:
            return Finding(
                "AA-011", "error",
                f"text contrast {ratio:.2f}:1 is below {threshold}:1",
                f"{facts.text_color} on {facts.background_color}",
                "change the text or background colour — not the opacity",
            )
        return None

    # ------------------------------------------------------------- AA-012
    def _no_ambient_motion(self, facts: SceneFacts) -> Finding | None:
        if facts.layer_count >= 2 and not facts.background_has_motion:
            return Finding(
                "AA-012", "info",
                "nothing moves continuously; every layer enters and freezes",
                "no parallax or ambient layer",
                "give the background layer a slow parallax",
            )
        return None

    # ------------------------------------------------------------- AA-013
    def _overlapping_layers(self, facts: SceneFacts) -> Finding | None:
        """Two layers placed at the same coordinates print through each other.

        Severity is `error`, not `warning`, because this is the only finding in
        the set that a viewer reads as a broken render rather than a stylistic
        miss: the text is not merely cramped, it is *illegible*, and the frame
        looks like a screenshot of a bug. It reached a shipped build once, via
        the layout engine's leftover sweep reusing a slot — which is exactly the
        kind of thing a rule catches and a reviewer does not.
        """
        positions = facts.slot_positions
        if len(positions) < 2:
            return None
        seen: dict[tuple[float, float], str] = {}
        for key, x, y in positions:
            spot = (round(x, 3), round(y, 3))
            if spot in seen:
                return Finding(
                    "AA-013", "error",
                    f"two layers occupy the same position ({spot[0]}, {spot[1]})",
                    f"'{seen[spot]}' and '{key}' render on top of one another",
                    "give the later layer its own band, or stack it clear of the first",
                )
            seen[spot] = key
        return None


# ------------------------------------------------------------ variation
@dataclass(frozen=True)
class SceneSignature:
    layout: str
    motion_set: tuple[str, ...]
    role_sequence: tuple[str, ...]

    def key(self) -> str:
        return f"{self.layout}|{'/'.join(sorted(self.motion_set))}"


class SceneVariationPolicy:
    """Keep neighbouring scenes from repeating themselves.

    Repetition across scenes is noticed long before repetition inside one: a
    viewer watching scene 4 has already seen scenes 1-3. The policy therefore
    tracks the last N scenes and forces a change when a neighbour would match.

    It only ever *suggests* a different layout — it never rewrites content. A
    variation policy that changes words to satisfy a rule is vandalism.
    """

    def __init__(self, memory: int = 3) -> None:
        self.memory = max(1, memory)
        self._history: list[SceneSignature] = []
        self.adjustments: list[str] = []

    def next_layout(
        self, proposed: str, available: Iterable[str]
    ) -> tuple[str, Finding | None]:
        options = list(available)
        if not options or proposed not in options:
            return proposed, None

        recent = {sig.layout for sig in self._history[-self.memory :]}
        if proposed not in recent:
            return proposed, None

        unused = [name for name in options if name not in recent]
        if not unused:
            # Everything has been used recently; repetition is unavoidable and
            # pretending otherwise would just shuffle without meaning.
            return proposed, None

        alternative = self._pick_last_used(unused)
        return alternative, Finding(
            "AA-009", "warning",
            f"scene repeats layout '{proposed}' used within the last {self.memory} scenes",
            f"neighbours used: {', '.join(sorted(recent))}",
            f"switched layout to '{alternative}'",
        )

    def _pick_last_used(self, options: list[str]) -> str:
        used_at = {}
        for position, sig in enumerate(self._history):
            if sig.layout in options and sig.layout not in used_at:
                used_at[sig.layout] = position
        # Prefer the option unused longest — position ascending = older.
        ranked = sorted(options, key=lambda name: used_at.get(name, -1))
        return ranked[0]

    def record(self, signature: SceneSignature) -> None:
        self._history.append(signature)
