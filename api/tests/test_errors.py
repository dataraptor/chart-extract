"""Error-envelope contract (E5): every typed failure → its HTTP + ``type``; no traceback ever."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from chartextract import Usage
from chartextract.provider.base import RefusalError, TruncatedError


class _RaisingProvider:
    """A provider that raises a chosen error from ``extract`` — to drive each error path."""

    provider = "stub"
    model = "stub"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def extract(self, system, document_text, schema_model):  # noqa: ANN001
        raise self._exc

    def classify_doc_type(self, text):  # noqa: ANN001 - pragma: no cover (override bypasses it)
        return "unknown", 0.0, Usage()


def _inject(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    from chartextract_api import deps

    monkeypatch.setattr(deps, "get_provider", lambda *a, **k: _RaisingProvider(exc))


def _assert_no_traceback(resp) -> None:
    assert "Traceback" not in resp.text
    assert 'File "' not in resp.text


def test_missing_key_503(client: TestClient) -> None:
    # provider=openai with no key configured → MissingAPIKeyError → 503 envelope.
    resp = client.post(
        "/api/extract",
        json={"sample_id": "path_report", "schema": "pathology", "provider": "openai"},
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["type"] == "missing_api_key"
    _assert_no_traceback(resp)


def test_refusal_422(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _inject(monkeypatch, RefusalError("the model refused"))
    resp = client.post("/api/extract", json={"sample_id": "path_report", "schema": "pathology"})
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "refusal"
    _assert_no_traceback(resp)


def test_truncated_422(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _inject(monkeypatch, TruncatedError("output truncated"))
    resp = client.post("/api/extract", json={"sample_id": "path_report", "schema": "pathology"})
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "truncated"
    _assert_no_traceback(resp)


def test_unsupported_upload_415(client: TestClient) -> None:
    files = {"file": ("scan.png", io.BytesIO(b"\x89PNG..."), "image/png")}
    resp = client.post("/api/extract", files=files, data={"schema": "pathology"})
    assert resp.status_code == 415
    assert resp.json()["error"]["type"] == "unsupported_file"
    _assert_no_traceback(resp)


def test_malformed_body_422(client: TestClient) -> None:
    # Extra/unknown key → extra=forbid → bad_request.
    resp = client.post("/api/extract", json={"sample_id": "path_report", "bogus": 1})
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "bad_request"
    _assert_no_traceback(resp)


def test_zero_inputs_is_bad_request(client: TestClient) -> None:
    resp = client.post("/api/extract", json={})
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "bad_request"
    _assert_no_traceback(resp)


def test_two_inputs_is_bad_request(client: TestClient) -> None:
    resp = client.post(
        "/api/extract", json={"sample_id": "path_report", "text": "PATHOLOGY\nSpecimen: x"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "bad_request"
    _assert_no_traceback(resp)


def test_invalid_json_body_422(client: TestClient) -> None:
    resp = client.post(
        "/api/extract", content="{not json", headers={"content-type": "application/json"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "bad_request"
    _assert_no_traceback(resp)
