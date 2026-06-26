"""Static same-origin serving (E9): ``GET /`` serves the UI; assets load; no CORS in prod."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_root_serves_dc_html(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    # The DC mockup is identified by its `<script type="text/x-dc">` component block.
    assert "x-dc" in resp.text


def test_support_js_served_same_origin(client: TestClient) -> None:
    resp = client.get("/support.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]


def test_no_cors_header_by_default(client: TestClient) -> None:
    # Same-origin in prod → no CORS middleware → no access-control-allow-origin header.
    resp = client.get("/health", headers={"origin": "http://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}


def test_root_json_when_no_app_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """With no frontend dir, ``/`` degrades to a JSON service pointer (still single process)."""
    for var in ("AZURE_OPENAI_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CHARTEXTRACT_APP_DIR", str(tmp_path / "missing"))
    from chartextract_api.app import create_app

    body = TestClient(create_app()).get("/").json()
    assert body["service"] == "chartextract-api"
