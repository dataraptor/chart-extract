"""Coverage for the adapter's smaller branches: CLI launcher, dev CORS, and edge error paths."""

from __future__ import annotations

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient


def test_intake_guessed_without_schema(client: TestClient) -> None:
    # No schema override → the stub's header-keyword guess picks intake.
    resp = client.post(
        "/api/extract",
        json={"text": "INTAKE FORM\nPATIENT: Jane Doe\nDOB: 1971-03-14\nSex: Female"},
    )
    assert resp.status_code == 200
    assert resp.json()["doc_type"] == "intake"


def test_unknown_provider_is_bad_request(client: TestClient) -> None:
    resp = client.post(
        "/api/extract",
        json={"sample_id": "path_report", "schema": "pathology", "provider": "bogus"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "bad_request"


def test_unknown_sample_id_is_bad_request(client: TestClient) -> None:
    resp = client.post("/api/extract", json={"sample_id": "does_not_exist", "schema": "pathology"})
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "bad_request"


def test_internal_error_envelope_no_traceback(
    stub_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An unexpected failure in a route → the generic handler → 500 envelope, never a traceback.
    # raise_server_exceptions=False so the TestClient returns the envelope a real client sees
    # (rather than re-raising for test visibility).
    from chartextract_api import deps
    from chartextract_api.app import create_app

    def _boom() -> list:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(deps, "load_samples", _boom)
    client = TestClient(create_app(), raise_server_exceptions=False)
    resp = client.get("/api/samples")
    assert resp.status_code == 500
    assert resp.json()["error"]["type"] == "internal"
    assert "Traceback" not in resp.text


def test_validation_handler_summary(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Drive the RequestValidationError handler directly (it's the defensive backstop).
    from chartextract_api import deps

    def _raise() -> list:
        raise RequestValidationError([])

    monkeypatch.setattr(deps, "load_samples", _raise)
    resp = client.get("/api/samples")
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "bad_request"


def test_cors_dev_flag_adds_header(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("AZURE_OPENAI_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CHARTEXTRACT_CORS_DEV", "1")
    from chartextract_api.app import create_app

    client = TestClient(create_app())
    resp = client.get("/health", headers={"origin": "http://localhost:5173"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cli_main_invokes_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    captured: dict[str, object] = {}

    def _fake_run(target: str, **kwargs: object) -> None:
        captured["target"] = target
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", _fake_run)
    from chartextract_api.cli import main

    rc = main(["--host", "0.0.0.0", "--port", "9001", "--dev"])
    assert rc == 0
    assert captured["target"] == "chartextract_api.app:app"
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9001
