"""Minimal HTTP client shared by the network TTS adapters.

Deliberately stdlib-only. Adding ``requests`` or ``httpx`` to the core dependency
list so three adapters can make a POST would be a poor trade — the core install
is ``pydantic`` + ``python-dotenv`` and should stay that way.

The retry policy is bounded and only retries idempotent GETs plus connection
failures. Retrying a synthesis POST on a timeout is how you pay for the same
sentence twice.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from ...utils.logging import get_logger

log = get_logger("providers.tts.http")

DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 2
RETRY_BACKOFF_SECONDS = 0.35


@dataclass
class HttpResult:
    ok: bool
    status: int | None = None
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    elapsed_ms: int = 0

    def json(self) -> Any:
        if not self.body:
            return None
        try:
            return json.loads(self.body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def _redact(url: str) -> str:
    """Strip query string before logging — tokens often ride there."""
    parsed = urllib.parse.urlsplit(url)
    if not parsed.query:
        return url
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "***", parsed.fragment)
    )


def request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    json_body: Any | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> HttpResult:
    """Perform one HTTP request. Never raises for a network error.

    Returning a failed ``HttpResult`` instead of propagating an exception is what
    lets a provider ``probe()`` report "engine not running" rather than crashing
    the whole registry walk.
    """
    payload = data
    final_headers = {"User-Agent": "html-video-workflow/0.2"}
    final_headers.update(headers or {})
    if json_body is not None:
        payload = json.dumps(json_body).encode("utf-8")
        final_headers.setdefault("Content-Type", "application/json")

    # Only idempotent verbs get retried. See module docstring.
    attempts = 1 + (retries if method.upper() == "GET" else 0)
    last: HttpResult | None = None

    for attempt in range(attempts):
        started = time.perf_counter()
        req = urllib.request.Request(url, data=payload, method=method.upper())
        for key, value in final_headers.items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read()
                elapsed = int((time.perf_counter() - started) * 1000)
                return HttpResult(
                    ok=200 <= response.status < 300,
                    status=response.status,
                    body=body,
                    headers={k.lower(): v for k, v in response.headers.items()},
                    elapsed_ms=elapsed,
                )
        except urllib.error.HTTPError as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:400]
            except Exception:  # pragma: no cover - body already consumed
                pass
            last = HttpResult(
                ok=False,
                status=exc.code,
                body=detail.encode("utf-8", errors="replace"),
                error=f"HTTP {exc.code} {exc.reason}" + (f": {detail}" if detail else ""),
                elapsed_ms=elapsed,
            )
            # 4xx is a configuration problem; retrying cannot fix it.
            if exc.code < 500:
                return last
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            last = HttpResult(ok=False, error=f"{type(exc).__name__}: {exc}",
                              elapsed_ms=elapsed)
        if attempt + 1 < attempts:
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))

    assert last is not None
    log.debug("request to %s failed: %s", _redact(url), last.error)
    return last


def join_url(base_url: str, path: str) -> str:
    """Join a base URL and path without doubling or eating slashes."""
    base = (base_url or "").rstrip("/")
    suffix = (path or "").lstrip("/")
    return f"{base}/{suffix}" if suffix else base
