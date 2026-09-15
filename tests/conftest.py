"""Shared pytest fixtures.

Tests never download models and never call a paid API. Heavy capabilities are
exercised through mock providers unless an explicit integration marker is used.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch):
    """Point HVW_HOME at a temp dir so tests never touch the user's real data.

    `tmp_path_factory.mktemp` keeps every directory it hands out and deletes them
    all in one sweep at session end. That sweep is a *bulk* delete, and a sandbox
    with a bulk-delete guard (WorkBuddy's `sitecustomize` shim, threshold ~50
    files) will refuse it and raise `SystemExit(1)` — which pytest reports as the
    whole suite erroring during setup, with no test having actually failed.

    So we garbage-collect each directory as soon as its test is done, keeping the
    pending set at one. Detection is on the fixture, not on the shim: the fixture
    must behave identically in an unguarded environment.
    """
    home = tmp_path_factory.mktemp("hvw-home")
    monkeypatch.setenv("HVW_HOME", str(home))
    from html_video_workflow.config import paths

    paths.hv_home.cache_clear()
    try:
        yield home
    finally:
        paths.hv_home.cache_clear()
        _drop_tree(home)


def _drop_tree(path: Path) -> None:
    """Best-effort, non-fatal cleanup of one test's temp tree.

    Failing to clean up must never fail the run — on Windows a browser or ffmpeg
    child can still hold a handle, and `shutil.rmtree` would raise.
    """
    import shutil

    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def legacy_project_path() -> Path:
    return ROOT / "assets" / "demo-us-study-2026.json"


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove API keys so provider probing stays deterministic."""
    for key in list(os.environ):
        if key.endswith("API_KEY") or key in {"OPENAI_BASE_URL", "HVW_LLM_BASE_URL"}:
            monkeypatch.delenv(key, raising=False)
    yield
