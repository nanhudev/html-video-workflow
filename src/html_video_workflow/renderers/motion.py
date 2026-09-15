"""MotionEngine — nine primitives with real per-layer timing.

The defining symptom of generated video is that every element arrives together:
one fade on the container, or five identical `delay += 100ms` steps. The viewer
reads that as "a template fired", and no amount of palette work fixes it.

So timing here is *computed*, not declared, and it is computed from what each
layer is for. Nothing animates because "it's an element"; it animates because it
is revealing information, counting a quantity, or connecting two ideas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MotionName = Literal[
    "fade", "slide", "scale", "reveal", "count", "trace", "wipe", "mask", "parallax",
]

#: Semantic intent → the primitive that expresses it. A request for a semantic
#: is a request for meaning, so several primitives can serve one intent and the
#: choice depends on what the layer actually contains.
SEMANTIC_PREFERENCES: dict[str, list[MotionName]] = {
    "reveal": ["reveal", "mask", "wipe"],
    "count": ["count", "trace"],
    "trace": ["trace", "wipe"],
    "connect": ["wipe", "trace"],
    "split": ["slide", "mask"],
    "depth": ["parallax", "scale"],
    "progression": ["wipe", "count"],
    "focus": ["scale", "fade"],
    # No dedicated engine for `drift` exists yet: a slow fade is the honest
    # downgrade rather than an alias to something with different intent.
    "drift": ["fade", "parallax"],
}

#: Easings that read as physical rather than linear-interpolated.
EASINGS: dict[str, str] = {
    "decelerate": "cubic-bezier(.16,1,.3,1)",
    "standard": "cubic-bezier(.4,0,.2,1)",
    "anticipate": "cubic-bezier(.34,1.56,.64,1)",
    "linearish": "cubic-bezier(.33,.1,.28,1)",
}

#: Base durations per primitive, before the per-layer weighting below.
BASE_DURATION_MS: dict[MotionName, int] = {
    "fade": 520,
    "slide": 620,
    "scale": 560,
    "reveal": 700,
    "count": 900,
    "trace": 1100,
    "wipe": 640,
    "mask": 720,
    "parallax": 1400,
}


@dataclass
class MotionInstance:
    """A fully resolved animation: primitive, timing and generated CSS."""

    name: MotionName
    css: str
    start_ms: float
    end_ms: float
    keyframes: str
    reason: list[str] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        return self.end_ms - self.start_ms


@dataclass
class TimingPlan:
    """Every layer's window, and the total they occupy."""

    instances: list[MotionInstance]

    @property
    def total_ms(self) -> float:
        return max((i.end_ms for i in self.instances), default=0.0)

    def window_for(self, index: int) -> tuple[float, float]:
        if index < len(self.instances):
            inst = self.instances[index]
            return inst.start_ms, inst.end_ms
        return 0.0, 0.0


# ------------------------------------------------------------- keyframe CSS
def _keyframes(motion: MotionName, uid: int) -> tuple[str, str]:
    """Return (keyframe-name, @keyframes block).

    Generated per instance rather than shared, because two layers may animate
    different distances and a shared name would force them to share geometry.
    """
    name = f"hvw{motion.capitalize()}{uid}"
    b = BASE_DURATION_MS[motion]
    if motion == "fade":
        block = f"@keyframes {name}{{from{{opacity:0}}to{{opacity:1}}}}"
    elif motion == "slide":
        block = (
            f"@keyframes {name}{{from{{opacity:0;transform:translate3d(var(--dx,-28px),var(--dy,0),0)}}"
            f"to{{opacity:1;transform:none}}}}"
        )
    elif motion == "scale":
        block = (
            f"@keyframes {name}{{from{{opacity:0;transform:scale(var(--from,0.94))}}"
            f"to{{opacity:1;transform:none}}}}"
        )
    elif motion == "reveal":
        # A true reveal: the glyphs are clipped, not merely faded upward.
        block = (
            f"@keyframes {name}{{from{{clip-path:inset(0 0 100% 0);opacity:.001}}"
            f"to{{clip-path:inset(0 0 -10% 0);opacity:1}}}}"
        )
    elif motion == "count":
        # The number itself is static; the frame around it commits. Counting is
        # performed by ``count.js`` when the target is numeric — see ``build()``.
        block = (
            f"@keyframes {name}{{from{{opacity:0;transform:translateY(10px) scale(.96)}}"
            f"to{{opacity:1;transform:none}}}}"
        )
    elif motion == "trace":
        # Stroke drawing via dash offset. Requires ``--len`` on the element.
        block = (
            f"@keyframes {name}{{from{{stroke-dashoffset:var(--len,1200)}}"
            f"to{{stroke-dashoffset:0}}}}"
        )
    elif motion == "wipe":
        block = (
            f"@keyframes {name}{{from{{clip-path:inset(0 var(--wipeDir,100%) 0 0)}}"
            f"to{{clip-path:inset(0 0 0 0)}}}}"
        )
    elif motion == "mask":
        # Mask band sweeping across — distinct from reveal because the element
        # stays whole and a sheet moves off it.
        block = (
            f"@keyframes {name}{{from{{-webkit-mask-position:var(--maskFrom,-120%) 0;"
            f"mask-position:var(--maskFrom,-120%) 0}}"
            f"to{{-webkit-mask-position:0% 0;mask-position:0% 0}}}}"
        )
    else:  # parallax
        block = (
            f"@keyframes {name}{{from{{transform:translate3d(0,var(--py,26px),0)}}"
            f"to{{transform:translate3d(0,0,0)}}}}"
        )
    del b
    return name, block


