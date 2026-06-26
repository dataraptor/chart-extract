"""``/health`` — names the active provider so the UI is honest about canned vs live (R/E10)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_ok_stub_when_no_key(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["provider"] == "stub"
    assert body["model"] == "stub"
