"""Legacy compatibility layer for ``scripts/workflow.py``."""
from .adapter import (
    gallery_legacy,
    legacy_templates,
    legacy_validate,
    load_legacy_module,
    render_legacy,
    research_legacy,
)

__all__ = [
    "gallery_legacy",
    "legacy_templates",
    "legacy_validate",
    "load_legacy_module",
    "render_legacy",
    "research_legacy",
]
