"""Post a commit status so a CI failure is readable without log access.

GitHub runner logs and job artifacts both require a browser session or a
personal token. A commit status needs neither: it is visible to anyone with
read access to the repository. When a build goes red on a machine we cannot
log into, this is how the build says what broke.

Usage::

    python scripts/ci_status.py <context> <state> <description>

Requires ``GITHUB_TOKEN``, ``GITHUB_REPOSITORY`` and ``GITHUB_SHA`` in the
environment (all set by Actions) and the workflow to grant
``permissions: statuses: write``.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

MAX_DESCRIPTION = 130


def post(context: str, state: str, description: str) -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    sha = os.environ.get("GITHUB_SHA", "")
    if not (token and repo and sha):
        print("ci_status: not running in Actions; nothing posted")
        return 0

    body = json.dumps({
        "state": state,
        "context": context,
        "description": description[:MAX_DESCRIPTION],
    }).encode()
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/statuses/{sha}",
        data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310
            print(f"ci_status: posted {context} -> {response.status}")
    except urllib.error.HTTPError as exc:
        # A 403 here means the token lacks `statuses: write`; without the body
        # that failure is completely invisible.
        print(f"ci_status: post failed {exc.code}: {exc.read()[:300]!r}")
        return 1
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    return post(argv[1], argv[2], argv[3])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
