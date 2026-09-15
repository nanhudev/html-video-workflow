"""PipelinePlanner — the decision record for one video.

It answers: which topic, which structure, which skin, which providers, how many
scenes, how long. Every answer carries a reason string, because the expensive
failure mode in a planner is not a wrong choice — it is a choice nobody can
explain afterwards.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..core.request import CreateVideoRequest, PlatformPreset
from ..sources.document import SourceDocument
from ..templates.models import StyleProfile, TemplateManifest
from ..templates.ranker import RankContext, RankedTemplate, TemplateRanker
from ..templates.registry import TemplateRegistry
from .script import ScriptPlanner, VideoScript
from .topic_planner import TopicPlanner, TopicSuggestion

_PREFERRED_RENDERER = "advanced_html"


class PipelinePlan(BaseModel):
    """Everything downstream needs, and everything a human might question."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    topic: str = ""
    topic_suggestion: TopicSuggestion | None = None
    template: TemplateManifest | None = None
    style: StyleProfile | None = None
    output: PlatformPreset | None = None

    scenes: int = 5
    duration_sec: float | None = None
    video_type: str = "explainer"
    language: str = "zh-CN"
    preset: str = "auto"

    llm: str | None = None
    tts: str | None = None
    renderer: str | None = None
    subtitle: str | None = None

    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    #: The full ranking, so "why not template X" is answerable.
    ranking: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def template_id(self) -> str:
        return self.template.id if self.template else ""

    @property
    def style_id(self) -> str:
        return self.style.id if self.style else ""