# ------------------------------------------------------------------ engine
class MotionEngine:
    """Decide a primitive per layer and give each one its own real timing."""

    #: Fraction of the scene duration we are willing to spend on entrances.
    ENTRANCE_BUDGET = 0.55

    def build(
        self,
        layers: list[dict[str, Any]],
        *,
        scene_duration_ms: float,
        fps: int = 30,
        seed: int = 0,
    ) -> TimingPlan:
        if not layers:
            return TimingPlan(instances=[])

        budget = max(600.0, scene_duration_ms * self.ENTRANCE_BUDGET)
        instances: list[MotionInstance] = []
        cursor = 0.0
        # Weights are role-driven, so a headline leads and its evidence follows
        # rather than every layer sharing an identical 100ms stagger.
        weights = [self._importance(layer, index) for index, layer in enumerate(layers)]
        total_weight = sum(weights) or 1.0

        for index, layer in enumerate(layers):
            motion, reason = self._choose(layer, index, seed)
            base = BASE_DURATION_MS[motion]
            # Larger, more dominant elements take longer — they have farther to
            # travel optically. Clamped so nothing becomes sluggish.
            duration = min(int(base * (0.85 + 0.35 * weights[index])), int(budget * 0.6))
            duration = max(220, duration)

            share = weights[index] / total_weight
            # Stagger proportional to weight, quantised to whole frames so the
            # result is reproducible and lands on a frame boundary.
            stagger = (budget - duration) * share * 0.6
            start = cursor + stagger
            frame = 1000.0 / max(1, fps)
            start = round(start / frame) * frame

            name, keyframes = _keyframes(motion, index)
            easing = self._easing_for(motion, layer)
            css = self._css_for(motion, name, duration, start, easing, layer, index)
            instances.append(
                MotionInstance(
                    name=motion,
                    css=css,
                    start_ms=start,
                    end_ms=start + duration,
                    keyframes=keyframes,
                    reason=reason,
                )
            )
            # Only advance the cursor enough that a dominant layer delays its
            # follower, keeping related lines from being simultaneous.
            cursor += stagger * 0.55

        return TimingPlan(instances=instances)

    # -------------------------------------------------------------- choices
    def _choose(
        self, layer: dict[str, Any], index: int, seed: int
    ) -> tuple[MotionName, list[str]]:
        motion_spec = layer.get("motion") or {}
        semantic = str(motion_spec.get("semantic") or "reveal").lower()
        explicit = str(motion_spec.get("enter") or "").lower()
        reasons: list[str] = []

        # An explicitly requested primitive is honoured when we know it. An
        # unknown name is ignored rather than mapped to something misleading.
        if explicit in BASE_DURATION_MS:
            reasons.append(f"explicit enter={explicit}")
            return explicit, reasons

        candidates = SEMANTIC_PREFERENCES.get(semantic, SEMANTIC_PREFERENCES["reveal"])
        chosen = candidates[0]
        reasons.append(f"semantic {semantic} → {chosen}")

        # Seed must include the layer index. Deriving variation from a constant
        # hands every layer the same "alternative", so scene-wide variation
        # collapses into the uniform motion the policy exists to prevent.
        if seed and len(candidates) > 1:
            alt = candidates[(seed + index * 7) % len(candidates)]
            if alt != chosen:
                reasons.append(f"variation pick → {alt}")
                chosen = alt

        # Content checks run *after* variation, because an alternative may be
        # invalid for this layer's content even though the primary was fine.
        chosen, reasons = self._apply_content_rules(chosen, layer, reasons)
        return chosen, reasons

    def _apply_content_rules(
        self, chosen: MotionName, layer: dict[str, Any], reasons: list[str]
    ) -> tuple[MotionName, list[str]]:
        kind = str(layer.get("type") or "text").lower()
        role = str(layer.get("role") or "").lower()

        # trace is only meaningful on vector content.
        if chosen == "trace" and kind not in {"svg", "shape", "chart"}:
            fallback = "wipe" if kind != "text" else "reveal"
            reasons.append(f"trace needs vector content → {fallback}")
            chosen = fallback
        elif chosen == "count" and role != "metric" and not self._looks_numeric(layer):
            reasons.append("count without a numeric target → reveal")
            chosen = "reveal"
        elif chosen == "parallax" and kind not in {"image", "video", "shape"}:
            reasons.append("parallax needs image content → scale")
            chosen = "scale"
        # A second pass, because one substitution can invalidate the next.
        if chosen == "trace" and kind not in {"svg", "shape", "chart"}:
            reasons.append("trace still not applicable → reveal")
            chosen = "reveal"
        return chosen, reasons

    @staticmethod
    def _looks_numeric(layer: dict[str, Any]) -> bool:
        import re

        text = str(layer.get("content") or "")
        return bool(re.search(r"\d", text))

    @staticmethod
    def _importance(layer: dict[str, Any], index: int) -> float:
        """How much of the scene's attention this layer deserves."""
        role = str(layer.get("role") or "").lower()
        base = {
            "headline": 1.0, "metric": 0.95, "foreground": 0.9, "subhead": 0.75,
            "body": 0.6, "evidence": 0.55, "caption": 0.45, "annotation": 0.4,
            "label": 0.35, "background": 0.2, "logo": 0.2,
        }.get(role, 0.5)
        # Earlier layers lead, but weakly — otherwise order alone dictates timing.
        order_bonus = max(0.0, 0.25 - 0.06 * index)
        return round(base + order_bonus, 3)

    @staticmethod
    def _easing_for(motion: MotionName, layer: dict[str, Any]) -> str:
        declared = (layer.get("motion") or {}).get("easing")
        if declared and str(declared).count(",") == 3:
            return f"cubic-bezier({declared})"
        if motion in {"trace", "progression"}:
            return EASINGS["linearish"]
        if motion in {"count", "reveal", "wipe", "mask"}:
            return EASINGS["decelerate"]
        if motion == "parallax":
            return EASINGS["standard"]
        return EASINGS["decelerate"]

    @staticmethod
    def _css_for(
        motion: MotionName,
        name: str,
        duration: int,
        start: float,
        easing: str,
        layer: dict[str, Any],
        index: int,
    ) -> str:
        parts = [f"animation:{name} {duration}ms {easing} {start:.0f}ms both"]
        style = layer.get("style") or {}
        if motion == "slide":
            dx = style.get("dx", "-28px")
            dy = style.get("dy", "0px")
            parts.append(f"--dx:{dx};--dy:{dy}")
        elif motion == "scale":
            parts.append(f"--from:{style.get('scale_from', 0.94)}")
        elif motion == "trace":
            parts.append(f"--len:{style.get('trace_len', 1200)}")
            # Traced strokes must be dashed from the very first rendered frame,
            # or the viewer sees the finished line before it draws.
            parts.append(
                f"stroke-dasharray:var(--len,{style.get('trace_len', 1200)});"
                f"stroke-dashoffset:var(--len,{style.get('trace_len', 1200)})"
            )
        elif motion == "wipe":
            parts.append(f"--wipeDir:{style.get('wipe_dir', '100%')}")
        elif motion == "mask":
            parts.append(
                f"-webkit-mask-image:linear-gradient(90deg,#000 0 45%,transparent 70%);"
                f"mask-image:linear-gradient(90deg,#000 0 45%,transparent 70%);"
                f"-webkit-mask-size:220% 100%;mask-size:220% 100%;"
                f"-webkit-mask-repeat:no-repeat;mask-repeat:no-repeat;"
                f"--maskFrom:-120%"
            )
        elif motion == "parallax":
            parts.append(f"--py:{style.get('parallax_y', 26)}px")
        del index
        return ";".join(parts)


def supported_motions() -> list[str]:
    return sorted(BASE_DURATION_MS)
