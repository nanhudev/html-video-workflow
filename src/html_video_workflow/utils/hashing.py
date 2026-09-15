"""Content hashing for cache keys and artifact identity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def hash_json(value: Any) -> str:
    """SHA-256 of a canonical JSON representation."""
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_file(path: str | Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_key(*parts: Any) -> str:
    """Build a deterministic cache key from heterogeneous parts.

    Every cache key must include content + provider id + provider version +
    relevant config, otherwise a provider change would silently reuse stale
    artifacts.
    """
    normalized = [stable_json(part) if not isinstance(part, str) else part for part in parts]
    return hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()[:32]
