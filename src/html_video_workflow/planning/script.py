"""ScriptPlanner — turns a topic (plus optional sources) into narration.

The default path is **rule-based and offline**. It is not trying to be a model;
it is trying to be *good enough to be watchable* when no model is configured,
which is the difference between a product that works out of the box and a
product that returns 503 on first contact. When an LLM provider is available
and healthy, ``ScriptPlanner`` uses it and falls back to rules on any failure —
recording the fallback like every other degradation in this codebase.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..sources.document import SourceDocument
from ..templates.models import TemplateManifest, WritingPreset
from ..utils.audio import estimate_speech_seconds
from ..utils.logging import get_logger
from .presets import compose_system_prompt

log = get_logger("planning.script")

#: ``{t}`` = topic, ``{f}`` = a fact lifted from the source, ``{n}`` = index.
_BEATS: dict[str, dict[str, dict[str, str]]] = {
    "hook": {
        "label": {"zh": "开场", "en": "Hook"},
        "headline": {"zh": "{t}", "en": "{t}"},
        "narration": {
            "zh": "先问一个更基础的问题：{t} 为什么值得单独拿出几分钟来讲？答案不在定义里，而在它改变了什么。",
            "en": "Start with a more basic question: why is {t} worth several minutes? The answer is not the definition — it is what changes.",
        },
    },
    "claim": {
        "label": {"zh": "核心判断", "en": "The claim"},
        "headline": {"zh": "核心判断", "en": "The claim"},
        "narration": {
            "zh": "如果只留一句话：{t} 的价值不来自它是什么，而来自它替你省掉了什么。",
            "en": "If one sentence survives: {t} is valuable not for what it is, but for what it removes.",
        },
    },
    "evidence": {
        "label": {"zh": "依据", "en": "Evidence"},
        "headline": {"zh": "可以验证的依据", "en": "Checkable evidence"},
        "narration": {
            "zh": "{f}",
            "en": "{f}",
        },
    },
    "tension": {
        "label": {"zh": "边界", "en": "Where it breaks"},
        "headline": {"zh": "它在哪里会失效", "en": "Where it breaks"},
        "narration": {
            "zh": "但 {t} 不是万能的。约束一变，它的优势会迅速消失——记住边界比记住优点更有用。",
            "en": "But {t} is not universal. Change the constraint and the advantage evaporates — knowing the boundary beats knowing the benefit.",
        },
    },
    "payoff": {
        "label": {"zh": "下一步", "en": "What to do"},
        "headline": {"zh": "下一步怎么做", "en": "What to do next"},
        "narration": {
            "zh": "所以如果你要动 {t}，先做最小的一步：找一个真实场景，量一次，再决定要不要铺开。",
            "en": "So if you are going to act on {t}, do the smallest thing first: pick one real case, measure once, then decide whether to scale.",
        },
    },
    "problem": {
        "label": {"zh": "问题", "en": "The problem"},
        "headline": {"zh": "问题出在哪", "en": "Where it hurts"},
        "narration": {
            "zh": "在没有 {t} 之前，这件事通常靠人肉兜底：慢、不可重复、出错才发现。",
            "en": "Before {t}, this was handled by hand: slow, unrepeatable, and only visible once it broke.",
        },
    },
    "overview": {
        "label": {"zh": "全貌", "en": "The shape of it"},
        "headline": {"zh": "整体是怎么运转的", "en": "How it fits together"},
        "narration": {
            "zh": "把 {t} 拆开看，只有三件事：输入进来、中间被处理、结果被写出去。复杂度都在中间那一层。",
            "en": "Broken down, {t} is three things: input arrives, something happens in the middle, a result comes out. All the complexity lives in the middle.",
        },
    },
    "step": {
        "label": {"zh": "机制", "en": "Mechanism"},
        "headline": {"zh": "关键一步", "en": "The key step"},
        "narration": {
            "zh": "{f}",
            "en": "{f}",
        },
    },
    "recap": {
        "label": {"zh": "回顾", "en": "Recap"},
        "headline": {"zh": "回到开头的问题", "en": "Back to the opening question"},
        "narration": {
            "zh": "回到最开始：{t} 解决的不是某个技术细节，而是把不确定的事情变成可以重复执行的事情。",
            "en": "Back to the start: {t} is not fixing a technical detail — it is turning something uncertain into something repeatable.",
        },
    },
    "headline_number": {
        "label": {"zh": "关键数字", "en": "The number"},
        "headline": {"zh": "一个数字先看清楚", "en": "One number first"},
        "narration": {
            "zh": "{f}",
            "en": "{f}",
        },
    },
    "supporting": {
        "label": {"zh": "支撑", "en": "Supporting numbers"},
        "headline": {"zh": "支撑这个数字的是什么", "en": "What holds it up"},
        "narration": {
            "zh": "{f}",
            "en": "{f}",
        },
    },
    "caveat": {
        "label": {"zh": "口径", "en": "Caveat"},
        "headline": {"zh": "先说清楚口径", "en": "Read the caveat"},
        "narration": {
            "zh": "任何关于 {t} 的数字都要看口径：样本是谁、时间窗口多长、有没有把异常值算进去。",
            "en": "Any number about {t} depends on its definition: who is in the sample, over what window, and whether outliers were kept.",
        },
    },
    "pain": {
        "label": {"zh": "痛点", "en": "The pain"},
        "headline": {"zh": "现在的做法哪里痛", "en": "What hurts today"},
        "narration": {
            "zh": "现在的流程里，最贵的不是执行，而是等待和返工。{t} 就是从这两处下手。",
            "en": "In the current flow the expensive part is not doing the work — it is waiting and redoing. That is where {t} cuts.",
        },
    },
    "capability": {
        "label": {"zh": "能力", "en": "Capability"},
        "headline": {"zh": "它能做什么", "en": "What it does"},
        "narration": {
            "zh": "{t} 做的事很朴素：把重复的判断固化下来，让人只处理例外。",
            "en": "What {t} does is simple: it fixes the repeated decisions so people only handle the exceptions.",
        },
    },
    "walkthrough": {
        "label": {"zh": "演示", "en": "Walkthrough"},
        "headline": {"zh": "走一遍真实流程", "en": "One real pass"},
        "narration": {
            "zh": "走一遍：准备输入、触发、看结果。三步里只有第二步需要人做决定。",
            "en": "One pass: prepare the input, trigger it, read the result. Only the middle step needs a human decision.",
        },
    },
    "result": {
        "label": {"zh": "结果", "en": "Result"},
        "headline": {"zh": "做完之后变了什么", "en": "What changed"},
        "narration": {
            "zh": "做完之后最直观的变化是时间：原来以天计，现在以分钟计。",
            "en": "The most visible change is time: what took days now takes minutes.",
        },
    },
    "turn": {
        "label": {"zh": "转折", "en": "The turn"},
        "headline": {"zh": "但这里有个反转", "en": "Here is the turn"},
        "narration": {
            "zh": "这里有个反转：{t} 真正难的不是开始，而是在规模变大之后还能保持一样的结果。",
            "en": "Here is the turn: the hard part of {t} is not starting — it is keeping the same result once it scales.",
        },
    },
    "proof": {
        "label": {"zh": "证据", "en": "Proof"},
        "headline": {"zh": "凭什么这么说", "en": "Why believe it"},
        "narration": {
            "zh": "{f}",
            "en": "{f}",
        },
    },
    "cta": {
        "label": {"zh": "收尾", "en": "Wrap up"},
        "headline": {"zh": "记住这一句就够了", "en": "Remember this one line"},
        "narration": {
            "zh": "记住这一句：先把 {t} 用在一个小地方，再谈全面替换。",
            "en": "Remember one line: use {t} in one small place before you talk about replacing everything.",
        },
    },
    "definition": {
        "label": {"zh": "是什么", "en": "What it is"},
        "headline": {"zh": "先说清楚它是什么", "en": "What it actually is"},
        "narration": {
            "zh": "{t} 可以先用一句话概括：它把原本依赖经验的操作，变成可以重复执行的流程。",
            "en": "One line on {t}: it turns something that relied on experience into something repeatable.",
        },
    },
    "why": {
        "label": {"zh": "为什么", "en": "Why it matters"},
        "headline": {"zh": "为什么现在需要它", "en": "Why now"},
        "narration": {
            "zh": "为什么是现在：规模上去了，靠人扛的部分先崩。{t} 就是在那个位置接住它。",
            "en": "Why now: once scale grows, the human-held parts break first. {t} catches it at exactly that point.",
        },
    },
    "example": {
        "label": {"zh": "例子", "en": "Example"},
        "headline": {"zh": "看一个具体例子", "en": "One concrete example"},
        "narration": {
            "zh": "{f}",
            "en": "{f}",
        },
    },
    "boundary": {
        "label": {"zh": "边界", "en": "Limits"},
        "headline": {"zh": "什么时候不该用它", "en": "When not to use it"},
        "narration": {
            "zh": "什么时候不该用 {t}：场景一次性的、规则还在变的、出错代价极高的——这三类先别动。",
            "en": "When not to reach for {t}: one-off cases, rules still in flux, and anything where being wrong is expensive.",
        },
    },
    "context": {
        "label": {"zh": "背景", "en": "Context"},
        "headline": {"zh": "先把背景摆正", "en": "Setting the scene"},
        "narration": {
            "zh": "在讲 {t} 之前，先看它出现的位置：它是在旧流程撑不住的时候才被需要的。",
            "en": "Before {t} itself, look at where it shows up: it is needed precisely when the old flow stops holding.",
        },
    },
    "development": {
        "label": {"zh": "展开", "en": "Development"},
        "headline": {"zh": "它是怎么长成这样的", "en": "How it got here"},
        "narration": {
            "zh": "{f}",
            "en": "{f}",
        },
    },
    "contrast": {
        "label": {"zh": "对照", "en": "Contrast"},
        "headline": {"zh": "和另一种做法比一比", "en": "Against the alternative"},
        "narration": {
            "zh": "和另一种做法相比，{t} 换来的是一致性，代价是前期的约束更多。",
            "en": "Against the alternative, {t} buys consistency and charges for it in upfront constraints.",
        },
    },
    "detail": {
        "label": {"zh": "细节", "en": "Detail"},
        "headline": {"zh": "一处容易被忽略的细节", "en": "An overlooked detail"},
        "narration": {
            "zh": "{f}",
            "en": "{f}",
        },
    },
    "close": {
        "label": {"zh": "收束", "en": "Close"},
        "headline": {"zh": "留一个问题给你", "en": "One question to leave with"},
        "narration": {
            "zh": "最后留一个问题：在你现在的流程里，哪一个环节最该被 {t} 替换掉？",
            "en": "One question to leave you with: in your current flow, which step most deserves to be replaced by {t}?",
        },
    },
}

_FALLBACK_BEAT = "claim"

#: A scene shorter than this reads as a flash, so it is a floor on timing — and
#: therefore a floor on the total: N scenes can never run for less than
#: ``N * _MIN_SCENE_SEC``, however short the narration is.
_MIN_SCENE_SEC = 3.0
_MAX_SCENE_SEC = 12.0
#: Breathing room after the last syllable. A cut that lands on the final sound
#: reads as rushed, and the pause is where the point lands.
_BEAT_PADDING_SEC = 0.9


class ScriptBeat(BaseModel):
    """One scene's worth of narration and the words that go on screen."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    kind: str = "claim"
    label: str = ""
    headline: str = ""
    narration: str = ""
    #: Words the TTS layer should lean on, and the renderer may emphasise.
    emphasis: list[str] = Field(default_factory=list)
    duration_sec: float = 4.0
    #: Layout primitive this beat wants; the storyboard may still override.
    layout: str | None = None


