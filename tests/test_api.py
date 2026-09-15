"""API contract tests (no network, no render)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from html_video_workflow.api.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_system_masks_secrets(client: TestClient) -> None:
    body = client.get("/system").json()
    assert "home" in body
    for value in body["secrets"].values():
        assert "****" in value


def test_hardware_endpoint_returns_profil(client: TestClient) -> None:
    body = client.get("/hardware").json()
    assert body["os"]
    assert "tooling" in body


def test_providers_endpoint_lists_mock_and_real_states(client: TestClient) -> None:
    rows = client.get("/providers").json()
    ids = {row["id"] for row in rows}
    assert {"mock_tts", "mock_renderer", "srt"} <= ids
    for row in rows:
        assert "state" in row
        assert "reason" in row


def test_providers_filter_by_type(client: TestClient) -> None:
    rows = client.get("/providers?provider_type=tts").json()
    assert rows
    assert all(row["type"] == "tts" for row in rows)


def test_provider_probe_endpoint(client: TestClient) -> None:
    body = client.get("/providers/mock_tts/probe").json()
    assert body["probe"]["state"] == "ready"


def test_unknown_provider_returns_404(client: TestClient) -> None:
    assert client.post("/providers/nope/probe").status_code == 404


def test_routing_is_explainable(client: TestClient) -> None:
    body = client.get("/routing?preset=fast").json()
    assert body["preset"] == "fast"
    assert body["selection"]["renderer"]
    for stage, info in body["reasons"].items():
        assert "candidates" in info


def test_create_project_and_fetch(client: TestClient) -> None:
    created = client.post(
        "/projects", json={"prompt": "介绍一下量子计算", "language": "zh-CN", "preset": "fast"}
    ).json()
    assert created["scenes"] >= 1
    project_id = created["id"]
    fetched = client.get(f"/projects/{project_id}").json()
    assert fetched["schema_version"] == 2
    assert fetched["sequences"]


def test_create_project_requires_input(client: TestClient) -> None:
    assert client.post("/projects", json={"language": "zh-CN"}).status_code == 400


def test_unknown_project_returns_404(client: TestClient) -> None:
    assert client.get("/projects/prj_missing").status_code == 404


def test_validate_endpoint_accepts_v1(client: TestClient, legacy_project_path) -> None:
    import json

    data = json.loads(legacy_project_path.read_text(encoding="utf-8"))
    body = client.post("/validate", json=data).json()
    assert body["valid"] is True
    assert body["schema_version"] == 1


def test_validate_endpoint_rejects_garbage(client: TestClient) -> None:
    body = client.post("/validate", json={"schema_version": 2, "project": {"title": None}}).json()
    assert body["valid"] is False
    assert body["errors"]


def test_projects_listing(client: TestClient) -> None:
    client.post("/projects", json={"prompt": "list test", "preset": "fast"})
    items = client.get("/projects").json()
    assert isinstance(items, list)


def test_jobs_listing(client: TestClient) -> None:
    assert isinstance(client.get("/jobs").json(), list)
