"""LayoutEngine — five primitives instead of twenty templates.

A template library grows until nobody can find anything; five well-chosen
primitives compose into everything those twenty templates did. The trade-off is
that composition has to be decided by something, so the engine reads intent from
the scene's declared strategy and its layer roles.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

LayoutName = Literal[
    "center", "split", "editorial_left", "editorial_right", "full_bleed",
    "overlay", "stat", "quote", "diagram",
]

#: Which primitive to prefer for each declared visual strategy. A declaration
#: is a hint, not a command: if the layers cannot support it we fall back.
STRATEGY_PREFERENCE: dict[str, list[LayoutName]] = {
    "typography_led": ["editorial_left", "center", "quote"],
    "diagram_led": ["diagram", "split", "full_bleed"],
    "image_led": ["full_bleed", "overlay", "center"],
    "data_led": ["stat", "split", "diagram"],
    "screen_led": ["full_bleed", "split", "overlay"],
    "avatar_led": ["overlay", "split", "editorial_right"],
    "broll": ["full_bleed", "overlay"],
    "chart": ["stat", "diagram", "split"],
}


@dataclass
class Slot:
    """One placed region, in fractions of the *usable* area."""

    x: float
    y: float
    w: float
    h: float
    align: str = "flex-start"
    justify: str = "flex-start"
    text_align: str = "left"
    z: int = 1
    notes: list[str] = field(default_factory=list)

    def css(self) -> str:
        return (
            f"position:absolute;left:{self.x * 100:.3f}%;top:{self.y * 100:.3f}%;"
            f"width:{self.w * 100:.3f}%;min-height:{self.h * 100:.3f}%;"
            f"display:flex;flex-direction:column;"
            f"align-items:{self.align};justify-content:{self.justify};"
            f"text-align:{self.text_align};z-index:{self.z}"
        )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


#: How far one surplus layer is pushed below the previous occupant of its slot,
#: as a fraction of that slot's own band height. A third rather than a full slot
#: because two supporting paragraphs stacked under a margin-heavy layout should
#: stay inside the frame; the cost of being slightly tight is a little less air,
#: while the cost of a full hop is text running off the bottom edge.
_STACK_STEP = 0.34


def _stacked(slot: Slot, depth: int) -> Slot:
    """A copy of `slot` moved down so layer `depth` cannot print over its peers.

    `depth` counts earlier occupants of the same slot (0 = the first, returned
    untouched). The vertical offset is expressed in the same fraction-of-usable-
    area units as `Slot.y`, so it survives every aspect ratio unchanged.

    The offset saturates rather than accumulating without bound — but a saturating
    clamp alone would *reintroduce* the bug it exists to prevent, because two deep
    layers would both land on the ceiling and collide again. So the step is
    derived from the depth: it shrinks as the stack grows, giving every occupant a
    distinct y while the total stays under `_MAX_STACK_SHIFT` for any depth.
    """
    if depth <= 0:
        return slot
    # Harmonic-ish decay: sum of step/k for k in 1..depth stays logarithmic, so
    # distinct offsets never exceed the cap no matter how many layers pile up.
    shift = 0.0
    for step in range(1, depth + 1):
        shift += _MAX_STACK_SHIFT / (step + 1)
    shift = min(shift, _MAX_STACK_SHIFT * depth / (depth + 1))
    return replace(slot, y=_clamp01(slot.y + shift),
                   notes=[*slot.notes, f"stacked below {depth} earlier layer(s)"])


#: Ceiling on the stacked offset so a long tail cannot march off the frame. The
#: safe area keeps ~7% at the bottom; staying under this is what keeps the last
#: stacked layer inside it.
_MAX_STACK_SHIFT = 0.16


#: Where decoration lands when the IR did not say. Bottom-left, under the text,
#: which is where a divider belongs in every layout the engine offers.
_DEFAULT_DECOR = (0.075, 0.80, 0.22, 0.01)


def _declared_slot(layer: dict[str, Any]) -> Slot:
    """A Slot built from the layer's *own* declared geometry.

    Decoration carries its intent in `layer["layout"]` — a divider is written as
    `{w: 0.22, h: 0.01}` precisely so it stays a line. Reading that back is the
    whole point: assigning decoration to a content band discards the one piece of
    information that says how big it should be.
    """
    declared = layer.get("layout") or {}
    if not isinstance(declared, dict):
        declared = {}
    x, y, w, h = _DEFAULT_DECOR
    try:
        x = _clamp01(declared.get("x", x))
        y = _clamp01(declared.get("y", y))
        w = _clamp01(declared.get("w", w)) or w
        h = _clamp01(declared.get("h", h)) or h
    except (TypeError, ValueError):
        x, y, w, h = _DEFAULT_DECOR
    return Slot(x, y, w, h, z=1, notes=["decoration keeps its declared geometry"])


@dataclass
class LayoutResult:
    name: LayoutName
    slots: dict[str, Slot]
    reason: list[str] = field(default_factory=list)

    def css_for(self, key: str) -> str:
        slot = self.slots[key]
        return slot.css()


# --------------------------------------------------------------- primitives
def _center(count: int) -> dict[str, Slot]:
    """One thing, exactly centred. Only legitimate when there is one thing.

    Centring a group is the single strongest "this was made by a tool" signal,
    which is why this primitive is deliberately narrow: it accepts a single slot
    and stacks extras beneath rather than distributing them.
    """
    height = 0.34 if count == 1 else 0.22
    top = (1.0 - height * count) / 2 if count > 1 else (1.0 - height) / 2
    slots = {
        "primary": Slot(0.10, max(0.0, top), 0.80, height,
                        align="center", justify="center", text_align="center", z=2)
    }
    if count > 1:
        slots["secondary"] = Slot(
            0.16, max(0.0, top + height), 0.68, 0.16,
            align="center", justify="center", text_align="center", z=2,
            notes=["stacked beneath the centred primary; not distributed"],
        )
    return slots


def _split(count: int) -> dict[str, Slot]:
    """Two columns at an uneven ratio. Never 50/50.

    A 50/50 split is the visual equivalent of a coin flip: no hierarchy, no
    direction, no point of entry. 58/42 establishes which side leads while still
    reading as two columns.
    """
    return {
        "primary": Slot(0.06, 0.16, 0.52, 0.62, z=2),
        "secondary": Slot(0.62, 0.24, 0.32, 0.52, z=2,
                          notes=["deliberately offset vertically from primary"]),
        # A full-width band, available when a third thing exists.
        "footer": Slot(0.06, 0.82, 0.88, 0.12, z=2),
    }


def _editorial_left(count: int) -> dict[str, Slot]:
    """Left-weighted column with a strong left margin — the default for prose."""
    return {
        "primary": Slot(0.08, 0.24, 0.62, 0.40, z=2),
        "secondary": Slot(0.08, 0.64, 0.52, 0.22, z=2),
        # The right-hand bleed zone: empty most of the time, and that emptiness
        # is what stops the frame looking like a filled form.
        "aside": Slot(0.72, 0.30, 0.20, 0.40, z=1,
                      notes=["intentionally sparse negative space"]),
    }


def _editorial_right(count: int) -> dict[str, Slot]:
    return {
        "primary": Slot(0.30, 0.24, 0.62, 0.40, z=2, text_align="right",
                        align="flex-end"),
        "secondary": Slot(0.40, 0.64, 0.52, 0.22, z=2, text_align="right",
                          align="flex-end"),
        "aside": Slot(0.08, 0.30, 0.20, 0.40, z=1),
    }


def _full_bleed(count: int) -> dict[str, Slot]:
    """Media fills the frame; text sits on a scrim, not floating on the image."""
    return {
        "media": Slot(0.0, 0.0, 1.0, 1.0, z=0),
        "scrim": Slot(0.0, 0.55, 1.0, 0.45, z=1,
                      notes=["gradient scrim keeps captions legible over any image"]),
        "primary": Slot(0.07, 0.66, 0.70, 0.22, z=2, justify="flex-end"),
        "secondary": Slot(0.07, 0.86, 0.62, 0.10, z=2, justify="flex-end"),
    }


def _overlay(count: int) -> dict[str, Slot]:
    """Text over media, with the text occupying a lower band."""
    return {
        "media": Slot(0.0, 0.0, 1.0, 1.0, z=0),
        "primary": Slot(0.08, 0.12, 0.60, 0.30, z=2),
        "secondary": Slot(0.08, 0.72, 0.56, 0.18, z=2, justify="flex-end"),
    }


def _stat(count: int) -> dict[str, Slot]:
    """A number that dominates, with the interpretation beneath it.

    The bands run metric 22%..48%, primary 52%..71%, secondary 75%..91%. They are
    packed deliberately tighter than they look: a slot is a *minimum* height and
    its content is free to grow past it, so generous bands plus a display-size
    headline is how a two-layer scene ends up with the headline's box reaching up
    into the metric. Leaving a real gutter between bands costs nothing on a quiet
    scene and is the difference between readable and overlapped on a loud one.
    """
    return {
        "metric": Slot(0.08, 0.22, 0.55, 0.26, z=2, justify="center"),
        "primary": Slot(0.08, 0.52, 0.60, 0.19, z=2),
        "secondary": Slot(0.08, 0.75, 0.52, 0.16, z=2),
        # A right-hand context column: sources, qualifiers, unit.
        "aside": Slot(0.68, 0.30, 0.24, 0.40, z=1),
    }


def _quote(count: int) -> dict[str, Slot]:
    """Asymmetric quotation: pulled left, with attribution away to the right."""
    return {
        "primary": Slot(0.10, 0.26, 0.72, 0.38, z=2, justify="center"),
        "secondary": Slot(0.10, 0.70, 0.44, 0.14, z=2,
                          notes=["attribution offset so it never centres under the quote"]),
    }


def _diagram(count: int) -> dict[str, Slot]:
    """Figure-dominant with a narrow caption column."""
    return {
        "figure": Slot(0.06, 0.12, 0.62, 0.70, z=1, justify="center"),
        "primary": Slot(0.70, 0.20, 0.24, 0.30, z=2),
        "secondary": Slot(0.70, 0.54, 0.24, 0.28, z=2),
    }


BUILDERS: dict[LayoutName, Any] = {
    "center": _center,
    "split": _split,
    "editorial_left": _editorial_left,
    "editorial_right": _editorial_right,
    "full_bleed": _full_bleed,
    "overlay": _overlay,
    "stat": _stat,
    "quote": _quote,
    "diagram": _diagram,
}

LAYOUT_IDS: list[LayoutName] = list(BUILDERS)


def supported_layouts() -> list[str]:
    return list(BUILDERS)


# ------------------------------------------------------------------- engine
class LayoutEngine:
    """Choose one primitive and instantiate slots for this scene's layers."""

    def choose(
        self,
        scene: dict[str, Any],
        *,
        explicit: str | None = None,
        lock: bool = False,
    ) -> LayoutResult:
        """Pick a layout.

        ``lock=True`` means a human explicitly asked for this layout and we obey
        without second-guessing — including when it is a bad idea. A suggestion
        coming from our own variation policy is **not** a lock: an alternative
        chosen to avoid repetition must still survive the same content checks,
        or variation would happily trade a repetition problem for a hierarchy
        one (selecting ``center`` for six layers).
        """
        strategy = (scene.get("visual_strategy") or "typography_led").lower()
        layers = scene.get("layers") or []
        count = len(layers)
        reasons: list[str] = []

        chosen: LayoutName
        if explicit and explicit in BUILDERS:
            chosen = explicit
            reasons.append(f"layout requested: {explicit}")
            if not lock:
                refined = self._refine(chosen, scene, layers, reasons)
                if refined != chosen:
                    chosen = refined
        else:
            candidates = STRATEGY_PREFERENCE.get(strategy, STRATEGY_PREFERENCE["typography_led"])
            chosen = candidates[0]
            reasons.append(f"visual_strategy {strategy} → {chosen}")
            chosen = self._refine(chosen, scene, layers, reasons)

        slots = BUILDERS[chosen](count)
        return LayoutResult(name=chosen, slots=slots, reason=reasons)

    def _refine(
        self,
        chosen: LayoutName,
        scene: dict[str, Any],
        layers: list[dict[str, Any]],
        reasons: list[str],
    ) -> LayoutName:
        """Correct the strategy hint against what the layers actually contain.

        A declared strategy is a claim about intent, and intent is frequently
        wrong or stale. If a scene declares ``typography_led`` but every layer is
        an image, honouring the declaration would place text slots where no text
        exists and leave the images unplaced.
        """
        kinds = {(str(layer.get("type") or "text")).lower() for layer in layers}
        visuals = kinds & {"image", "video", "svg", "chart"}
        has_text = "text" in kinds or not kinds
        numbers = [
            layer for layer in layers
            if (layer.get("role") or "").lower() == "metric"
        ]

        if chosen.startswith("editorial") and visuals and not has_text:
            reasons.append("all layers are visual but strategy is editorial → full_bleed")
            return "full_bleed"
        if chosen == "diagram" and not visuals and not (scene.get("shots") or []):
            reasons.append("diagram requested without any figure layer → editorial_left")
            return "editorial_left"
        if numbers and chosen not in {"stat"}:
            reasons.append("metric layer present → stat")
            return "stat"
        if chosen == "center" and len(layers) > 2:
            # Centring more than two things distributes attention to nothing.
            reasons.append("more than 2 layers: centre would distribute focus → editorial_left")
            return "editorial_left"
        return chosen

    def assign(
        self,
        result: LayoutResult,
        layers: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], Slot, str]]:
        """Bind each layer to a slot.

        Three sweeps, because one pass is wrong whenever a dedicated slot exists.
        `metric` sits at the *front* of the reading order, so consuming the order
        positionally handed slot 0 (`metric`, y=22%..48%) to whatever layer came
        first and displaced the real metric into `primary`. With a headline first,
        that put a display-size headline into `primary` (a 19%-tall band) while a
        metric slot sat above it — the headline overflowed upward out of its band
        and collided with the layer above. Two layers in one place is the single
        most visible rendering defect there is.

        1. media — the picture is decided by *what it is*, never by its index.
           A layout's text slots sit above `media` in the reading order, so a
           positional sweep would hand the image slot to a label.
        2. text roles, claimed in importance order (a headline outranks a label
           even when the label is authored first) and matched to the slot the
           layout sized for that role.
        3. leftovers, filled in reading order. Nothing is ever dropped.
        """
        order = self._slot_order(result)
        taken: set[str] = set()
        placed: list[tuple[dict[str, Any], Slot | None, str]] = [
            (layer, None, "") for layer in layers
        ]

        # Sweep 1 — media. A scene has at most one thing that *is* the picture,
        # and the picture must not be chosen by layer index (see above).
        #
        # Decoration is settled first, before any slot is claimed, because a
        # decorative layer has no business occupying a content band. A hairline
        # accent rule that gets handed `secondary` stops being a hairline: it
        # inherits the band's width and, because `Slot.css` sets `min-height`
        # while the shape sets `height`, the browser paints a full-size accent
        # *block* where the design called for a 3px line. That is how a shipped
        # `glass-aurora` render grew a teal square on the right of every scene.
        # Such layers carry their own geometry in the IR, so they get it.
        decorative = [
            position for position, layer in enumerate(layers)
            if self._is_decoration(layer)
        ]
        for position in decorative:
            placed[position] = (layers[position], _declared_slot(layers[position]),
                                f"decor:{position}")

        for position, layer in enumerate(layers):
            if self._is_decoration(layer):
                continue
            key = self._dedicated_key(layer, media_pass=True, result=result, taken=taken)
            if key is not None:
                taken.add(key)
                placed[position] = (layer, result.slots[key], key)
        del position

        # Sweep 2 — text roles, in *importance* order rather than list order.
        # Running this over the list as written let a `label` declared above a
        # `headline` claim `primary`, and the headline then fell into
        # `secondary` — a 16%-tall slot holding display type. Authoring order is
        # not a statement about which layer leads.
        for position in sorted(range(len(layers)),
                               key=lambda i: self._text_rank(layers[i])):
            if placed[position][1] is not None:
                continue
            key = self._dedicated_key(layers[position], media_pass=False,
                                      result=result, taken=taken)
            if key is not None:
                taken.add(key)
                placed[position] = (layers[position], result.slots[key], key)
        del position

        # Sweep 3 — whatever is left fills the remaining slots in reading order.
        #
        # Once the leftovers run out the surplus layers must go *somewhere*, and
        # the obvious `min(cursor, len - 1)` — "share the last slot" — is the
        # worst possible answer: two layers handed byte-identical CSS land on the
        # same coordinates and print through each other. That is not a subtle
        # degradation, it is the single defect a viewer notices immediately, and
        # it shipped: a `_diagram` scene with four text layers rendered its last
        # two on top of one another.
        #
        # So the surplus is *stacked* instead of overlaid. Every extra layer
        # inherits the last slot but is pushed clear of everything already in it,
        # using that slot's own minimum height as the step. Nothing vanishes,
        # nothing collides, and the block simply grows downward past its band —
        # which `Slot` already permits ("a slot is a *minimum* height and may be
        # outgrown"). Layouts whose last band is near the bottom of the frame are
        # the reason the step is a fraction of the slot rather than all of it: a
        # tight stack of supporting text still stays inside the safe area far
        # more often than a full-slot hop would.
        remaining = [key for key in order if key not in taken]
        cursor = 0
        # Every slot key that has been spoken for, whether by an earlier sweep or
        # by this one. Seeded from the layers already placed so a leftover that
        # lands in an occupied slot knows it is the second occupant, not the
        # first — deriving the count from `taken` alone misses exactly that case.
        occupancy: dict[str, int] = {}
        for _, _, key in placed:
            if key:
                occupancy[key] = occupancy.get(key, 0) + 1
        for index, (layer, slot, key) in enumerate(placed):
            if slot is not None:
                continue
            if remaining:
                chosen = remaining.pop(0)
            else:
                # No slot left at all: share the last one, stacked, like the rest.
                chosen = order[-1] if order else "primary"
            occupancy[chosen] = occupancy.get(chosen, 0)
            placed[index] = (layer, _stacked(result.slots[chosen], occupancy[chosen]), chosen)
            occupancy[chosen] += 1
        return placed

    #: Lower number = claims a display slot sooner. A headline outranks a label
    #: even when the label is written first.
    TEXT_RANK: dict[str, int] = {
        "headline": 0, "display": 0, "label": 1, "metric": 1, "quote": 2,
        "subhead": 2, "body": 3, "caption": 4,
    }

    @classmethod
    def _text_rank(cls, layer: dict[str, Any]) -> int:
        role = (str(layer.get("role") or "")).lower()
        return cls.TEXT_RANK.get(role, 5)

    @staticmethod
    def _is_decoration(layer: dict[str, Any]) -> bool:
        """Whether this layer is furniture rather than content.

        Decoration is drawn from its own declared box, not from a content band:
        a divider rule, an accent block, a background wash. Letting these compete
        for slots both starves the real content and distorts the decoration —
        the browser resolves the conflict between the slot's `min-height` and the
        shape's `height` in favour of whichever came later, which is how a 3px
        line becomes a full-width accent rectangle.

        A *picture* is never decoration, however it is labelled: an image marked
        `role: background` is a full-bleed hero, and it belongs in the media slot
        where `object-fit: cover` can size it. The check is on what the layer
        draws, not on the role string alone.
        """
        kind = str(layer.get("type") or "text").lower()
        role = str(layer.get("role") or "").lower()
        if kind in {"image", "video"}:
            return False
        if role == "background":
            return True
        if kind == "shape":
            # `ring` and the default bordered box are compositional marks that may
            # legitimately frame a region, so only the flat fills are furniture.
            return str(layer.get("kind") or "rule").lower() in {"rule", "block"}
        return False

    @classmethod
    def _dedicated_key(
        cls,
        layer: dict[str, Any],
        *,
        media_pass: bool,
        result: LayoutResult,
        taken: set[str],
    ) -> str | None:
        """The slot this layer owns by right, or None if it takes a leftover.

        Only slots a *layout* provides for a specific role are claimed here.
        `_pick_key`'s `index == 0 → primary` shortcut is deliberately absent: it
        is what let a headline jump the queue ahead of a metric.
        """
        del cls
        kind = (str(layer.get("type") or "text")).lower()
        role = (str(layer.get("role") or "")).lower()

        if media_pass:
            if kind in {"image", "video"} and "media" in result.slots:
                return "media" if "media" not in taken else None
            if kind in {"svg", "chart"} and "figure" in result.slots:
                return "figure" if "figure" not in taken else None
            return None

        if role == "metric" and "metric" in result.slots and "metric" not in taken:
            return "metric"
        # The display layer and its read plate. `primary` is the slot the layout
        # sized for display type; `scrim` is the equivalent over full-bleed media.
        # A headline that has to settle for `secondary` — a 10-16%-tall sub-band —
        # grows straight out of its band and into whatever is above it.
        if role in {"headline", "display", "label"}:
            for candidate in ("primary", "scrim"):
                if candidate in result.slots and candidate not in taken:
                    return candidate
        return None

    @staticmethod
    def _slot_order(result: LayoutResult) -> list[str]:
        """Slots in the order content should fill them."""
        preference = [
            "figure", "media", "metric", "primary", "secondary", "aside", "footer",
        ]
        available = set(result.slots)
        return [name for name in preference if name in available]

    @staticmethod
    def _pick_key(
        layer: dict[str, Any], index: int, order: list[str], result: LayoutResult
    ) -> str:
        kind = (str(layer.get("type") or "text")).lower()
        role = (str(layer.get("role") or "")).lower()
        if kind in {"image", "video"} and "media" in result.slots:
            return "media"
        if kind in {"image", "video", "svg", "chart"} and "figure" in result.slots:
            return "figure"
        if role == "metric" and "metric" in result.slots:
            return "metric"
        if index == 0 and "primary" in result.slots:
            return "primary"
        fallback = order[min(index, len(order) - 1)] if order else "primary"
        return fallback
