"""Provider registry: register · discover · probe · select."""
from __future__ import annotations

import importlib
import threading
from typing import Any, Iterable

from ..utils.logging import get_logger
from .base import Capability, Provider, ProviderError, ProviderType

log = get_logger("providers.registry")

_LOCK = threading.RLock()
_REGISTRY: dict[str, Provider] = {}
_ENTRY_POINTS_GROUP = "html_video_workflow.providers"

#: module name -> "TypeError: ..." for every builtin that failed to import.
_LOAD_FAILURES: dict[str, str] = {}
_LOADED = False

#: Built-in provider modules imported during discovery.
BUILTIN_MODULES: tuple[str, ...] = (
    "html_video_workflow.providers.llm.openai_compatible",
    "html_video_workflow.providers.llm.mock_llm",
    "html_video_workflow.providers.tts.sapi",
    "html_video_workflow.providers.tts.moss",
    "html_video_workflow.providers.tts.mock_tts",
    "html_video_workflow.providers.tts.aivisspeech",
    "html_video_workflow.providers.tts.neural_sidecar",
    "html_video_workflow.providers.tts.openai_compatible_tts",
    "html_video_workflow.providers.renderer.legacy_html",
    "html_video_workflow.providers.renderer.advanced_html",
    "html_video_workflow.providers.renderer.mock_renderer",
    "html_video_workflow.providers.media.local_asset",
    "html_video_workflow.providers.subtitle.srt_writer",
)


class register:  # noqa: N801 - decorator reads better lowercase
    """Class decorator that registers a provider instance."""

    def __init__(self, cls: type[Provider]) -> None:
        if not issubclass(cls, Provider):
            raise TypeError(f"{cls!r} is not a Provider subclass")
        self.instance = cls()
        register_provider(self.instance)

    def __call__(self, *args: Any, **kwargs: Any) -> Provider:
        return self.instance


def register_provider(provider: Provider) -> Provider:
    with _LOCK:
        existing = _REGISTRY.get(provider.id)
        if existing is not None and existing is not provider:
            log.warning("provider id %s replaced by %s", provider.id, type(provider).__name__)
        _REGISTRY[provider.id] = provider
    return provider


def load_failures() -> dict[str, str]:
    """Builtin modules that failed to import. Surfaced by `doctor` and tests.

    A silently swallowed import error is how an entire provider domain vanishes
    without anyone noticing, so this list is part of the public surface.
    """
    ensure_loaded()
    return dict(_LOAD_FAILURES)


def discover_builtins() -> None:
    """Import built-in provider modules so their decorators run.

    Failures are recorded in `_LOAD_FAILURES` *and* logged at error level, then
    swallowed: a broken optional provider must not take down the registry. Use
    `load_failures()` when you need certainty.
    """
    for module_name in BUILTIN_MODULES:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            # A module that is simply absent is a planned provider, not a
            # failure. Recording it as a hard error would make the load-failure
            # list cry wolf and hide the genuine import breakages it exists for.
            if exc.name and exc.name.startswith("html_video_workflow."):
                log.debug("optional provider module not present: %s", module_name)
                continue
            _LOAD_FAILURES[module_name] = f"{type(exc).__name__}: {exc}"
            log.error("failed to import provider module %s: %s", module_name, exc)
        except Exception as exc:  # noqa: BLE001 - recorded, then reported
            _LOAD_FAILURES[module_name] = f"{type(exc).__name__}: {exc}"
            log.error("failed to import provider module %s: %s", module_name, exc)


def discover_entry_points() -> None:  # pragma: no cover - depends on installs
    """Load third-party providers advertised through entry points."""
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover
        return
    try:
        selected = entry_points(group=_ENTRY_POINTS_GROUP)
    except Exception:
        return
    for entry in selected:
        try:
            obj = entry.load()
            provider = obj() if isinstance(obj, type) else obj
            register_provider(provider)
        except Exception as exc:
            _LOAD_FAILURES[f"entry_point:{entry.name}"] = f"{type(exc).__name__}: {exc}"
            log.error("failed to load provider entry point %s: %s", entry.name, exc)


def ensure_loaded(force: bool = False) -> None:
    """Import builtins exactly once per process.

    Guarding on `_LOADED` rather than `if not _REGISTRY` is load-bearing: the
    mock/renderer modules are plain `import`s, so once Python caches them their
    `@register` decorators never run again. A `clear()` followed by a
    registry-empty check would silently leave the registry empty forever.
    """
    global _LOADED
    if force:
        _LOADED = False
        _LOAD_FAILURES.clear()
    if not _LOADED:
        _LOADED = True
        discover_builtins()
        discover_entry_points()


def get(provider_id: str) -> Provider:
    ensure_loaded()
    try:
        return _REGISTRY[provider_id]
    except KeyError as exc:
        raise ProviderError(f"Unknown provider: {provider_id}") from exc


def all_providers() -> list[Provider]:
    ensure_loaded()
    return list(_REGISTRY.values())


def by_type(provider_type: ProviderType | str) -> list[Provider]:
    wanted = ProviderType(provider_type)
    return [p for p in all_providers() if p.type == wanted]


def by_ids(ids: Iterable[str]) -> list[Provider]:
    return [get(pid) for pid in ids if pid in _REGISTRY]


def capabilities(refresh: bool = False) -> list[Capability]:
    """Probe every provider. Callers get honest states, never 'ready' by default."""
    ensure_loaded()
    result: list[Capability] = []
    for provider in all_providers():
        try:
            result.append(provider.capabilities())
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("capability probe failed for %s: %s", provider.id, exc)
            result.append(
                Capability(
                    id=provider.id,
                    type=provider.type,
                    available=False,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
    return result


def available(provider_type: ProviderType | str) -> list[Provider]:
    return [p for p in by_type(provider_type) if p.probe().available]


def clear() -> None:
    with _LOCK:
        _REGISTRY.clear()
