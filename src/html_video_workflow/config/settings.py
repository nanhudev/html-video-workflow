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
    """Populate os.environ from .env without overwriting real environment vars.

    Two locations are read when no explicit path is given. ``./.env`` keeps the
    original behaviour for a source checkout, and ``$HVW_HOME/.env`` is what the
    wizard writes to — a packaged build is launched from an arbitrary working
    directory (and sometimes from a shortcut whose "start in" is C:\\Windows),
    so storing a key relative to the CWD would lose it on the next launch.
    The working directory is read first, so a project-local file still wins.
    """
    targets = [Path(path)] if path else env_file_paths()
    for target in targets:
        _load_one_env_file(target)


def env_file_paths() -> list[Path]:
    """Where configuration is read from, most specific first."""
    from .paths import hv_home

    paths = [Path.cwd() / ".env"]
    try:
        paths.append(hv_home() / ".env")
    except Exception:  # noqa: BLE001 - an unwritable home must not break loading
        pass
    return paths


def app_env_file() -> Path:
    """The file the app itself writes secrets to."""
    from .paths import hv_home

    return hv_home() / ".env"


def _load_one_env_file(target: Path) -> None:
    if not target.exists():
        return
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:  # pragma: no cover - unreadable file is not fatal
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def write_env_values(values: dict[str, str | None], path: Path | None = None) -> Path:
    """Merge ``values`` into the app's .env, preserving unrelated lines.

    ``None`` removes the key. Rewriting the whole file would be simpler and
    would also delete every other secret the user ever set, so it is not done.
    """
    target = Path(path) if path else app_env_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    kept: list[str] = []
    if target.exists():
        try:
            kept = target.read_text(encoding="utf-8").splitlines()
        except OSError:
            kept = []

    remaining = dict(values)
    out: list[str] = []
    for line in kept:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in remaining:
                value = remaining.pop(key)
                if value is None:
                    continue
                out.append(f"{key}={value}")
                continue
        out.append(line)

    for key, value in remaining.items():
        if value is not None:
            out.append(f"{key}={value}")

    target.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    try:
        # Best effort: on Windows this is a no-op, on POSIX it is the difference
        # between a secret and a world-readable file.
        os.chmod(target, 0o600)
    except OSError:  # pragma: no cover
        pass
    return target


#: The environment variables the wizard writes. ``HVW_*`` wins over the vendor
#: names in the provider, so writing these three is enough to reconfigure it.
LLM_ENV_KEYS = ("HVW_LLM_API_KEY", "HVW_LLM_BASE_URL", "HVW_LLM_MODEL")
VENDOR_ENV_KEYS = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL")


def apply_llm_credentials(
    *,
    api_key: str | None,
    base_url: str | None = None,
    model: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Set the LLM credentials for this process, and optionally on disk.

    Returns a summary that never contains the key itself. The caller is
    responsible for re-probing: writing a key is not the same as the key
    working, and this function does not pretend to know which one happened.
    """
    values: dict[str, str | None] = {}
    if api_key is not None:
        key = api_key.strip()
        values["HVW_LLM_API_KEY"] = key or None
        # Also written under the vendor name so the untouched legacy script and
        # any third-party tool that reads OPENAI_API_KEY keep working.
        values["OPENAI_API_KEY"] = key or None
    if base_url is not None:
        url = base_url.strip()
        values["HVW_LLM_BASE_URL"] = url or None
        values["OPENAI_BASE_URL"] = url or None
    if model is not None:
        name = model.strip()
        values["HVW_LLM_MODEL"] = name or None
        values["OPENAI_MODEL"] = name or None

    for env_key, value in values.items():
        if value is None:
            os.environ.pop(env_key, None)
        else:
            os.environ[env_key] = value

    written: Path | None = None
    if persist:
        written = write_env_values(values)

    return {
        "base_url": os.environ.get("HVW_LLM_BASE_URL") or "",
        "model": os.environ.get("HVW_LLM_MODEL") or "",
        "masked_key": mask_secret(os.environ.get("HVW_LLM_API_KEY")),
        "has_key": bool(os.environ.get("HVW_LLM_API_KEY")),
        "env_file": str(written) if written else None,
    }


def reload_providers() -> int:
    """Rebuild every provider instance so new credentials take effect.

    Provider objects read the environment in ``__init__``, so a registry that
    is not rebuilt keeps serving the old answer — a saved key that only starts
    working after a restart is a bug report waiting to happen.

    Rebuilding means *re-instantiating the registered classes*, never clearing
    and re-importing: provider modules are already in ``sys.modules``, so their
    ``@register`` decorators would not run again and the registry would come back
    empty. That failure is silent, which makes it the worst kind — it takes out
    every provider at the exact moment the user is being told their key was
    accepted. The count is therefore checked, not assumed.
    """
    from ..providers.registry import all_providers, rebuild_instances
    from ..utils.logging import get_logger

    before = {provider.id for provider in all_providers()}
    built = rebuild_instances()
    after = {provider.id for provider in all_providers()}
    lost = before - after
    if lost:
        get_logger("config.settings").error(
            "reloading providers lost %d of them: %s",
            len(lost), ", ".join(sorted(lost)))
    return built



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
