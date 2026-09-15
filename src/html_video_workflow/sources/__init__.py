"""Source ingestion: turn whatever the user has into readable documents.

The planners downstream never see a URL or a file handle — only
:class:`SourceDocument`. That is what lets the same storyboard code work for a
pasted paragraph, a Markdown file, a GitHub README and a web page.
"""
from __future__ import annotations

from .document import SourceDocument, SourceSection
from .providers import (
    SourceProvider,
    detect_kind,
    resolve_source,
    supported_kinds,
)

__all__ = [
    "SourceDocument",
    "SourceProvider",
    "SourceSection",
    "detect_kind",
    "resolve_source",
    "supported_kinds",
]
