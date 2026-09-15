"""Source providers — one per shape of input.

Network access is optional and always fail-soft at the *call site*: a timeout is
reported as ``SOURCE_UNREADABLE`` by the Runtime, never as an empty document
that quietly produces a video about nothing.
"""
from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterable

from ..core.request import SourceInput
from .document import SourceDocument, SourceKind, SourceSection

DEFAULT_TIMEOUT = 12
_UA = "html-video-workflow/0.3 (+local-first video runtime)"

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+(.*)$")
_TAG = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.S | re.I)
_HTML_TAG = re.compile(r"<[^>]+>")
_ENTITY = {
    "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&quot;": '"', "&#39;": "'", "&mdash;": "—", "&hellip;": "…",
}
_WS = re.compile(r"[ \t\u00a0]+")
_BLANKS = re.compile(r"\n{3,}")

_TEXT_SUFFIX = {".md", ".markdown", ".txt", ".text", ".rst", ".json", ".yaml", ".yml"}


# --------------------------------------------------------------------- helpers
def _clean(text: str) -> str:
    for entity, char in _ENTITY.items():
        text = text.replace(entity, char)
    text = _WS.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    return _BLANKS.sub("\n\n", text).strip()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _doc_id(prefix: str, seed: str) -> str:
    return f"{prefix}_{hashlib.sha1(seed.encode('utf-8', 'replace')).hexdigest()[:10]}"


def _clip(text: str, max_chars: int) -> tuple[str, bool]:
    """Cut on a sentence/line boundary rather than mid-word."""
    if len(text) <= max_chars:
        return text, False
    window = text[:max_chars]
    for pivot in ("\n\n", "。", ". ", "\n"):
        cut = window.rfind(pivot)
        if cut > max_chars * 0.6:
            return window[:cut].rstrip(), True
    return window.rstrip(), True


def _parse_markdown(text: str) -> tuple[list[SourceSection], list[str], str | None]:
    sections: list[SourceSection] = []
    facts: list[str] = []
    title: str | None = None
    current: SourceSection | None = None
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            label = heading.group(2).strip()
            if title is None and level == 1:
                title = label
            current = SourceSection(heading=label, level=level)
            sections.append(current)
            continue
        bullet = _BULLET.match(line)
        if bullet:
            item = bullet.group(1).strip()
            if 4 <= len(item) <= 160:
                facts.append(item)
            if current is not None:
                current.text += item + "\n"
            continue
        if line.strip():
            if current is None:
                current = SourceSection()
                sections.append(current)
            current.text += line.strip() + "\n"
    for section in sections:
        section.text = section.text.strip()
    return sections, facts, title


