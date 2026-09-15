"""Talking to the desktop: open a file, reveal it in the file manager.

The wizard's last step is "打开文件位置", and on a product aimed at people who
do not use a terminal that is not a nicety — it is the difference between
"rendered successfully" and "I cannot find my video".

Three rules this module keeps:

* **Never guess a path is safe.** Containment is checked by the caller against
  the app home; this module will happily open whatever it is given, so the
  check has to happen before the call, not here. :func:`resolve_within` exists
  so callers do not have to write that check twice.
* **Never block.** These are fire-and-forget subprocesses; a hung file manager
  must not hang a render server.
* **Never claim success we did not get.** A headless Linux box has no way to
  show anyone anything, and saying "opened" there would be a lie. The function
  raises :class:`DesktopUnavailable` instead, and the caller reports it as text
  the user can act on (the path is still in the response).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .logging import get_logger

log = get_logger("utils.desktop")


class DesktopUnavailable(RuntimeError):
    """No mechanism on this machine can show a file to the user."""


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _spawn(argv: list[str]) -> None:
    """Fire and forget.

    No ``check=True``: Windows Explorer exits non-zero even when it did exactly
    what was asked (``explorer /select,`` returns 1 on success), so a return
    code here is not evidence of anything. Failures to even start the process
    are the only thing worth catching, and they raise ``OSError``.
    """
    subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        close_fds=not _is_windows(),
    )


def resolve_within(path: str | os.PathLike[str], root: Path) -> Path:
    """Resolve ``path`` and refuse anything outside ``root``.

    The API exposes "open this file" to a browser. Without this check that is a
    remote file-opener for anything on the machine, reachable by any page the
    user has open. ``resolve()`` matters as much as the prefix test: without it
    ``<root>/../../etc`` walks straight out.
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError(f"path must be absolute: {path!r}")
    resolved = candidate.resolve()
    base = root.resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError(f"path is outside the app home: {resolved}")
    return resolved


def reveal(path: str | os.PathLike[str]) -> str:
    """Show ``path`` in the OS file manager, selecting it when it is a file.

    Returns a human-readable description of what was done, for the API response
    and the log.
    """
    target = Path(path).resolve()
    if not target.exists():
        raise FileNotFoundError(str(target))

    if _is_windows():
        # The comma is not decoration: `explorer /select,<path>` is parsed as
        # `/select` plus a path, and without the comma Explorer opens Documents.
        _spawn(["explorer", f"/select,{target}"])
        return f"opened Explorer with {target.name} selected"
    if _is_macos():
        _spawn(["open", "-R", str(target)])
        return f"revealed {target.name} in Finder"

    directory = target if target.is_dir() else target.parent
    opener = _which("xdg-open")
    if opener is None:
        raise DesktopUnavailable(
            "no xdg-open on PATH, so this machine cannot show a file manager")
    _spawn([opener, str(directory)])
    return f"opened {directory}"


def open_file(path: str | os.PathLike[str]) -> str:
    """Open ``path`` with whatever the OS considers its default handler."""
    target = Path(path).resolve()
    if not target.exists():
        raise FileNotFoundError(str(target))

    if _is_windows():
        os.startfile(str(target))  # type: ignore[attr-defined]  # noqa: S606
        return f"opened {target.name} with the default application"
    if _is_macos():
        _spawn(["open", str(target)])
        return f"opened {target.name} with the default application"

    opener = _which("xdg-open")
    if opener is None:
        raise DesktopUnavailable(
            "no xdg-open on PATH, so this machine has nothing to open files with")
    _spawn([opener, str(target)])
    return f"opened {target.name} with the default application"


def open_url(url: str) -> str:
    """Open ``url`` in the default browser."""
    if _is_windows():
        os.startfile(url)  # type: ignore[attr-defined]  # noqa: S606
        return f"opened {url} in the default browser"
    if _is_macos():
        _spawn(["open", url])
        return f"opened {url} in the default browser"
    opener = _which("xdg-open")
    if opener is None:
        raise DesktopUnavailable("no xdg-open on PATH, so no browser can be started")
    _spawn([opener, url])
    return f"opened {url} in the default browser"


def _which(name: str) -> str | None:
    import shutil

    return shutil.which(name)
