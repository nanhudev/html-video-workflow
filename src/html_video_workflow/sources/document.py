"""A source, normalised.

``sections`` and ``facts`` exist because planners need *structure*, not a blob:
a storyboard built from headings and bullet lines beats one built from a
3000-character paragraph that got truncated mid-sentence.
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceKind = Literal["text", "markdown", "webpage", "github", "file", "unknown"]


class SourceSection(BaseModel):
    model_config = ConfigDict(extra="allow")

    heading: str | None = None
    level: int = 1
    text: str = ""


class SourceDocument(BaseModel):
    """One readable document extracted from whatever the user handed us."""

    model_config = ConfigDict(extra="allow")

    id: str
    kind: SourceKind = "unknown"
    title: str | None = None
    url: str | None = None
    path: str | None = None
    language: str | None = None
    text: str = ""
    sections: list[SourceSection] = Field(default_factory=list)
    #: Bullet / short lines worth lifting onto a slide almost verbatim.
    facts: list[str] = Field(default_factory=list)
    trust: Literal["user_provided", "public_web", "model", "unknown"] = "user_provided"
    retrieved_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    char_count: int = 0
    truncated: bool = False
    sha256: str | None = None

    @property
    def headings(self) -> list[str]:
        return [s.heading for s in self.sections if s.heading]

    def summary(self, limit: int = 1200) -> str:
        """A planner-sized digest: headings first, then the densest facts."""
        parts: list[str] = []
        if self.title:
            parts.append(self.title)
        for section in self.sections[:12]:
            if section.heading:
                parts.append(f"## {section.heading}")
            body = _first_sentences(section.text, 2)
            if body:
                parts.append(body)
        if not parts:
            parts.append(_first_sentences(self.text, 6))
        for fact in self.facts[:12]:
            if fact not in parts:
                parts.append(f"- {fact}")
        return "\n".join(parts)[:limit]

    def fingerprint(self) -> str:
        payload = (self.url or self.path or self.title or "") + "\n" + self.text
        return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()[:16]


_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?.;；])\s*")


def _first_sentences(text: str, count: int) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    pieces = [p for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    return "".join(pieces[:count])