class PipelinePlanner:
    """Makes every product decision for one request. No I/O beyond probing."""

    def __init__(self, registry: TemplateRegistry | None = None,
                 llm: Any | None = None) -> None:
        from ..templates.registry import get_registry

        self.registry = registry or get_registry()
        self.topics = TopicPlanner(llm)
        self.scripts = ScriptPlanner(llm)
        self.ranker = TemplateRanker()

    # ------------------------------------------------------------------ public
    def plan(self, request: CreateVideoRequest,
             documents: list[SourceDocument] | None = None) -> PipelinePlan:
        documents = documents or []
        reasons: list[str] = []
        warnings: list[str] = []

        output = self._output(request, reasons, warnings)
        duration = self._duration(request, output, warnings)
        suggestion = self.topics.decide(request, documents)
        video_type = self._video_type(request, suggestion)

        context = self._rank_context(request, documents, output, duration, video_type)
        ranked = self.ranker.rank(self.registry.templates(), context)
        template, chosen_reason, template_warning = self._choose_template(
            request, ranked, context, reasons)
        if template_warning:
            warnings.append(template_warning)
        reasons.append(chosen_reason)

        style, style_reason, style_warning = self._choose_style(request, template)
        reasons.append(style_reason)
        if style_warning:
            warnings.append(style_warning)

        scenes = self._scenes(request, template, duration)
        reasons.append(f"scene count {scenes} "
                       f"(template {template.id} allows "
                       f"{template.scene_count.get('min', 3)}-"
                       f"{template.scene_count.get('max', 8)})")

        route = self._route(request)
        reasons.extend(self._route_reasons(route))

        return PipelinePlan(
            topic=suggestion.title,
            topic_suggestion=suggestion,
            template=template,
            style=style,
            output=output,
            scenes=scenes,
            duration_sec=duration,
            video_type=video_type,
            language=request.language,
            preset=route.get("preset", request.preset),
            llm=route["selection"].get("llm"),
            tts=route["selection"].get("tts"),
            renderer=self._renderer(request, route, reasons, warnings),
            subtitle=route["selection"].get("subtitle"),
            reasons=reasons,
            warnings=warnings,
            ranking=[{"id": item.id, "score": item.score, "reasons": item.reasons,
                      "eligible": item.ok} for item in ranked],
        )

    def build_script(self, plan: PipelinePlan, request: CreateVideoRequest,
                     documents: list[SourceDocument] | None = None) -> VideoScript:
        assert plan.template is not None
        return self.scripts.build(
            plan.topic,
            manifest=plan.template,
            language=plan.language,
            documents=documents or [],
            script_text=request.script,
            target_duration_sec=plan.duration_sec,
            scene_count=plan.scenes,
        )

    # --------------------------------------------------------------- internals
    def _output(self, request: CreateVideoRequest, reasons: list[str],
                warnings: list[str]) -> PlatformPreset:
        output = request.output()
        if request.platform and request.platform not in ("custom",):
            reasons.append(f"platform preset {output.id} → {output.width}x{output.height} "
                           f"{output.aspect}")
        else:
            reasons.append(f"no platform given → {output.id} "
                           f"({output.width}x{output.height} {output.aspect})")
        if output.safe_bottom >= 0.14:
            warnings.append(
                f"{output.label} overlays its own UI on the lower "
                f"{output.safe_bottom:.0%} of the frame; captions are inset accordingly")
        return output

    def _duration(self, request: CreateVideoRequest, output: PlatformPreset,
                  warnings: list[str]) -> float | None:
        duration = request.duration_sec
        if duration and output.max_duration_sec and duration > output.max_duration_sec:
            warnings.append(
                f"requested {duration:.0f}s exceeds {output.label}'s "
                f"{output.max_duration_sec:.0f}s limit — clamped")
            return float(output.max_duration_sec)
        return duration

    def _video_type(self, request: CreateVideoRequest,
                    suggestion: TopicSuggestion) -> str:
        # Nothing in V2 carries an explicit video_type on the request; the topic
        # angle is the best signal we have, and it is recorded so the choice is
        # auditable rather than implicit.
        return suggestion.video_type or "explainer"

    def _rank_context(self, request: CreateVideoRequest,
                      documents: list[SourceDocument], output: PlatformPreset,
                      duration: float | None, video_type: str) -> RankContext:
        import re

        facts = [fact for doc in documents for fact in doc.facts]
        return RankContext(
            topic=request.topic or request.prompt or "",
            video_type=video_type,
            aspect=output.aspect,
            platform=output.id,
            scenes=request.scenes,
            duration_sec=duration,
            has_data=any(re.search(r"\d", fact) for fact in facts),
            has_sources=bool(documents),
            has_screen_capture=False,
            source_headings=sum(len(doc.sections) for doc in documents),
            source_text="\n".join(doc.summary(1500) for doc in documents),
        )

    def _choose_template(self, request: CreateVideoRequest,
                         ranked: list[RankedTemplate], context: RankContext,
                         reasons: list[str]) -> tuple[TemplateManifest, str, str | None]:
        if request.template:
            manifest = self.registry.find(request.template)
            if manifest is None:
                fallback = self.registry.default_template()
                return fallback, (
                    f"template {request.template!r} not found → {fallback.id}"
                ), (f"unknown template requested: {request.template}")
            _, why = self.ranker._passes_filters(manifest, context)  # noqa: SLF001
            warning = None
            if why:
                warning = f"forced template {manifest.id} does not fit: {why}"
            return manifest, f"template {manifest.id} forced by request", warning

        for item in ranked:
            if item.ok and item.manifest is not None:
                return item.manifest, (
                    f"template {item.manifest.id} ranked first "
                    f"(score {item.score:.2f}: {'; '.join(item.reasons) or 'no signal'})"
                ), None
        fallback = self.registry.default_template()
        blocked = "; ".join(f"{item.id}: {item.reasons[0]}" for item in ranked[:3])
        return fallback, f"no template passed the filters → {fallback.id}", (
            f"every template was filtered out ({blocked}) — falling back to "
            f"{fallback.id}, which will look generic")

    def _choose_style(self, request: CreateVideoRequest,
                      template: TemplateManifest
                      ) -> tuple[StyleProfile, str, str | None]:
        if request.style:
            style = self.registry.find_style(request.style)
            if style is None:
                default = self._default_style(template)
                return default, f"style {request.style!r} unknown → {default.id}", (
                    f"unknown style requested: {request.style}")
            if style.id not in (template.compatible_styles or [template.default_style]):
                return style, f"style {style.id} forced by request", (
                    f"style {style.id} is not listed as compatible with "
                    f"template {template.id}; visuals may not match the argument")
            return style, f"style {style.id} forced by request", None
        default = self._default_style(template)
        return default, f"style {default.id} (template default)", None

    def _default_style(self, template: TemplateManifest) -> StyleProfile:
        style = self.registry.find_style(template.default_style)
        if style is None:
            styles = self.registry.styles_for(template)
            style = styles[0] if styles else self.registry.default_style()
        return style

    def _scenes(self, request: CreateVideoRequest, template: TemplateManifest,
                duration: float | None) -> int:
        if request.scenes:
            return template.clamp_scenes(request.scenes)
        if duration:
            # ~5s per scene is the floor for a beat to land before the cut.
            return template.clamp_scenes(max(3, round(duration / 5.0)))
        return template.clamp_scenes(None)

    def _route(self, request: CreateVideoRequest) -> dict[str, Any]:
        from ..pipeline.router import plan_pipeline

        return plan_pipeline(
            language=request.language,
            preset=request.preset,
            overrides=request.overrides(),
        )

    def _route_reasons(self, route: dict[str, Any]) -> list[str]:
        out = [f"routing preset {route.get('preset')}"]
        for stage, provider in (route.get("selection") or {}).items():
            out.append(f"{stage} → {provider or 'NONE AVAILABLE'}")
        return out

    def _renderer(self, request: CreateVideoRequest, route: dict[str, Any],
                  reasons: list[str], warnings: list[str]) -> str | None:
        selected = (route.get("selection") or {}).get("renderer")
        if request.renderer:
            return selected
        if selected == _PREFERRED_RENDERER:
            return selected
        try:
            from ..providers.registry import get as get_provider

            preferred = get_provider(_PREFERRED_RENDERER)
        except Exception:  # noqa: BLE001 - absence is a real, expected outcome
            warnings.append(
                f"{_PREFERRED_RENDERER} unavailable; using {selected or 'none'}, which "
                f"down-converts IR V2 and drops the layout/motion vocabulary")
            return selected
        if preferred.probe().available:
            reasons.append(
                f"renderer {selected} → {_PREFERRED_RENDERER} (one-click pipeline "
                f"authors IR V2 natively)")
            warnings.append(
                f"routing preferred {selected or 'none'}; overridden to "
                f"{_PREFERRED_RENDERER} so the IR renders without down-conversion")
            return _PREFERRED_RENDERER
        warnings.append(
            f"{_PREFERRED_RENDERER} not available; using {selected or 'none'}")
        return selected
