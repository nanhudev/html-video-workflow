"""Artifact cache.

Cache keys always include content + provider id + provider config, so changing
provider never reuses a stale artifact.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from ..config.paths import cache_dir
from ..utils.hashing import cache_key, hash_file
from ..utils.logging import get_logger

log = get_logger("runtime.cache")

INDEX_NAME = "index.json"


def _index_path() -> Path:
    return cache_dir() / INDEX_NAME


def _load_index() -> dict[str, Any]:
    path = _index_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_index(index: dict[str, Any]) -> None:
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def key_for(provider_id: str, content: Any, config: Any = None) -> str:
    return cache_key(provider_id, content, config or {})


def get(provider_id: str, content: Any, config: Any = None) -> Path | None:
    """Return a cached artifact path, or None. Missing files are evicted."""
    key = key_for(provider_id, content, config)
    index = _load_index()
    entry = index.get(key)
    if not entry:
        return None
    path = Path(entry["path"])
    if not path.exists():
        index.pop(key, None)
        _save_index(index)
        return None
    entry["hits"] = int(entry.get("hits", 0)) + 1
    entry["last_used"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save_index(index)
    return path


def put(provider_id: str, content: Any, config: Any, source: str | Path,
        suffix: str | None = None) -> Path:
    """Store an artifact in the cache and return its cached path."""
    source = Path(source)
    key = key_for(provider_id, content, config)
    target = cache_dir() / provider_id / f"{key}{suffix or source.suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    index = _load_index()
    index[key] = {
        "provider": provider_id,
        "path": str(target),
        "sha256": hash_file(target),
        "size_bytes": target.stat().st_size,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hits": 0,
    }
    _save_index(index)
    return target


def stats() -> dict[str, Any]:
    index = _load_index()
    total_bytes = 0
    for entry in index.values():
        try:
            total_bytes += int(entry.get("size_bytes") or 0)
        except (TypeError, ValueError):
            continue
    return {
        "entries": len(index),
        "bytes": total_bytes,
        "megabytes": round(total_bytes / (1024 * 1024), 2),
        "directory": str(cache_dir()),
    }


def clear() -> int:
    index = _load_index()
    removed = 0
    for entry in index.values():
        try:
            Path(entry["path"]).unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    _save_index({})
    return removed
