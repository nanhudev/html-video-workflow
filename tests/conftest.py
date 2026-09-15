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
    """Point HVW_HOME at a temp dir so tests never touch the user's real data."""
    home = tmp_path_factory.mktemp("hvw-home")
    monkeypatch.setenv("HVW_HOME", str(home))
    from html_video_workflow.config import paths

    paths.hv_home.cache_clear()
    yield home
    paths.hv_home.cache_clear()


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
