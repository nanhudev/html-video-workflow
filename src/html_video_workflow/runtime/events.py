"""Observability: append-only JSONL event stream + in-process pub/sub (SSE)."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from queue import Queue
from typing import Any

from ..config.paths import logs_dir
from ..utils.logging import get_logger

log = get_logger("runtime.events")

_subscribers: dict[str, list[Queue[str]]] = {}
_lock = threading.RLock()


def event_path(job_id: str) -> Path:
    path = logs_dir() / f"{job_id}.events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def emit(job_id: str, stage: str, event: str, **payload: Any) -> dict[str, Any]:
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "job_id": job_id,
        "stage": stage,
        "event": event,
        **payload,
    }
    line = json.dumps(record, ensure_ascii=False, default=str)
    try:
        with event_path(job_id).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:  # pragma: no cover
        log.warning("unable to persist event: %s", exc)
    with _lock:
        for queue in list(_subscribers.get(job_id, [])):
            try:
                queue.put_nowait(line)
            except Exception:  # pragma: no cover - defensive
                pass
    return record


def read_events(job_id: str) -> list[dict[str, Any]]:
    path = event_path(job_id)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def subscribe(job_id: str) -> Queue[str]:
    with _lock:
        queue: Queue[str] = Queue()
        _subscribers.setdefault(job_id, []).append(queue)
        return queue


def unsubscribe(job_id: str, queue: Queue[str]) -> None:
    with _lock:
        queues = _subscribers.get(job_id, [])
        if queue in queues:
            queues.remove(queue)


async def stream_events(job_id: str, poll_interval: float = 0.4):
    """Async generator yielding SSE-formatted lines for a job."""
    queue = subscribe(job_id)
    try:
        for event in read_events(job_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        while True:
            try:
                line = queue.get_nowait()
            except Exception:
                await asyncio.sleep(poll_interval)
                continue
            yield f"data: {line}\n\n"
    finally:
        unsubscribe(job_id, queue)