class VideoScript(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str = ""
    logline: str = ""
    topic: str = ""
    language: str = "zh-CN"
    beats: list[ScriptBeat] = Field(default_factory=list)
    source_facts: list[str] = Field(default_factory=list)
    generated_by: str = "rule"
    #: Which writing preset the narration was written under, if any. Provenance
    #: matters more than it looks: two videos with identical beats are
    #: different products depending on this field.
    writing_preset: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @property
    def total_duration(self) -> float:
        return round(sum(beat.duration_sec for beat in self.beats), 2)

    def narration_texts(self) -> list[str]:
        return [beat.narration for beat in self.beats if beat.narration]


def _lang_key(language: str) -> str:
    return "en" if language.lower().startswith("en") else "zh"


def _chars_per_sec(language: str) -> float:
    """Matches ``utils.audio.estimate_speech_seconds``: 5.2 CJK chars/s, ~13
    latin chars/s. Using a different number here would make the storyboard
    disagree with the audio stage about how long a scene lasts."""
    return 13.0 if _lang_key(language) == "en" else 5.2


class ScriptPlanner:
    """Builds a VideoScript. Rules first, model when one is actually available."""

    def __init__(self, llm_provider: Any | None = None) -> None:
        self._llm = llm_provider

    def use_provider(self, llm_provider: Any | None) -> None:
        """Attach the language model the router actually selected.

        Exists because the decision belongs to the router, not to this class:
        ``create_video`` builds a planner before it knows the routing, and the
        first version never attached anything afterwards — so a configured API
        key changed the *plan* and nothing about the words, which is precisely
        the "I paid for a model and got templates" failure.
        """
        self._llm = llm_provider

    def build(
        self,
        topic: str,
        *,
        manifest: TemplateManifest,
        language: str = "zh-CN",
        documents: list[SourceDocument] | None = None,
        script_text: str | None = None,
        target_duration_sec: float | None = None,
        scene_count: int | None = None,
        preset: WritingPreset | None = None,
        custom_brief: str | None = None,
    ) -> VideoScript:
        warnings: list[str] = []
        if script_text and script_text.strip():
            beats = self._from_user_script(script_text, language)
            generated_by = "user"
        else:
            beats = self._from_beats(topic, manifest, language, documents or [],
                                     scene_count)
            generated_by = "rule"
            llm_beats, failure = self._try_llm(
                topic, manifest, language, documents or [],
                preset=preset, custom_brief=custom_brief)
            if llm_beats:
                beats, generated_by = llm_beats, "llm"
            elif failure:
                # A configured model that failed is not the same product as no
                # model at all, and it is not the user's fault. Saying which one
                # happened is the difference between a debuggable product and a
                # mysterious one.
                warnings.append(
                    f"the language model was available but the script call failed "
                    f"({failure}); the built-in rule writer produced the narration "
                    f"instead")

        beats = self._fit_duration(beats, language, manifest, target_duration_sec,
                                   warnings)
        facts = [fact for doc in (documents or []) for fact in doc.facts][:12]
        return VideoScript(
            title=topic,
            logline=self._logline(topic, language, beats),
            topic=topic,
            language=language,
            beats=beats,
            source_facts=facts,
            generated_by=generated_by,
            writing_preset=preset.id if preset else None,
            warnings=warnings,
        )

    # --------------------------------------------------------------- internals
    def _from_beats(self, topic: str, manifest: TemplateManifest, language: str,
                    documents: list[SourceDocument],
                    scene_count: int | None) -> list[ScriptBeat]:
        key = _lang_key(language)
        names = list(manifest.beats) or ["hook", "claim", "evidence", "payoff"]
        wanted = manifest.clamp_scenes(scene_count)
        if len(names) > wanted:
            # Trim from the middle, never the hook or the ending: a video that
            # opens and closes badly is worse than one that is shorter.
            head, tail = names[:2], names[-1:]
            middle = names[2:-1]
            step = max(1, len(middle) / max(1, wanted - len(head) - len(tail)))
            kept = [middle[int(i * step)] for i in range(wanted - len(head) - len(tail))]
            names = head + kept + tail
        elif len(names) < wanted:
            filler = [name for name in ("evidence", "detail", "example")
                      if name in _BEATS]
            while len(names) < wanted:
                names.append(filler[len(names) % len(filler)])

        facts = self._fact_pool(documents, topic, language)
        beats: list[ScriptBeat] = []
        for index, name in enumerate(names, start=1):
            spec = _BEATS.get(name) or _BEATS[_FALLBACK_BEAT]
            fact = facts[(index - 1) % len(facts)] if facts else ""
            narration = spec["narration"][key]
            if "{f}" in narration:
                narration = narration.replace("{f}", fact) if fact else \
                    _BEATS[_FALLBACK_BEAT]["narration"][key].replace("{t}", topic)
            narration = narration.replace("{t}", topic).replace("{n}", str(index))
            headline = spec["headline"][key].replace("{t}", topic)
            beats.append(
                ScriptBeat(
                    id=f"b{index}",
                    kind=name,
                    label=spec["label"][key],
                    headline=headline if len(headline) <= 40 else topic,
                    narration=narration,
                    emphasis=[topic] if topic else [],
                    layout=_BEAT_LAYOUT.get(name),
                )
            )
        return beats

    def _from_user_script(self, script_text: str, language: str) -> list[ScriptBeat]:
        blocks = [b.strip() for b in re.split(r"\n\s*\n", script_text) if b.strip()]
        if len(blocks) < 2:
            blocks = [s.strip() for s in re.split(r"(?<=[。！？.!?])\s*", script_text)
                      if len(s.strip()) > 8]
        # Pack very short sentences so a 40-line script does not become 40 scenes.
        packed: list[str] = []
        for block in blocks:
            if packed and len(packed[-1]) + len(block) < 90:
                packed[-1] = f"{packed[-1]} {block}"
            else:
                packed.append(block)
        key = _lang_key(language)
        return [
            ScriptBeat(
                id=f"b{index}",
                kind="evidence",
                label=(_BEATS["evidence"]["label"][key]),
                headline=_headline_from_text(text, index),
                narration=text,
                layout=None,
            )
            for index, text in enumerate(packed[:24], start=1)
        ]

    def _try_llm(self, topic: str, manifest: TemplateManifest, language: str,
                 documents: list[SourceDocument], *,
                 preset: WritingPreset | None = None,
                 custom_brief: str | None = None,
                 ) -> tuple[list[ScriptBeat] | None, str | None]:
        """Ask the configured model for the narration.

        Returns ``(beats, None)`` on success and ``(None, reason)`` when a model
        was configured but the call failed. The reason is a *value* rather than
        a log line because "the model is configured and broken" needs a
        different fix from "no model is configured", and the previous
        ``except Exception: return None`` collapsed both into silence.
        """
        if self._llm is None:
            return None, None
        key = _lang_key(language)
        kinds = [
            (name, str((_BEATS.get(name, {}).get("label") or {}).get(key, name)))
            for name in (manifest.beats or ["hook", "claim", "evidence", "payoff"])
        ]
        system = compose_system_prompt(
            preset,
            language=language,
            custom=custom_brief,
            kinds=kinds,
            max_chars=int(manifest.narration.get("max_chars_per_scene", 130)),
        )
        try:
            from ..providers.base import LLMRequest

            digest = "\n".join(doc.summary(800) for doc in documents)[:3000]
            material = f"\n可用材料：\n{digest}" if digest.strip() else ""
            response = self._llm.complete(LLMRequest(
                prompt=(
                    f"视频主题：{topic}\n"
                    f"语言：{language}\n"
                    f"节拍数量：{len(kinds)}"
                    f"{material}"
                ),
                system=system,
                json_mode=True,
            ))
            import json

            payload = _loads(response.text)
            beats: list[ScriptBeat] = []
            for index, item in enumerate(payload.get("beats") or [], start=1):
                narration = str(item.get("narration") or "").strip()
                if not narration:
                    continue
                beats.append(ScriptBeat(
                    id=f"b{index}",
                    kind=str(item.get("kind") or "claim"),
                    label=str(item.get("label") or ""),
                    headline=str(item.get("headline") or "")[:40],
                    narration=narration,
                    layout=_BEAT_LAYOUT.get(str(item.get("kind") or "")),
                ))
            if not beats:
                return None, "the model returned no usable beats"
            return beats, None
        except Exception as exc:  # noqa: BLE001 - the rules are the fallback
            log.warning("script call via %s failed: %s", getattr(self._llm, "id", "?"), exc)
            return None, f"{type(exc).__name__}: {exc}"

    def _fit_duration(self, beats: list[ScriptBeat], language: str,
                      manifest: TemplateManifest, target: float | None,
                      warnings: list[str]) -> list[ScriptBeat]:
        """Make the *words* fit the target, not the clock.

        The first version rescaled ``duration_sec`` until the numbers added up to
        the requested total while the narration stayed just as long. The result
        was a "20 second" video that ran 32 seconds, because the audio stage
        measures the text and the scene timing is downstream of it. Timing is a
        consequence of the words; changing it without changing the words is a
        lie the render happily exposes.
        """
        cps = float(manifest.narration.get("chars_per_sec") or _chars_per_sec(language))
        max_chars = int(manifest.narration.get("max_chars_per_scene") or 130)

        budget = max_chars
        per_beat: float | None = None
        if target and beats:
            # Reserve the inter-beat pause before dividing, or the sum overshoots.
            spendable = max(4.0, float(target) - _BEAT_PADDING_SEC * len(beats))
            per_beat = spendable / len(beats)
            budget = max(10, int(per_beat * cps))
            if budget < max_chars:
                warnings.append(
                    f"narration trimmed to ~{budget} chars per scene to fit "
                    f"{target:.0f}s; a longer duration or fewer scenes would "
                    f"leave the text intact")

        for beat in beats:
            beat.narration = beat.narration.strip()
            if len(beat.narration) > budget:
                beat.narration = _truncate(beat.narration, budget)
            if per_beat is not None:
                # Measure with the *same* estimator the audio stage uses.
                # Counting characters here instead made English narration ~14%
                # long, because the canonical estimator ignores whitespace.
                beat.narration = _trim_to_seconds(beat.narration, per_beat, cps)
            spoken = estimate_speech_seconds(beat.narration, cps)
            beat.duration_sec = round(
                min(_MAX_SCENE_SEC,
                    max(_MIN_SCENE_SEC, spoken + _BEAT_PADDING_SEC)), 2)

        if target and beats:
            total = sum(beat.duration_sec for beat in beats)
            if total < float(target) * 0.9:
                # Trimming can make a video shorter, never longer. A target the
                # material cannot fill has to be *reported*, not quietly
                # missed: padding the gap with held frames is just dead air.
                warnings.append(
                    f"narration fills only ~{total:.0f}s of the requested "
                    f"{target:.0f}s; add material, more scenes or a shorter "
                    f"target to close the gap")
            elif total > float(target) * 1.1:
                # The other missed direction: trimming cannot go below the
                # per-scene floor, so a very short target is unreachable once
                # the template requires more scenes than the budget allows.
                # Asking for 6s and shipping 9s silently is the same lie as the
                # original 20s-that-was-32s, just in the other direction.
                warnings.append(
                    f"scenes cannot be shorter than {_MIN_SCENE_SEC:.1f}s each, "
                    f"so {len(beats)} scenes need ~{total:.0f}s; the "
                    f"{target:.0f}s target is below what this template can "
                    f"produce — raise it or pick a template with fewer scenes")
        return beats

    def _fact_pool(self, documents: list[SourceDocument], topic: str,
                   language: str) -> list[str]:
        facts = [fact for doc in documents for fact in doc.facts if 8 <= len(fact) <= 120]
        if not facts:
            for doc in documents:
                facts.extend(_fact_candidates(doc.text))
        if not facts:
            key = _lang_key(language)
            facts = [
                f"先看一个可以直接验证的点：把 {topic} 放进真实流程里跑一遍，"
                f"记录耗时和错误率。" if key == "zh" else
                f"One checkable point: run {topic} through a real flow and record "
                f"time spent and error rate.",
                f"第二个证据来自对比：同样的任务，换一种做法，差距往往出现在返工次数上。"
                if key == "zh" else
                f"A second piece of evidence comes from comparison: same task, "
                f"different method, and the gap shows up in rework.",
                f"第三点最容易被忽略：{topic} 的成本不在搭建，而在长期维护。" if key == "zh"
                else f"The most overlooked point: the cost of {topic} is not setup, "
                     f"it is upkeep.",
            ]
        return facts[:8]

    def _logline(self, topic: str, language: str, beats: list[ScriptBeat]) -> str:
        if not beats:
            return topic
        key = _lang_key(language)
        if key == "en":
            return f"{topic} — in {len(beats)} beats, from the question to what to do."
        return f"{topic}——用 {len(beats)} 个段落，从问题讲到该怎么做。"


#: Layout primitive each narrative beat naturally wants.
_BEAT_LAYOUT: dict[str, str] = {
    "hook": "center",
    "claim": "editorial_left",
    "evidence": "split",
    "tension": "quote",
    "payoff": "editorial_left",
    "problem": "split",
    "overview": "diagram",
    "step": "diagram",
    "recap": "editorial_left",
    "headline_number": "stat",
    "supporting": "split",
    "caveat": "editorial_left",
    "pain": "split",
    "capability": "split",
    "walkthrough": "full_bleed",
    "result": "stat",
    "turn": "quote",
    "proof": "stat",
    "cta": "center",
    "definition": "editorial_left",
    "why": "split",
    "example": "editorial_left",
    "boundary": "quote",
    "context": "full_bleed",
    "development": "editorial_left",
    "contrast": "split",
    "detail": "editorial_left",
    "close": "center",
}


def _headline_from_text(text: str, index: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    head = re.split(r"[。！？.!?]", cleaned)[0]
    return (head or cleaned)[:28] or f"第 {index} 段"


def _trim_to_seconds(text: str, seconds: float, cps: float) -> str:
    """Longest prefix of ``text`` that still fits ``seconds`` of speech.

    A binary search rather than a proportional cut because the estimator is not
    linear in string length — it charges CJK and latin characters at different
    rates. Cutting ``len(text) * ratio`` lands either side of the budget
    depending on which script the narration happens to be in.
    """
    if estimate_speech_seconds(text, cps) <= seconds:
        return text
    lo, hi = 1, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        if estimate_speech_seconds(text[:mid], cps) > seconds:
            lo = mid + 1
        else:
            hi = mid
    return _truncate(text, lo)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    window = text[:limit]
    for pivot in ("。", "！", "？", ". ", "，", ", "):
        cut = window.rfind(pivot)
        if cut > limit * 0.55:
            return window[: cut + len(pivot)].strip()
    return window.rstrip() + "…"


def _fact_candidates(text: str) -> list[str]:
    out: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if 12 <= len(line) <= 120 and not line.startswith("#"):
            out.append(line)
        if len(out) >= 6:
            break
    return out


def _loads(text: str) -> dict:
    import json

    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start: end + 1]
    return json.loads(raw)
