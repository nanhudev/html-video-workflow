"""Keep a console encoding from turning a successful render into a failed one.

Every user-facing surface in this project eventually writes a string it did not
choose — a provider's error message, a routing explanation, the title derived
from the user's own prompt. On Windows those strings meet the *locale* encoding,
and any glyph outside it raises ``UnicodeEncodeError`` from inside ``print``.

The consequence is worse than an ugly character. The write happens after the
work is done, so the expensive, correct part has already succeeded — and the
process still exits non-zero having printed nothing usable. A caller reading
stdout sees an empty document and concludes the pipeline failed. That is a
false negative produced entirely by the reporter, and it is how the CI one-click
check was red for two commits while the underlying render worked.

The fix is deliberately narrow: it changes the *failure mode* of the stream, not
its encoding. Forcing UTF-8 would be the other plausible choice and it is wrong
here — it would turn correctly rendered Chinese into mojibake on a Chinese
console, breaking the common case to rescue the rare one. Substituting an
unencodable glyph degrades one character and keeps everything else, including
the JSON, parseable.
"""
from __future__ import annotations

import sys
from typing import Any


def make_streams_unfailing(
    streams: tuple[tuple[str, Any], ...] | None = None,
) -> list[str]:
    """Stop ``print`` from being able to raise.

    Returns the names of the streams that were secured, so a caller can report
    what it changed instead of silently mutating global state.
    """
    pairs = streams if streams is not None else (("stdout", sys.stdout),
                                                 ("stderr", sys.stderr))
    secured: list[str] = []
    for name, stream in pairs:
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            # A captured or duck-typed stream — in a test, or a pipe wrapper.
            # There is no encoding to relax, and nothing to report.
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            continue  # already closed, or not a real text stream
        secured.append(name)
    return secured


def safe_write(stream: Any, text: str) -> bool:
    """Write once, degrading the character rather than failing the write.

    A last line of defence for streams that cannot be reconfigured — a CI
    harness reading a subprocess pipe, for instance. Returns whether the write
    succeeded unmodified.
    """
    try:
        stream.write(text)
        return True
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        stream.write(text.encode(encoding, errors="replace").decode(encoding,
                                                                   errors="replace"))
        return False
    except (ValueError, OSError):
        return False
