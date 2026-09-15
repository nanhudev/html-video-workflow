"""TopicPlanner — what should this video actually be *about*?

A prompt like "做个视频" is not a topic, and a 40-page source document is not a
topic either. This planner turns either into a small set of concrete, filmable
angles, and — crucially — works with **no model and no network**. When an LLM
*is* available it is used to widen the candidate set, never as a precondition.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..core.request import CreateVideoRequest
from ..sources.document import SourceDocument

#: Phrases that are instructions, not content. Stripping them is what turns
#: "帮我做一个视频，讲讲向量数据库" into the topic "向量数据库".
_PROMPT_NOISE = (
    "帮我做一个视频", "帮我做视频", "做一个视频", "做视频", "生成一个视频",
    "生成视频", "请制作", "请帮我", "我想要", "我想", "帮我", "请",
    "make a video about", "make a video", "create a video about",
    "create a video on", "generate a video about", "video about",
    "explain", "介绍", "讲讲", "讲一下", "关于",
)

_CONNECTORS = ("，", ",", "。", ".", "：", ":", "；", ";", "—", " then ", " and then ")


class TopicSuggestion(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str
    angle: str = ""
    rationale: str = ""
    video_type: str = "explainer"
    keywords: list[str] = Field(default_factory=list)
    score: float = 0.0
    source: str = "rule"


#: Angle templates. ``{t}`` is the cleaned topic. Each carries the video type it
#: pushes toward, so the template ranker gets a meaningful signal later.
_ANGLES: tuple[tuple[str, str, str, float], ...] = (
    ("为什么 {t} 值得你重新理解", "contrarian", "knowledge", 0.86),
    ("{t} 到底是怎么工作的", "mechanism", "explainer", 0.92),
    ("关于 {t}，三个常见误解", "mythbusting", "knowledge", 0.78),
    ("五分钟讲清 {t}", "primer", "tutorial", 0.74),
    ("{t}：从问题到解法", "problem_solution", "explainer", 0.80),
    ("{t} 的关键数字", "data", "data_story", 0.66),
    ("{t} 之后，下一步做什么", "forward", "essay", 0.58),
)


class TopicPlanner:
    """Derives and ranks candidate topics. Deterministic by default."""

    def __init__(self, llm_provider: Any | None = None) -> None:
        self._llm = llm_provider

    def use_provider(self, llm_provider: Any | None) -> None:
        """Attach the language model the router selected. See ScriptPlanner."""
        self._llm = llm_provider

    # ------------------------------------------------------------------ public
    def suggest(self, request: CreateVideoRequest,
                documents: list[SourceDocument] | None = None,
                count: int = 5) -> list[TopicSuggestion]:
        seed = self.seed(request, documents)
        if not seed:
            return []
        suggestions = [self._from_angle(seed, template, kind, video_type, base, index)
                       for index, (template, kind, video_type, base)
                       in enumerate(_ANGLES)]
        suggestions.sort(key=lambda item: item.score, reverse=True)
        # The user's own wording, unadorned, always stays in the running — an
        # angle template is a suggestion, not an improvement by default.
        suggestions.insert(0, TopicSuggestion(
            title=seed, angle="direct",
            rationale="直接使用用户给出的表述", video_type="explainer",
            keywords=_keywords(seed), score=1.0, source="user",
        ))
        return suggestions[: max(1, count)]

    def seed(self, request: CreateVideoRequest,
             documents: list[SourceDocument] | None = None) -> str:
        """The cleaned topic string every angle is built from."""
        if request.topic and request.topic.strip():
            return _clean_topic(request.topic)
        for doc in documents or []:
            if doc.title:
                return _clean_topic(doc.title)
            for heading in doc.headings:
                if heading and len(heading) > 3:
                    return _clean_topic(heading)
        if request.prompt:
            return _clean_topic(request.prompt)
        if request.script:
            return _clean_topic(request.script.splitlines()[0])
        if request.source:
            return _clean_topic(request.source.value)
        return ""

    def decide(self, request: CreateVideoRequest,
               documents: list[SourceDocument] | None = None) -> TopicSuggestion:
        """Pick one. With an explicit topic the choice is that topic; otherwise
        the highest-scoring angle wins, and the runner-ups stay inspectable."""
        seed = self.seed(request, documents)
        if not seed:
            return TopicSuggestion(title="未命名主题", score=0.0)
        if request.topic:
            return TopicSuggestion(
                title=_clean_topic(request.topic), angle="direct",
                rationale="用户在请求中显式指定", video_type="explainer",
                keywords=_keywords(seed), score=1.0, source="user",
            )
        return self.suggest(request, documents, count=1)[0]

    # --------------------------------------------------------------- internals
    def _from_angle(self, seed: str, template: str, kind: str,
                    video_type: str, base: float, index: int) -> TopicSuggestion:
        title = template.format(t=seed)
        score = base + _specificity(seed) - 0.01 * index
        return TopicSuggestion(
            title=title, angle=kind,
            rationale=_rationale(kind, seed), video_type=video_type,
            keywords=_keywords(seed), score=round(min(score, 0.99), 3),
            source="rule",
        )


def _clean_topic(text: str) -> str:
    value = (text or "").strip()
    for noise in sorted(_PROMPT_NOISE, key=len, reverse=True):
        if value.lower().startswith(noise.lower()):
            value = value[len(noise):].strip()
    # Cut trailing instructions: "讲讲 X，要中文，30 秒" -> "X"
    for connector in _CONNECTORS:
        if connector in value:
            head, _, tail = value.partition(connector)
            if len(head.strip()) >= 3 and not _looks_like_continuation(tail):
                value = head.strip()
                break
    value = re.sub(r"\s+", " ", value).strip(" ,.，。:：\"'")
    return value[:80] or "未命名主题"


_TAIL_CLAUSES = ("要", "时长", "秒", "分钟", "用中文", "中文", "英文", "配字幕",
                 "加字幕", "30", "60", "seconds", "minutes", "with captions")


def _looks_like_continuation(tail: str) -> bool:
    """A tail that is a *specification* should be dropped; a tail that is more
    topic must be kept."""
    tail = tail.strip()
    if not tail:
        return True
    return any(clause in tail for clause in _TAIL_CLAUSES) and len(tail) < 24


def _keywords(text: str) -> list[str]:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    tokens = [t for t in cleaned.split() if len(t) > 1]
    # Dedupe preserving order; long CJK runs are already meaningful as a whole.
    seen: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return seen[:8]


def _specificity(text: str) -> float:
    """Concrete topics beat vague ones. Numbers, proper nouns and length all
    count; '科技' is worth less than '向量数据库'."""
    score = 0.0
    if re.search(r"\d", text):
        score += 0.05
    if re.search(r"[A-Za-z]{3,}", text):
        score += 0.04
    length = len(text)
    if 6 <= length <= 40:
        score += 0.05
    elif length > 60:
        score -= 0.03
    return score


def _rationale(kind: str, seed: str) -> str:
    return {
        "contrarian": f"用一个反常识切入抓住前 5 秒，再回到 {seed} 本身",
        "mechanism": f"按机制讲 {seed}，适合没有先验知识的观众",
        "mythbusting": f"用纠错结构组织 {seed}，每点都能独立成段",
        "primer": f"{seed} 的入门版，控制术语密度",
        "problem_solution": f"先给问题再给 {seed}，动机最清楚",
        "data": f"以数字驱动 {seed} 的叙述，需要有可靠数据",
        "forward": f"把 {seed} 落到下一步行动，适合做结尾",
    }.get(kind, "")
