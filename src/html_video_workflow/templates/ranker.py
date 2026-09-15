"""TemplateRanker — choose the structure, and say why.

Ranking is two-phase on purpose. **Hard filters first**: a template that cannot
run (wrong aspect, missing required material) must never reach the scoring
stage, because a score good enough to beat the filter is a score that ships a
broken video. Weighted scoring only then orders what survived.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from .models import TemplateManifest

_DIGIT = re.compile(r"\d")
_OPINION = re.compile(
    r"为什么|应该|误区|误解|值得|争议|其实|真正|why|should|myth|versus|vs\b|wrong", re.I)
_STEP = re.compile(r"步骤|流程|如何|怎么|教程|step|how\s+to|workflow|pipeline", re.I)
_NARRATIVE = re.compile(r"故事|历程|发展|历史|背景|story|history|journey|case", re.I)


@dataclass
class RankContext:
    """Everything the ranker is allowed to look at."""

    topic: str = ""
    video_type: str | None = None
    aspect: str = "16:9"
    platform: str | None = None
    scenes: int | None = None
    duration_sec: float | None = None
    has_data: bool = False
    has_sources: bool = False
    has_screen_capture: bool = False
    source_headings: int = 0
    source_text: str = ""
    keywords: list[str] = field(default_factory=list)

    def features(self) -> dict[str, float]:
        """A 0..1 feature vector. Named to match ``score_hints`` keys."""
        text = f"{self.topic} {self.source_text[:2000]}"
        duration = self.duration_sec or 0.0
        scenes = self.scenes or 0
        return {
            "numeric": 1.0 if (self.has_data or _DIGIT.search(self.topic)) else 0.0,
            "opinionated": 1.0 if _OPINION.search(text) else 0.25,
            "steps": 1.0 if _STEP.search(text) or self.source_headings >= 4 else 0.2,
            "structural": 0.7 if self.source_headings >= 3 else 0.4,
            "narrative": 1.0 if _NARRATIVE.search(text) else 0.3,
            "short": 1.0 if (duration and duration <= 60) or (scenes and scenes <= 4) else 0.0,
            "long": 1.0 if (duration and duration >= 180) or (scenes and scenes >= 8) else 0.0,
            "vertical": 1.0 if self.aspect == "9:16" else 0.0,
        }


class RankedTemplate(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    id: str = ""
    score: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    manifest: TemplateManifest | None = None

    @property
    def ok(self) -> bool:
        return self.manifest is not None


class TemplateRanker:
    """Ranks templates against a context. Deterministic: no model, no state."""

    def rank(self, templates: list[TemplateManifest],
             context: RankContext) -> list[RankedTemplate]:
        features = context.features()
        ranked: list[RankedTemplate] = []
        for manifest in templates:
            reasons: list[str] = []
            allowed, why = self._passes_filters(manifest, context)
            if not allowed:
                ranked.append(RankedTemplate(id=manifest.id, score=-1.0,
                                             reasons=[why], manifest=None))
                continue
            score = self._score(manifest, context, features, reasons)
            ranked.append(RankedTemplate(id=manifest.id, score=round(score, 4),
                                         reasons=reasons, manifest=manifest))
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked

    def best(self, templates: list[TemplateManifest],
             context: RankContext) -> RankedTemplate | None:
        eligible = [item for item in self.rank(templates, context) if item.ok]
        return eligible[0] if eligible else None

    # --------------------------------------------------------------- internals
    def _passes_filters(self, manifest: TemplateManifest,
                        context: RankContext) -> tuple[bool, str]:
        if not manifest.supports_aspect(context.aspect):
            return False, (f"template {manifest.id} does not support aspect "
                           f"{context.aspect}")
        if not manifest.supports_platform(context.platform):
            return False, f"template {manifest.id} does not support {context.platform}"
        if context.video_type and context.video_type in manifest.not_for:
            return False, (f"template {manifest.id} explicitly avoids "
                           f"video_type={context.video_type}")
        available = {
            "data": context.has_data,
            "screen_capture": context.has_screen_capture,
            "sources": context.has_sources,
        }
        for requirement in manifest.requires:
            if not available.get(requirement, False):
                return False, (f"template {manifest.id} requires {requirement}, "
                               f"which this request does not have")
        return True, ""

    def _score(self, manifest: TemplateManifest, context: RankContext,
               features: dict[str, float], reasons: list[str]) -> float:
        hints = manifest.score_hints or {}
        if hints:
            weighted = sum(hints.get(key, 0.0) * value for key, value in features.items())
            total = sum(abs(value) for value in hints.values()) or 1.0
            score = weighted / total
        else:
            score = 0.5
        if context.video_type and context.video_type in manifest.best_for:
            score += 0.25
            reasons.append(f"video_type={context.video_type} is in best_for")
        if context.scenes:
            clamped = manifest.clamp_scenes(context.scenes)
            if clamped != context.scenes:
                score -= 0.08
                reasons.append(f"scene count clamped {context.scenes} -> {clamped}")
        if hints:
            top = sorted(hints.items(), key=lambda kv: kv[1], reverse=True)[:2]
            reasons.append("matches " + ", ".join(
                f"{key}={features.get(key, 0):.1f}" for key, _ in top))
        return max(0.0, min(score, 1.2))
