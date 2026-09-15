"""Writing presets — how the narration should read.

A **template** answers *what the video is made of* (beats, layouts, scene
count). A **preset** answers *how it is written* (who is talking, to whom, in
what tone, under which constraints). They are separate because "教程步骤 in
blueprint colours" should be a combination, not a ninth JSON file.

What a preset actually changes, in order of how much the user notices:

1. the recommended template / style / duration / scene count (filled into the
   wizard's defaults, always overridable by the request);
2. the system prompt handed to a language model, when one is configured.

Point 2 is the reason this module exists. The rule-based writer is
deterministic and cannot be briefed — pretending otherwise would be the kind of
silent no-op this codebase exists to avoid, so the UI says so out loud.
"""
from __future__ import annotations

from collections.abc import Iterable

from ..templates.models import WritingPreset

#: Restated rather than imported from the planner, deliberately: the planner's
#: parser and this contract are two halves of one agreement, and they should be
#: read side by side. Importing it would let one drift from the other unnoticed.
JSON_CONTRACT = (
    "只返回 JSON，不要任何解释文字，不要 Markdown 代码块标记。格式必须是：\n"
    '{"beats":[{"kind":"...","label":"...","headline":"...","narration":"..."}]}'
)

_LANGUAGE_NAMES = {
    "zh": "简体中文",
    "en": "English",
    "ja": "日本語",
}


def language_name(language: str | None) -> str:
    key = (language or "zh")[:2].lower()
    return _LANGUAGE_NAMES.get(key, _LANGUAGE_NAMES["zh"])


def compose_system_prompt(
    preset: WritingPreset | None,
    *,
    language: str = "zh-CN",
    custom: str | None = None,
    kinds: Iterable[tuple[str, str]] = (),
    max_chars: int | None = None,
    headline_chars: int = 18,
) -> str:
    """Build the system prompt for one script request.

    The structural rules at the bottom are not negotiable by a preset or by a
    user's custom text. They are what the parser and the renderer rely on; a
    prompt that talks the model out of them turns a good request into a
    fallback.
    """
    lines: list[str] = []

    persona = (preset.persona if preset else "") or (
        "你是一位专业的短视频撰稿人，擅长把复杂的事讲清楚。"
    )
    lines.append(persona)

    rules: list[str] = list(preset.rules) if preset else []
    if rules:
        lines.append("")
        lines.append("写作规则：")
        lines.extend(f"{index}. {rule}" for index, rule in enumerate(rules, start=1))

    if custom and custom.strip():
        lines.append("")
        lines.append("本次的额外要求（优先级高于上面的通用规则）：")
        lines.append(custom.strip())

    lines.append("")
    lines.append("结构性要求（必须遵守，不能因为风格要求而放宽）：")
    lines.append(f"1. 所有文案使用{language_name(language)}书写，不要混用其他语言。")
    if kinds:
        listing = "、".join(f"{kind}（{label}）" for kind, label in kinds)
        lines.append(
            f"2. 本次视频按以下节拍顺序展开，每个节拍一个 beat：{listing}。"
            "kind 必须从这个列表里原样选择，不要新增或改名。"
        )
    if max_chars:
        lines.append(
            f"3. narration 是念出来的旁白，单个 beat 不超过 {max_chars} 个字，"
            "长度要均匀，不要一段特别长一段特别短。"
        )
    lines.append(
        f"4. headline 是屏幕上的大字，不超过 {headline_chars} 个字，"
        "不要用句号结句；label 是分类标签，不超过 8 个字。"
    )
    lines.append(
        "5. 旁白是口语稿：不要出现 Markdown、星号、括号、书名号、emoji、换行符，"
        "不要念标题序号。"
    )
    lines.append(
        "6. 不要编造具体数字、人名、机构名、时间。材料里没有的事实，"
        "改用定性表达或明确标注为推测。"
    )
    lines.append("")
    lines.append(JSON_CONTRACT)
    return "\n".join(lines)


def resolve_preset(preset_id: str | None) -> WritingPreset | None:
    """Look up a preset by id, returning ``None`` for "no preset".

    An unknown id is *not* silently swapped for the default: the caller asked
    for something specific, and answering with a different thing while claiming
    success is how a product loses a user's trust. The API surfaces the error.
    """
    if not preset_id:
        return None
    from ..templates.registry import get_registry

    registry = get_registry()
    if preset_id not in {preset.id for preset in registry.presets()}:
        from ..templates.registry import RegistryError

        raise RegistryError(
            f"unknown writing preset: {preset_id} "
            f"(known: {', '.join(sorted(p.id for p in registry.presets())) or 'none'})"
        )
    return registry.find_preset(preset_id)
