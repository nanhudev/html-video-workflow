"""Template System V2 — what the video *is*, separate from how it *looks*.

**Template ≠ Style.** A template is the structure of the argument (how many
scenes, what each scene does, which layout carries it). A style is the skin
(palette, type, motion bias). The same template renders credibly in five
styles, and a style never changes the argument.

Manifests are JSON on disk and are written to be read by an *agent*: every
field answers a question a planner would otherwise have to guess.
"""
from __future__ import annotations

from .models import StyleProfile, TemplateManifest
from .ranker import RankedTemplate, TemplateRanker
from .registry import TemplateRegistry, get_registry

__all__ = [
    "RankedTemplate",
    "StyleProfile",
    "TemplateManifest",
    "TemplateRanker",
    "TemplateRegistry",
    "get_registry",
]
