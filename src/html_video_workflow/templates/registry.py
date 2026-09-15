"""Registry for templates and styles.

Manifests are JSON on disk rather than Python, deliberately: an agent can read
``templates/builtins/*.json`` directly to decide which structure fits, and a
user can drop a new one into ``$HVW_HOME/templates`` without writing code.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterable

from ..utils.logging import get_logger
from .models import StyleProfile, TemplateManifest

log = get_logger("templates.registry")

_BUILTIN_DIR = Path(__file__).parent / "builtins"
_STYLES_FILE = _BUILTIN_DIR / "styles.json"


class RegistryError(RuntimeError):
    pass


def _user_template_dir() -> Path:
    from ..config.paths import hv_home

    return hv_home() / "templates"


class TemplateRegistry:
    """Holds every known template and style, built-in plus user-supplied."""

    def __init__(self) -> None:
        self._templates: dict[str, TemplateManifest] = {}
        self._styles: dict[str, StyleProfile] = {}
        self._errors: dict[str, str] = {}
        self.reload()

    # ------------------------------------------------------------------ loading
    def reload(self) -> None:
        self._templates.clear()
        self._styles.clear()
        self._errors.clear()
        for path in sorted(_BUILTIN_DIR.glob("*.json")):
            if path.name == _STYLES_FILE.name:
                continue
            self._load_template(path)
        self._load_styles(_STYLES_FILE)
        user_dir = _user_template_dir()
        if user_dir.is_dir():
            for path in sorted(user_dir.glob("*.json")):
                if path.name == _STYLES_FILE.name:
                    self._load_styles(path)
                else:
                    self._load_template(path)

    def _load_template(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._errors[str(path)] = f"{type(exc).__name__}: {exc}"
            log.error("bad template manifest %s: %s", path, exc)
            return
        try:
            manifest = TemplateManifest.model_validate(data)
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            self._errors[str(path)] = f"{type(exc).__name__}: {exc}"
            log.error("invalid template manifest %s: %s", path, exc)
            return
        self._templates[manifest.id] = manifest

    def _load_styles(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._errors[str(path)] = f"{type(exc).__name__}: {exc}"
            log.error("bad style file %s: %s", path, exc)
            return
        for item in payload if isinstance(payload, list) else [payload]:
            try:
                style = StyleProfile.model_validate(item)
            except Exception as exc:  # noqa: BLE001
                self._errors[f"{path}:{item.get('id', '?')}"] = f"{type(exc).__name__}: {exc}"
                log.error("invalid style in %s: %s", path, exc)
                continue
            self._styles[style.id] = style

    # ------------------------------------------------------------------ reading
    def templates(self) -> list[TemplateManifest]:
        return list(self._templates.values())

    def styles(self) -> list[StyleProfile]:
        return list(self._styles.values())

    def get(self, template_id: str) -> TemplateManifest:
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise RegistryError(
                f"unknown template: {template_id} "
                f"(known: {', '.join(sorted(self._templates)) or 'none'})"
            ) from exc

    def find(self, template_id: str | None) -> TemplateManifest | None:
        return self._templates.get(template_id) if template_id else None

    def style(self, style_id: str) -> StyleProfile:
        try:
            return self._styles[style_id]
        except KeyError as exc:
            raise RegistryError(
                f"unknown style: {style_id} "
                f"(known: {', '.join(sorted(self._styles)) or 'none'})"
            ) from exc

    def find_style(self, style_id: str | None) -> StyleProfile | None:
        return self._styles.get(style_id) if style_id else None

    def default_template(self) -> TemplateManifest:
        return self._templates.get("editorial_argument") or self.templates()[0]

    def default_style(self) -> StyleProfile:
        return self._styles.get("editorial") or self.styles()[0]

    def styles_for(self, manifest: TemplateManifest) -> list[StyleProfile]:
        wanted: Iterable[str] = manifest.compatible_styles or [manifest.default_style]
        picked = [self._styles[sid] for sid in wanted if sid in self._styles]
        return picked or [self.default_style()]

    def load_errors(self) -> dict[str, str]:
        """Manifests/styles that failed to parse. Surfaced by `doctor`."""
        return dict(self._errors)


_registry: TemplateRegistry | None = None
_lock = threading.RLock()


def get_registry(refresh: bool = False) -> TemplateRegistry:
    global _registry
    with _lock:
        if _registry is None:
            _registry = TemplateRegistry()
        elif refresh:
            _registry.reload()
        return _registry
