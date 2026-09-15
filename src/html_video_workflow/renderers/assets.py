"""AssetResolver — resolve layer `src` against the project's asset table.

Layers reference assets by id or by path. Resolving them is a separate step from
rendering because "the asset is missing" and "the asset rendered badly" are
different failures with different remedies, and a renderer that conflates them
reports the wrong one.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResolvedAsset:
    """An asset that exists on disk, in a form a browser can load."""

    kind: str
    #: Absolute file path, or None for remote.
    path: Path | None
    url: str | None
    license: str | None = None
    attribution: str | None = None
    sha256: str | None = None

    def as_src(self) -> str:
        if self.url:
            return self.url
        if self.path is None:
            return ""
        return self.path.resolve().as_uri()


@dataclass(frozen=True)
class MissingAsset:
    """Why an asset could not be resolved. Always carries a reason."""

    ref: str
    reason: str


class AssetResolver:
    """Look up assets the project declared, and say clearly when one is absent."""

    def __init__(
        self,
        assets: list[dict[str, Any]] | dict[str, Any] | None = None,
        *,
        base_dir: Path | None = None,
    ) -> None:
        self._base = base_dir
        self._by_id: dict[str, dict[str, Any]] = {}
        self._assets = self._normalize(assets)
        for entry in self._assets:
            key = entry.get("id")
            if key:
                self._by_id[str(key)] = entry

    @staticmethod
    def _normalize(assets: list[dict] | dict | None) -> list[dict[str, Any]]:
        """Accept both shapes the IR allows.

        `VideoProject.assets` is `list[AssetRef] | dict[str, Any]`, which exists
        for backwards compatibility with older projects. Rather than rejecting
        the dict form, both are flattened to a list — migrating old files is not
        the user's job.
        """
        if not assets:
            return []
        if isinstance(assets, dict):
            merged: list[dict[str, Any]] = []
            for key, value in assets.items():
                if isinstance(value, dict):
                    entry = dict(value)
                    entry.setdefault("id", key)
                    merged.append(entry)
                elif isinstance(value, list):
                    merged.extend(v for v in value if isinstance(v, dict))
            return merged
        return [dict(a) for a in assets]

    def resolve(self, ref: str | None) -> ResolvedAsset | MissingAsset:
        if not ref:
            return MissingAsset(ref="", reason="layer declares no source")

        entry = self._by_id.get(ref)
        if entry is not None:
            return self._from_entry(entry, ref)

        # A bare path, possibly relative to the project directory.
        candidate = Path(ref)
        if self._base and not candidate.is_absolute():
            candidate = self._base / ref
        if candidate.exists() and candidate.is_file():
            return ResolvedAsset(
                kind=self._guess_kind(candidate),
                path=candidate,
                url=None,
                sha256=self._hash(candidate),
            )

        if re.match(r"^https?://", ref):
            return ResolvedAsset(kind="image", path=None, url=ref)

        if ref.startswith("data:"):
            return ResolvedAsset(kind="image", path=None, url=ref)

        return MissingAsset(
            ref=ref,
            reason=f"not declared in project.assets and no file at {ref}",
        )

    def _from_entry(self, entry: dict[str, Any], ref: str) -> ResolvedAsset | MissingAsset:
        url = entry.get("url")
        path_value = entry.get("path")
        path = Path(path_value) if path_value else None
        if path and self._base and not path.is_absolute():
            path = self._base / path
        if path is not None and not path.exists():
            return MissingAsset(
                ref=ref,
                reason=f"declared asset points at a missing file: {path}",
            )
        if path is None and not url:
            return MissingAsset(
                ref=ref, reason="declared asset has neither path nor url"
            )
        kind = entry.get("kind") or self._guess_kind(path)
        return ResolvedAsset(
            kind=kind or "image",
            path=path,
            url=url,
            license=entry.get("license"),
            attribution=entry.get("attribution"),
            sha256=entry.get("sha256") or (self._hash(path) if path else None),
        )

    @staticmethod
    def _guess_kind(path: Path | None) -> str:
        if path is None:
            return "image"
        suffix = path.suffix.lower()
        if suffix in {".mp4", ".mov", ".webm", ".mkv"}:
            return "video"
        if suffix in {".mp3", ".wav", ".ogg", ".m4a"}:
            return "audio"
        return "image"

    @staticmethod
    def _hash(path: Path | None) -> str | None:
        if path is None or not path.exists():
            return None
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:  # pragma: no cover - unreadable source drives
            return None