def _http_get(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def _html_to_text(html: str) -> tuple[str, str | None]:
    html = _TAG.sub(" ", html)
    title = None
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if match:
        title = _clean(match.group(1))[:200] or None
    text = _HTML_TAG.sub("\n", html)
    return _clean(text), title


# --------------------------------------------------------------------- registry
class SourceProvider:
    """Reads one shape of input into SourceDocuments."""

    kind: SourceKind = "unknown"

    def can_handle(self, source: SourceInput) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError

    def load(self, source: SourceInput) -> list[SourceDocument]:  # pragma: no cover
        raise NotImplementedError


class TextProvider(SourceProvider):
    kind = "text"

    def can_handle(self, source: SourceInput) -> bool:
        return source.kind in {"auto", "text"}

    def load(self, source: SourceInput) -> list[SourceDocument]:
        raw = source.value
        text, truncated = _clip(raw, source.max_chars)
        sections, facts, _ = _parse_markdown(raw)
        return [
            SourceDocument(
                id=_doc_id("text", raw[:200]),
                kind="text",
                title=_first_line(raw),
                text=text,
                sections=sections,
                facts=facts,
                char_count=len(text),
                truncated=truncated,
                sha256=_sha256(raw),
            )
        ]


class MarkdownProvider(SourceProvider):
    kind = "markdown"

    def can_handle(self, source: SourceInput) -> bool:
        if source.kind == "markdown":
            return True
        if source.kind != "auto":
            return False
        return _looks_like_path(source.value) and Path(source.value).suffix.lower() in {
            ".md", ".markdown", ".rst"}

    def load(self, source: SourceInput) -> list[SourceDocument]:
        """``kind="markdown"`` says what ``value`` *is*, not where to fetch it.

        Reading it as a path unconditionally meant inline markdown content —
        the obvious way to hand a planner a document — raised
        ``FileNotFoundError``. A path is only a path when one actually exists;
        otherwise the value is the document.
        """
        path = Path(source.value)
        raw = (_read_local(source.value)
               if _looks_like_path(source.value) and path.exists()
               else source.value)
        return _from_markdown(source, raw, kind="markdown")


class LocalFileProvider(SourceProvider):
    kind = "file"

    def can_handle(self, source: SourceInput) -> bool:
        if source.kind == "file":
            return True
        return source.kind == "auto" and _looks_like_path(source.value)

    def load(self, source: SourceInput) -> list[SourceDocument]:
        path = Path(source.value)
        raw = _read_local(source.value)
        if path.suffix.lower() in {".md", ".markdown", ".rst"}:
            return _from_markdown(source, raw, kind="markdown")
        text, truncated = _clip(raw, source.max_chars)
        return [
            SourceDocument(
                id=_doc_id("file", str(path)),
                kind="file",
                title=path.stem,
                path=str(path),
                text=text,
                sections=[SourceSection(text=text)],
                facts=[line.strip() for line in text.splitlines()
                       if 8 <= len(line.strip()) <= 160][:20],
                char_count=len(text),
                truncated=truncated,
                sha256=_sha256(raw),
            )
        ]


class GitHubProvider(SourceProvider):
    kind = "github"

    def can_handle(self, source: SourceInput) -> bool:
        if source.kind == "github":
            return True
        value = source.value.lower()
        return source.kind == "auto" and ("github.com/" in value or value.endswith(".git"))

    def load(self, source: SourceInput) -> list[SourceDocument]:
        owner, repo = _github_slug(source.value)
        if not owner:
            raise ValueError(f"not a GitHub repository URL: {source.value}")
        last_error: Exception | None = None
        for branch in ("HEAD", "main", "master"):
            for name in ("README.md", "readme.md", "README.MD", "README.rst"):
                url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{name}"
                try:
                    raw = _http_get(url, timeout=DEFAULT_TIMEOUT)
                except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                    last_error = exc
                    continue
                docs = _from_markdown(source, raw, kind="github")
                for doc in docs:
                    doc.url = f"https://github.com/{owner}/{repo}"
                    doc.title = doc.title or f"{owner}/{repo}"
                    doc.trust = "public_web"
                return docs
        raise ValueError(f"could not read a README for {owner}/{repo}: {last_error}")


class WebPageProvider(SourceProvider):
    kind = "webpage"

    def can_handle(self, source: SourceInput) -> bool:
        if source.kind in {"webpage", "url"}:
            return True
        value = source.value.lower()
        return source.kind == "auto" and value.startswith(("http://", "https://"))

    def load(self, source: SourceInput) -> list[SourceDocument]:
        html = _http_get(source.value)
        text, title = _html_to_text(html)
        body, truncated = _clip(text, source.max_chars)
        facts = [line.strip() for line in body.splitlines()
                 if 12 <= len(line.strip()) <= 160][:20]
        return [
            SourceDocument(
                id=_doc_id("web", source.value),
                kind="webpage",
                title=title,
                url=source.value,
                text=body,
                sections=[SourceSection(text=body)],
                facts=facts,
                trust="public_web",
                char_count=len(body),
                truncated=truncated,
                sha256=_sha256(text),
            )
        ]


#: Order matters: the more specific detectors run before the greedy text one.
PROVIDERS: tuple[SourceProvider, ...] = (
    GitHubProvider(),
    WebPageProvider(),
    MarkdownProvider(),
    LocalFileProvider(),
    TextProvider(),
)


def supported_kinds() -> list[str]:
    return [p.kind for p in PROVIDERS]


def detect_kind(value: str) -> SourceKind:
    source = SourceInput(kind="auto", value=value)
    for provider in PROVIDERS:
        if provider.can_handle(source):
            return provider.kind
    return "text"


def resolve_source(
    source: SourceInput | str | Mapping[str, Any] | None,
) -> list[SourceDocument]:
    """Resolve any supported input into documents.

    A plain mapping is accepted and normalised here rather than at every call
    site. JSON bodies, MCP arguments and CLI ``--source`` objects all arrive as
    untyped dicts; if the public boundary advertises ``{"kind": ..., "value":
    ...}`` then refusing that shape would mean the API documents one contract
    and the runtime enforces another.

    Falls through to the text provider rather than raising: a URL we cannot
    classify is still text-shaped to a human, and the worst outcome is a video
    about the literal URL string — which the planner reports as a warning, not
    a crash.
    """
    if source is None:
        return []
    if isinstance(source, str):
        source = SourceInput(value=source)
    elif isinstance(source, Mapping):
        source = SourceInput(**dict(source))
    elif isinstance(source, SourceDocument):  # already resolved; pass through
        return [source]
    if not source.value:
        return []
    if source.kind != "auto":
        for provider in PROVIDERS:
            if provider.kind == source.kind or (
                provider.kind == "webpage" and source.kind == "url"
            ):
                return provider.load(source)
    for provider in PROVIDERS:
        if provider.can_handle(source):
            return provider.load(source)
    return TextProvider().load(source)


# --------------------------------------------------------------- internals
def _looks_like_path(value: str) -> bool:
    if not value or len(value) > 4096:
        return False
    lowered = value.lower()
    if lowered.startswith(("http://", "https://")):
        return False
    if "\n" in value or len(value) > 260:
        return False
    return Path(value).suffix.lower() in _TEXT_SUFFIX or Path(value).name.count(".") == 1


def _read_local(value: str) -> str:
    path = Path(value)
    if not path.exists():
        raise FileNotFoundError(f"source file not found: {value}")
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError(f"source file too large (8 MB limit): {value}")
    return path.read_text(encoding="utf-8", errors="replace")


def _from_markdown(source: SourceInput, raw: str,
                   kind: SourceKind) -> list[SourceDocument]:
    clipped, truncated = _clip(raw, source.max_chars)
    sections, facts, title = _parse_markdown(clipped)
    return [
        SourceDocument(
            id=_doc_id("md", source.value[:200]),
            kind=kind,
            title=title,
            path=source.value if _looks_like_path(source.value) else None,
            text=clipped,
            sections=sections or [SourceSection(text=clipped)],
            facts=facts,
            char_count=len(clipped),
            truncated=truncated,
            sha256=_sha256(raw),
        )
    ]


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return ""


def _github_slug(value: str) -> tuple[str, str]:
    text = value.strip().rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    match = re.search(r"github\.com[:/]+([^/]+)/([^/#?]+)", text)
    if not match:
        return "", ""
    return match.group(1), match.group(2).replace(".git", "")


def iter_documents(docs: Iterable[SourceDocument]) -> str:
    """Flatten documents into one planner-friendly digest."""
    return "\n\n".join(doc.summary() for doc in docs if doc.text)
