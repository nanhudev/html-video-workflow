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
from .models import StyleProfile, TemplateManifest, WritingPreset

log = get_logger("templates.registry")

_BUILTIN_DIR = Path(__file__).parent / "builtins"
_STYLES_FILE = _BUILTIN_DIR / "styles.json"
#: Sibling manifests that share the ``*.json`` glob but are not templates.
#: Without this, adding a new file type to the directory silently registers it
#: as a template and the registry reports a validation error nobody reads.
_NON_TEMPLATE_FILES = {"styles.json", "presets.json"}


class RegistryError(RuntimeError):
    pass


def _user_template_dir() -> Path:
    from ..config.paths import hv_home

    return hv_home() / "templates"


class TemplateRegistry:
    """Holds every known template and style, built-in plus user-supplied.

    Writing presets live here as well, and their ids are a **separate
    namespace** from template ids. ``data_story`` deliberately exists in both:
    the preset ("数据解读") is *how the narration is written*, the template
    ("Data Story") is *what the video is made of*, and the first recommends the
    second. Nothing may look a preset up in the template table or the reverse —
    they are different questions that happen to share a vocabulary.
    """

    def __init__(self) -> None:
        self._templates: dict[str, TemplateManifest] = {}
        self._styles: dict[str, StyleProfile] = {}
        self._presets: dict[str, WritingPreset] = {}
        self._errors: dict[str, str] = {}
        self.reload()

    # ------------------------------------------------------------------ loading
    def reload(self) -> None:
        self._templates.clear()
        self._styles.clear()
        self._presets.clear()
        self._errors.clear()
        for path in sorted(_BUILTIN_DIR.glob("*.json")):
            if path.name in _NON_TEMPLATE_FILES:
                continue
            self._load_template(path)
        self._load_styles(_STYLES_FILE)
        self._load_presets(_BUILTIN_DIR / "presets.json")
        user_dir = _user_template_dir()
        if user_dir.is_dir():
            for path in sorted(user_dir.glob("*.json")):
                # A user file may replace styles or presets wholesale; anything
                # else is treated as a template. Same rule as the builtins, so
                # "drop a JSON in the folder" means one thing, not two.
                if path.name == _STYLES_FILE.name:
                    self._load_styles(path)
                elif path.name == "presets.json":
                    self._load_presets(path)
                else:
                    self._load_template(path)

    def _load_presets(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._errors[str(path)] = f"{type(exc).__name__}: {exc}"
            log.error("bad preset file %s: %s", path, exc)
            return
        for item in payload if isinstance(payload, list) else [payload]:
            try:
                preset = WritingPreset.model_validate(item)
            except Exception as exc:  # noqa: BLE001 - reported, never swallowed
                self._errors[f"{path}:{item.get('id', '?')}"] = f"{type(exc).__name__}: {exc}"
                log.error("invalid preset in %s: %s", path, exc)
                continue
            self._presets[preset.id] = preset

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

    def presets(self) -> list[WritingPreset]:
        return list(self._presets.values())

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

    def preset(self, preset_id: str) -> WritingPreset:
        try:
            return self._presets[preset_id]
        except KeyError as exc:
            raise RegistryError(
                f"unknown writing preset: {preset_id} "
                f"(known: {', '.join(sorted(self._presets)) or 'none'})"
            ) from exc

    def find_preset(self, preset_id: str | None) -> WritingPreset | None:
        return self._presets.get(preset_id) if preset_id else None

    def default_preset(self) -> WritingPreset:
        return self._presets.get("popular_science") or self.presets()[0]

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
