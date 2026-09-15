"""Setup endpoints — the wizard's first two steps.

Two questions a non-technical user actually has before pressing 生成:

1. *will it work on this machine?* — answered by real probes, never by hope;
2. *do I need an API key, and is mine any good?* — answered by writing the key
   and then **calling the endpoint**, because "saved" and "works" are different
   facts and only one of them is worth a green tick.

Everything here degrades to a readable sentence plus a fix instruction. A
self-check that says "ffmpeg: not found" without saying "install it like this"
is a log line, not a user interface.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ... import __version__
from ...config.paths import hv_home, outputs_dir
from ...config.settings import (
    apply_llm_credentials,
    known_secrets,
    load_settings,
    reload_providers,
)
from ...hardware.profile import probe_hardware
from ...providers.registry import capabilities, get as get_provider

router = APIRouter(prefix="/v1/setup", tags=["setup"])

#: Chinese labels for the probe states, so the UI never shows a raw enum.
_STATE_ZH = {
    "ready": "就绪",
    "not_installed": "未安装",
    "unavailable": "不可用",
    "missing_credentials": "缺少密钥",
    "error": "出错",
}

_LLM_PROVIDER = "openai_compatible"
_TTS_PROVIDER = "sapi"
_RENDERERS = ("advanced_html", "legacy_html")


class LlmCredentials(BaseModel):
    api_key: str | None = Field(default=None, description="空字符串表示清除")
    base_url: str | None = None
    model: str | None = None


def _item(item_id: str, label: str, state: str, detail: str, *,
          fix: str = "", required: bool = True) -> dict[str, Any]:
    return {
        "id": item_id,
        "label": label,
        "state": state,
        "state_label": _STATE_ZH.get(state, state),
        "detail": detail,
        "fix": fix,
        "required": required,
    }


def _capability_rows() -> dict[str, Any]:
    return {row.id: row for row in capabilities()}


def _tools() -> dict[str, Any]:
    from dataclasses import asdict

    rows = probe_hardware().tooling or {}
    return {name: (asdict(tool) if hasattr(tool, "__dataclass_fields__") else tool)
            for name, tool in rows.items()}


def _check_items() -> list[dict[str, Any]]:
    """The checklist, derived from probes run just now."""
    rows = _capability_rows()
    tools = _tools()
    items: list[dict[str, Any]] = []

    ffmpeg = tools.get("ffmpeg") or {}
    ffprobe = tools.get("ffprobe") or {}
    for tool_id, tool, name in (("ffmpeg", ffmpeg, "视频合成 FFmpeg"),
                                ("ffprobe", ffprobe, "视频检测 FFprobe")):
        available = bool(tool.get("available"))
        items.append(_item(
            tool_id, name,
            "ready" if available else "not_installed",
            f"找到可执行文件：{tool.get('path')}" if available
            else "没有找到这个程序，无法合成视频",
            fix=("" if available else
                 "安装 FFmpeg 后重启本程序：Windows 可用 winget install Gyan.FFmpeg，"
                 "或从 ffmpeg.org 下载压缩包，把 bin 目录加入 PATH"),
        ))

    renderer_id = next((rid for rid in _RENDERERS
                        if rows.get(rid) and rows[rid].available), None)
    renderer = rows.get(renderer_id) if renderer_id else None
    items.append(_item(
        "renderer", "画面渲染（浏览器内核）",
        "ready" if renderer else "unavailable",
        f"使用 {renderer_id}，基于系统自带浏览器内核截图" if renderer
        else "没有可用的渲染器，需要系统安装 Microsoft Edge 或 Google Chrome",
        fix="" if renderer else "安装 Microsoft Edge（Windows 10/11 通常已自带）后重启本程序",
    ))

    tts = rows.get(_TTS_PROVIDER)
    # Ask the provider for its voices rather than reading ``Capability.voices``:
    # that field is only ever filled by the provider's own ``list_voices()``,
    # while the generic path puts a *count* in ``details``. Reporting "no
    # Chinese voice" because a field was never populated would send the user off
    # to install a language pack they already have — a false negative is the
    # same class of error as a false positive, just quieter.
    voices = []
    if tts is not None and tts.available:
        try:
            voices = list(get_provider(_TTS_PROVIDER).list_voices() or [])
        except Exception:  # noqa: BLE001 - reported as "could not enumerate"
            voices = []
    zh_voice = next((v for v in voices
                     if str(getattr(v, "language", "") or "").lower().startswith("zh")),
                    None)
    languages = sorted({str(getattr(v, "language", "")) for v in voices if
                        getattr(v, "language", None)})
    items.append(_item(
        "voice", "语音合成（配音）",
        "ready" if zh_voice else ("unavailable" if tts and tts.available else "not_installed"),
        (f"找到中文语音：{zh_voice.name}" if zh_voice else
         (f"系统语音可用，但没有中文音色（现有：{'、'.join(languages) or '未知'}）"
          if tts and tts.available and voices else
          ("系统语音可用，但未能列出音色，请打开高级页面查看" if tts and tts.available
           else "没有找到可用的语音引擎，视频将没有声音"))),
        fix=("" if zh_voice else
             "Windows：设置 → 时间和语言 → 语言和区域 → 中文(简体) → 语言选项 → "
             "添加语音包（语音），然后重启本程序"),
    ))

    settings = load_settings()
    home = hv_home()
    try:
        home.mkdir(parents=True, exist_ok=True)
        probe = home / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        writable = True
    except OSError:
        writable = False
    items.append(_item(
        "storage", "数据目录可写",
        "ready" if writable else "unavailable",
        f"作品与缓存将存放于 {home}" if writable else f"无法写入 {home}",
        fix="" if writable else "换一个可写的位置：设置环境变量 HVW_HOME 指向你有权限的磁盘目录",
    ))

    profile = probe_hardware()
    free_mb = profile.disk_free_mb
    if free_mb is not None:
        enough = free_mb >= 2048
        items.append(_item(
            "disk", "磁盘剩余空间",
            "ready" if enough else "unavailable",
            f"剩余约 {free_mb / 1024:.1f} GB 可用",
            fix="" if enough else "清理磁盘空间，一分钟的视频大约需要 1-2 GB 临时空间",
        ))

    settings_preset = settings.routing.preset
    items.append(_item(
        "routing", "运行档位",
        "ready",
        f"当前档位 {settings_preset}（在设置里可以改成 fast 以加快速度）",
        required=False,
    ))
    return items


def _llm_status() -> dict[str, Any]:
    """The honest state of the text-generation provider."""
    password = known_secrets()
    try:
        provider = get_provider(_LLM_PROVIDER)
        probe = provider.probe()
        state = probe.state.value if hasattr(probe.state, "value") else str(probe.state)
        reason = probe.reason
        evidence = probe.evidence or {}
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        state, reason, evidence = "error", f"{type(exc).__name__}: {exc}", {}

    return {
        "provider": _LLM_PROVIDER,
        "state": state,
        "state_label": _STATE_ZH.get(state, state),
        "configured": state == "ready",
        "reason": reason,
        # Prefer what the provider itself reports, but fall back to what is
        # configured. A probe that cannot reach the endpoint knows nothing about
        # the address, and echoing that ignorance as an empty field makes a
        # successful save look like it did not take — the user then retypes a
        # URL that was stored correctly all along.
        "base_url": evidence.get("base_url") or os.environ.get("HVW_LLM_BASE_URL", ""),
        "model": evidence.get("model") or os.environ.get("HVW_LLM_MODEL", ""),
        "masked_key": password.get("OPENAI_API_KEY", ""),
        # Deliberately stated in the payload: a user who skips this step should
        # know what they are getting, not discover it in the finished video.
        "offline_effect": "不填也能用：文案由内置模板生成，画面、配音、字幕都是真的。",
    }


@router.get("/status")
def setup_status() -> dict[str, Any]:
    """Everything step 1 needs, from live probes."""
    items = _check_items()
    blocking = [row["id"] for row in items
                if row["required"] and row["state"] != "ready"]
    outputs = outputs_dir()
    return {
        "version": __version__,
        "home": str(hv_home()),
        "outputs": str(outputs),
        "ready": not blocking,
        "blocking": blocking,
        "items": items,
        "llm": _llm_status(),
    }


@router.post("/llm")
def save_llm(payload: LlmCredentials) -> dict[str, Any]:
    """Persist the key, rebuild the providers, then *actually try it*.

    Saving and working are reported separately on purpose. A wrong key that is
    stored successfully is still a broken configuration, and the response says
    so instead of returning a tick the user will only get to distrust later.
    """
    clearing = payload.api_key is not None and not payload.api_key.strip()
    if clearing and payload.base_url is None and payload.model is None:
        # `None` means "leave this alone" everywhere in `apply_llm_credentials`,
        # so clearing has to be spelled as the empty string — the value that
        # means "set this to nothing". Passing `None` here stored a key and then
        # reported that it had been removed.
        summary = apply_llm_credentials(api_key="")
        reload_providers()
        return {"saved": True, "cleared": True, "summary": summary,
                "llm": _llm_status()}

    if payload.api_key is not None and not payload.api_key.strip():
        raise HTTPException(status_code=400, detail="API Key 不能为空")

    summary = apply_llm_credentials(
        api_key=payload.api_key,
        base_url=payload.base_url,
        model=payload.model,
    )
    reload_providers()
    status = _llm_status()
    status["saved"] = True
    status["summary"] = summary
    return status


@router.post("/llm/test")
def test_llm(payload: LlmCredentials) -> dict[str, Any]:
    """Try the credentials without keeping them.

    Restores the previous environment afterwards, including on failure — a
    "test" that silently becomes a "save" is the kind of surprise that makes
    people stop trusting buttons.
    """
    from ...config.settings import LLM_ENV_KEYS

    before = {key: os.environ.get(key) for key in LLM_ENV_KEYS}
    try:
        apply_llm_credentials(
            api_key=payload.api_key,
            base_url=payload.base_url,
            model=payload.model,
            persist=False,
        )
        reload_providers()
        return _llm_status()
    finally:
        for env_key, value in before.items():
            if value is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = value
        reload_providers()
