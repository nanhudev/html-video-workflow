"""OpenAI-compatible LLM provider.

One implementation covers OpenAI, DeepSeek, OpenRouter, Ollama, llama.cpp
server, LM Studio, vLLM and any other OpenAI-compatible endpoint. The business
layer never learns which model is behind it — only which endpoint and which
capabilities.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from ...utils.logging import get_logger
from ..base import (  # noqa: E402
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProbeResult,
    ProbeState,
    ProviderError,
    ProviderSpec,
    ProviderTimeout,
)
from ..registry import register  # noqa: E402

log = get_logger("providers.llm.openai_compatible")

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or default


@register
class OpenAICompatibleProvider(LLMProvider):
    spec = ProviderSpec(
        id="openai_compatible",
        type="llm",
        name="OpenAI-compatible LLM",
        vendor="various",
        version="1.0.0",
        local=False,
        implementation="api",
        quality_score=8.0,
        speed_score=7.0,
        naturalness_score=7.5,
        startup_cost="low",
        install_state="optional",
        install_docs="Set OPENAI_BASE_URL / OPENAI_API_KEY (or DEEPSEEK_API_KEY).",
        tags=["api", "openai-compatible"],
    )

    # ------------------------------------------------------------- config
    def __init__(self) -> None:
        self.base_url = (
            _env("HVW_LLM_BASE_URL") or _env("OPENAI_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_key = _env("HVW_LLM_API_KEY") or _env("OPENAI_API_KEY") or _env(
            "DEEPSEEK_API_KEY"
        )
        self.model = _env("HVW_LLM_MODEL") or _env("OPENAI_MODEL") or DEFAULT_MODEL

    # ------------------------------------------------------------- probing
    def probe(self) -> ProbeResult:
        if not self.api_key:
            return ProbeResult(
                state=ProbeState.MISSING_CREDENTIALS,
                reason="No API key found (OPENAI_API_KEY / DEEPSEEK_API_KEY / HVW_LLM_API_KEY)",
                evidence={"base_url": self.base_url, "model": self.model},
            )
        started = time.perf_counter()
        try:
            request = urllib.request.Request(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
            models = [m.get("id") for m in payload.get("data", []) if isinstance(m, dict)]
        except urllib.error.HTTPError as exc:
            return ProbeResult(
                state=ProbeState.UNAVAILABLE,
                reason=f"Endpoint returned HTTP {exc.code}",
                evidence={"base_url": self.base_url},
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return ProbeResult(
                state=ProbeState.UNAVAILABLE,
                reason=f"Endpoint unreachable: {exc}",
                evidence={"base_url": self.base_url},
            )
        latency = int((time.perf_counter() - started) * 1000)
        return ProbeResult(
            state=ProbeState.READY,
            reason=f"Endpoint reachable, {len(models)} models listed",
            evidence={"base_url": self.base_url, "model": self.model,
                      "latency_ms": latency, "models": models[:20]},
        )

    # ----------------------------------------------------------- completion
    def complete(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise ProviderError(
                "LLM provider has no API key configured",
                provider=self.id,
                fallback="mock_llm",
            )
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": [],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.system:
            payload["messages"].append({"role": "system", "content": request.system})
        payload["messages"].append({"role": "user", "content": request.prompt})
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}

        http_request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(http_request, timeout=120) as response:
                raw = json.loads(response.read().decode("utf-8", "replace"))
        except TimeoutError as exc:
            raise ProviderTimeout("LLM request timed out", provider=self.id) from exc
        except urllib.error.HTTPError as exc:
            raise ProviderError(
                f"LLM endpoint returned HTTP {exc.code}: {exc.reason}",
                provider=self.id,
                fallback="mock_llm",
            ) from exc

        choices = raw.get("choices") or []
        text = ""
        if choices:
            message = choices[0].get("message") or {}
            text = message.get("content") or ""
        return LLMResponse(
            provider=self.id,
            text=text,
            model=raw.get("model") or payload["model"],
            usage=raw.get("usage", {}),
        )
