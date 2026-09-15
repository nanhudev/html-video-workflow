"""Rule-based prosody planning.

**The problem this solves is the "AI dubbing" feel.** A TTS engine reading a
paragraph as one flat utterance produces uniform pacing, no breathing room and
no emphasis — technically intelligible, obviously synthetic. Real narration has
rhythm: a beat before a turn in the argument, a shorter pause at a comma, a
longer one at a full stop, and a little extra weight on the word that carries
the sentence.

This module turns one narration string into a ``ProsodyPlan`` of segments, each
with its own pause, pace and emphasis. It is **rule-based on purpose**: a plan
that depends on an LLM cannot run in CI, cannot be unit-tested, and changes
behaviour when the model behind it changes. Rules are boring, deterministic and
debuggable — which is exactly what a baseline should be.

An LLM planner can layer on later. It would produce a ``ProsodyPlan`` too; this
one stays the fallback and the reference.

Every segment carries a ``rationale`` so a surprising pause can be traced to the
rule that produced it instead of being guessed at.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..providers.tts.contract import ProsodyPlan, ProsodySegment
from ..utils.logging import get_logger

log = get_logger("pipeline.prosody")

#: Punctuation that ends a thought, with the pause it earns (milliseconds).
#: CJK and Latin are listed separately because the same mark does not carry the
#: same weight in both — a Chinese 。 is a firmer stop than an English period is
#: in casual prose, and a 、 is lighter than a comma.
TERMINAL_MARKS: dict[str, int] = {
    "。": 420, "！": 400, "？": 430, "；": 300, "…": 340,
    ".": 380, "!": 380, "?": 400, ";": 280, "…": 340,
}
SOFT_MARKS: dict[str, int] = {
    "，": 170, "、": 110, "：": 220, "—": 200,
    ",": 150, ":": 200, "-": 140,
}
CLOSERS = "”’\"')）]】」』》"

#: Characters whose presence after a separator suggests it is not a real break —
#: decimals ("3.5"), abbreviations ("e.g."), and numbered lists ("1.").
_DECIMAL = re.compile(r"\d$")

#: Latin abbreviations whose trailing period is interior, not terminal. Checked
#: on the text immediately before the dot, so "e.g." and "etc." stay intact.
_ABBREVIATIONS = (
    "e.g", "i.e", "etc", "vs", "cf", "al", "approx", "no", "fig", "sec",
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st",
)

#: Emphasis candidates: words that carry the argument forward. Deliberately
#: small and multilingual rather than a big list nobody maintains.
EMPHASIS_CUES = (
    "真正", "关键", "核心", "本质", "根本", "重要", "唯一", "必须", "其实",
    "always", "never", "must", "critical", "essential", "the point", "only",
    "actually", "really", "fundamentally",
)

#: Sentences longer than this get split at a soft separator to breathe.
LONG_SENTENCE_CHARS = 46
LONG_SENTENCE_LATIN_WORDS = 22

#: Pace multipliers. Small on purpose: a 0.8x segment sounds broken, a 0.97x
#: segment sounds like a person taking their time.
PACE_NORMAL = 1.0
PACE_EMPHATIC = 0.96
PACE_LONG_CLAUSE = 1.04
PACE_OPENING = 1.03
PACE_CLOSING = 0.95


@dataclass(frozen=True)
class ProsodySettings:
    """Tunables, so a project can shift the whole read without new rules."""

    pause_scale: float = 1.0
    #: Global reading speed. 1.0 = the engine's own default.
    pace: float = 1.0
    #: Multiplier applied to every computed pause.
    lead_in_ms: int = 120
    tail_ms: int = 320
    max_segment_chars: int = LONG_SENTENCE_CHARS
    emphasis_cues: tuple[str, ...] = EMPHASIS_CUES
    #: When set, only the first N segments keep their pause_before; used to stop
    #: a mid-scene transition from inheriting an opening beat.
    drop_leading_pause: bool = False


class ProsodyPlanner:
    """Turn narration text into segments with pauses, pace and emphasis."""

    def __init__(self, settings: ProsodySettings | None = None) -> None:
        self.settings = settings or ProsodySettings()

    # ------------------------------------------------------------------ API
    def plan(self, text: str, *, language: str = "zh-CN",
             emotion: str | None = None) -> ProsodyPlan:
        cleaned = self._normalise(text)
        if not cleaned:
            return ProsodyPlan(segments=[], language=language, planner="rule_based")

        raw = self._split(cleaned)
        segments: list[ProsodySegment] = []
        for index, (chunk, mark) in enumerate(raw):
            for piece in self._subdivide(chunk):
                segments.append(self._segment(piece, mark, index, len(raw), language, emotion))
        if not segments:
            return ProsodyPlan(segments=[], language=language, planner="rule_based")

        self._place_pauses(segments)
        return ProsodyPlan(
            segments=segments,
            language=language,
            total_pause_ms=sum(
                s.pause_before_ms + s.pause_after_ms for s in segments
            ),
            planner="rule_based",
        )

    # ------------------------------------------------------------- cleaning
    @staticmethod
    def _normalise(text: str) -> str:
        """Collapse whitespace without destroying CJK paragraph structure."""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{2,}", "\n", text)
        return text.strip()

    # -------------------------------------------------------------- split
    def _split(self, text: str) -> list[tuple[str, str]]:
        """Split into (chunk, trailing_mark) at terminal punctuation."""
        chunks: list[tuple[str, str]] = []
        buffer: list[str] = []
        length = len(text)
        position = 0

        while position < length:
            char = text[position]
            buffer.append(char)
            if char not in TERMINAL_MARKS:
                position += 1
                continue
            # "3.5", "e.g." and "No. 1" are not sentence ends. A period followed
            # by a digit or letter is almost always an interior dot; treating it
            # as terminal chops sentences in half at exactly the wrong place.
            if char in ".．" and self._is_interior_dot(text, position):
                position += 1
                continue
            # Absorb closing quotes/brackets that belong to this sentence.
            chunk_so_far = "".join(buffer)
            absorbed, last = self._absorb_closers(chunk_so_far, text, position)
            buffer.append(absorbed)
            chunk = "".join(buffer).strip()
            if chunk:
                chunks.append((chunk, char))
            buffer = []
            position = max(position, last) + 1

        remainder = "".join(buffer).strip()
        if remainder:
            chunks.append((remainder, ""))
        return chunks

    @staticmethod
    def _is_interior_dot(text: str, position: int) -> bool:
        """True when the period at ``position`` does not end a sentence.

        Four cases, all common enough that getting them wrong is visible:

        * a decimal — ``3.5``;
        * the dot *inside* an abbreviation — the first ``.`` in ``e.g.``;
        * the dot *after* a known abbreviation — the trailing ``.`` in ``etc.``;
        * a repeated dot — the interior of an ellipsis run.

        The abbreviation test looks at the *word fragment ending at this dot*,
        not at the whitespace-delimited token. ``at e.g.`` has a token of ``e``
        before the first dot and ``e.g`` before the second; splitting on
        whitespace alone cannot tell ``e.`` from ``etc.`` apart.
        """
        following = text[position + 1 : position + 2]
        if following.isdigit():
            return True
        if following == ".":
            return True

        # Fragment immediately before the dot, bounded by whitespace or any
        # punctuation that cannot appear inside a word.
        fragment = re.split(r"[\s，,。；;：:（(【\[“\"'、!？?]", text[:position])[-1].lower()
        fragment = fragment.rstrip("([{“\"'")

        # Single letters between dots are the interior of a dotted abbreviation:
        # "e.g." → before the first dot the fragment is "e", which is almost
        # certainly not a sentence of one letter.
        if len(fragment) == 1 and fragment.isalpha() and following.isalpha():
            return True
        if fragment in _ABBREVIATIONS:
            return True
        # "e.g" already holds a dot: the trailing dot is part of the same run.
        if "." in fragment:
            head = fragment.replace(".", "")
            if head in {"eg", "ie", "cf"} or head in _ABBREVIATIONS:
                return True
        return False

    @staticmethod
    def _absorb_closers(chunk_so_far: str, text: str, position: int) -> tuple[str, int]:
        """Return closing punctuation belonging to the sentence ending here.

        A closer is absorbed only when the chunk contains an unclosed matching
        opener. Without that check, ``“赢。”然后`` absorbs the *second* quote too
        and the next segment starts with a stray ``”`` — a one-character
        artefact that reads as a typo in the caption.
        """
        pairs = {"”": "“", "’": "‘", ")": "(", "）": "（", "]": "[",
                 "】": "【", "」": "「", "』": "『", "》": "《", '"': '"', "'": "'"}
        absorbed: list[str] = []
        index = position + 1
        while index < len(text) and text[index] in CLOSERS:
            closer = text[index]
            opener = pairs.get(closer)
            if opener is None:
                break
            # Already-closed pairs in the chunk, plus whatever we absorbed here.
            opened = chunk_so_far.count(opener)
            closed = chunk_so_far.count(closer) + absorbed.count(closer)
            if opened <= closed:
                break  # nothing left to close — this closer belongs elsewhere
            absorbed.append(closer)
            index += 1
        return "".join(absorbed), index - 1

    def _subdivide(self, chunk: str) -> list[str]:
        """Break an over-long clause at a soft separator so the reader breathes.

        Measured on the whole chunk including its terminal mark: a 48-character
        limit that ignored the final 。 would quietly allow 49-character
        sentences and make the threshold meaningless.
        """
        if not self._is_long(chunk):
            return [chunk]

        pieces: list[str] = []
        current: list[str] = []
        for char in chunk:
            current.append(char)
            if char not in SOFT_MARKS:
                continue
            candidate = "".join(current).strip()
            # Only break once the fragment is substantial, otherwise we trade a
            # long sentence for a stutter.
            if self._is_long(candidate):
                pieces.append(candidate)
                current = []
        tail = "".join(current).strip()
        if tail:
            # Re-merge only a token-length leftover. A clause like "所以必须切开它。"
            # is 8 characters but reads as a real closing thought; welding it back
            # on would undo the split entirely and leave the listener with the
            # same 56-character run we just decided was too long.
            if pieces and len(tail) <= 4:
                pieces[-1] = f"{pieces[-1]}{tail}"
            else:
                pieces.append(tail)
        return pieces or [chunk]

    def _is_long(self, text: str) -> bool:
        if len(text) >= self.settings.max_segment_chars:
            return True
        latin_words = len(re.findall(r"[A-Za-z']+", text))
        return latin_words >= LONG_SENTENCE_LATIN_WORDS

    # ------------------------------------------------------------ assemble
    def _segment(
        self,
        chunk: str,
        mark: str,
        index: int,
        total: int,
        language: str,
        emotion: str | None,
    ) -> ProsodySegment:
        base_pause = TERMINAL_MARKS.get(mark, 0) or SOFT_MARKS.get(mark, 0)
        emphasis = self._emphasis(chunk)
        rationale: list[str] = []

        if mark in TERMINAL_MARKS:
            rationale.append(f"terminal '{mark}' → {base_pause}ms")
        elif mark in SOFT_MARKS:
            rationale.append(f"soft '{mark}' → {base_pause}ms")

        pace = PACE_NORMAL
        if emphasis:
            pace = PACE_EMPHATIC
            rationale.append(f"emphasis on {emphasis}")
        if self._is_long(chunk):
            pace = max(pace, PACE_LONG_CLAUSE)
            rationale.append("long clause → slight acceleration to stay engaging")
        if index == 0 and total > 1:
            pace = min(pace, PACE_OPENING)
            rationale.append("opening line → unhurried")
        if index == total - 1 and total > 1:
            pace = min(pace, PACE_CLOSING)
            rationale.append("closing line → settled")

        return ProsodySegment(
            text=chunk,
            pause_before_ms=0,
            pause_after_ms=int(round(base_pause * self.settings.pause_scale)),
            emphasis=emphasis,
            pace=round(pace * self.settings.pace, 4),
            emotion=emotion,
            rationale="; ".join(rationale) or None,
        )

    def _emphasis(self, chunk: str) -> list[str]:
        lowered = chunk.lower()
        found: list[str] = []
        for cue in self.settings.emphasis_cues:
            if cue in chunk or cue.lower() in lowered:
                if cue not in found:
                    found.append(cue)
        return found

    def _place_pauses(self, segments: list[ProsodySegment]) -> None:
        """Give the first segment a lead-in and the last a settle-out beat.

        Mid-plan, ``pause_before`` stays 0 because the previous segment's
        ``pause_after`` already covers the gap. Counting it twice is how a plan
        ends up with a two-second hole in the middle of a sentence.
        """
        if not segments:
            return
        if not self.settings.drop_leading_pause:
            segments[0].pause_before_ms = int(
                round(self.settings.lead_in_ms * self.settings.pause_scale)
            )
        segments[-1].pause_after_ms += int(
            round(self.settings.tail_ms * self.settings.pause_scale)
        )


# ------------------------------------------------------------------ helpers
def plan_prosody(
    text: str,
    *,
    language: str = "zh-CN",
    emotion: str | None = None,
    settings: ProsodySettings | None = None,
) -> ProsodyPlan:
    """Convenience wrapper for the common case."""
    return ProsodyPlanner(settings).plan(text, language=language, emotion=emotion)


def join_segments(plan: ProsodyPlan) -> str:
    """Reassemble a plan's text — used by tests and by the caption stage."""
    return plan.text
