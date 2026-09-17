"""Allow ``python -m html_video_workflow.cli`` to behave like ``html-video``.

The console script is the documented way in, but a console script is only
installed *somewhere*: inside a virtualenv the operator may not have activated,
or nowhere at all when someone is working from a source checkout. Module
execution always works as long as the package imports, which makes it the form
worth keeping in a README next to the pip-installed one.

`` dev.py `` and ``scripts/e2e_one_click.py`` both fall back to this rather than
relying on whatever ``html-video`` happens to be first on PATH.
"""
from __future__ import annotations

import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())
