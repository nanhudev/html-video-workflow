"""Layered configuration: default < system < user < project < runtime."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .paths import settings_path

_CONFIG_ENV_PREFIX = "HVW_"


class RenderSettings(BaseModel):
    width: int = 1280
    height: int = 720
    fps: int = 30
    preset: str = "youtube_16x9"
    crf: int = 19
    video_bitrate_kbps: int = 6000
    audio_bitrate_kbps: int = 160


class AudioSettings(BaseModel):
    loudness_target_lufs: float = -16.0
    true_peak_dbtp: float = -1.5
    bgm_gain_db: float = -18.0
    ducking: bool = True
    #: Multiplier on every prosody pause. <1 reads faster and tenser.
    pause_scale: float = 1.0
    #: Narration sample rate to request. ``None`` lets the provider decide.
    narration_sample_rate: int | None = None
    #: Trim dead air from the head and tail of each narration clip.
    trim_silence: bool = True


class RoutingSettings(BaseModel):
    preset: str = "auto"  # auto | fast | balanced | high_quality | max_quality
    prefer_local: bool = True
    allow_api: bool = True
    locked_providers: dict[str, str] = Field(default_factory=dict)
    max_parallel_tasks: int = 2


class Settings(BaseModel):
    """User/system level configuration."""

    schema_version: int = 1
    render: RenderSettings = Field(default_factory=RenderSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    routing: RoutingSettings = Field(default_factory=RoutingSettings)
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    http: dict[str, Any] = Field(
        default_factory=lambda: {"host": "127.0.0.1", "port": 8787}
    )

    # ---------------------------------------------------------------- merge
    def merged_with(self, overrides: dict[str, Any]) -> "Settings":
        data = self.model_dump()
        _deep_merge(data, overrides or {})
        return Settings.model_validate(data)


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def default_settings() -> Settings:
    return Settings()


def load_settings() -> Settings:
    """Load persisted settings, layered over defaults and environment."""
    settings = Settings()
    path = settings_path()
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                settings = settings.merged_with(stored)
        except (json.JSONDecodeError, OSError):
            pass
    return _apply_env(settings)


def _apply_env(settings: Settings) -> Settings:
    overrides: dict[str, Any] = {}
    for key, value in os.environ.items():
        if not key.startswith(_CONFIG_ENV_PREFIX):
            continue
        suffix = key[len(_CONFIG_ENV_PREFIX) :].lower()
        if suffix in {"routing_preset"}:
            overrides.setdefault("routing", {})["preset"] = value
        elif suffix in {"width", "height", "fps"}:
            overrides.setdefault("render", {})[suffix] = int(value)
        elif suffix in {"allow_api", "prefer_local"}:
            overrides.setdefault("routing", {})[suffix] = value.lower() in {
                "1",
                "true",
                "yes",
            }
    return settings.merged_with(overrides) if overrides else settings


def save_settings(settings: Settings) -> Path:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


# ----------------------------------------------------------------- secrets
_SECRET_KEYS = (
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
    "HUGGINGFACE_TOKEN",
    "HF_TOKEN",
    "ELEVENLABS_API_KEY",
    "AZURE_SPEECH_KEY",
)


def load_env_file(path: Path | None = None) -> None:
    """Populate os.environ from a .env file without overwriting real env vars."""
    target = Path(path) if path else Path.cwd() / ".env"
    if not target.exists():
        return
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def mask_secret(value: str | None) -> str:
    """Mask a secret for display/logs: ``sk-****7a3``."""
    if not value:
        return ""
    if len(value) <= 7:
        return "*" * len(value)
    return f"{value[:3]}****{value[-3:]}"


def known_secrets() -> dict[str, str]:
    """Return masked view of recognised secret env vars."""
    return {key: mask_secret(os.environ.get(key)) for key in _SECRET_KEYS}
