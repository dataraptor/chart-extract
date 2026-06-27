"""Security hardening contract (Split 12 — the final gate).

Re-asserts the production-safety invariants on the live HTTP surface:

* **Input validation** — upload size cap, inline-text cap, content-type allowlist (text-layer
  PDF/.txt only — OCR is a §2 non-goal), binary-masquerading-as-text rejection. Every bad input
  returns the structured envelope, never a crash.
* **`sample_id` is an allowlist, not a free path** — traversal/absolute-path ids are rejected.
* **Dev hooks are off in prod** — the ``?simulate`` hook and dev CORS are inert unless the operator
  sets the explicit dev env flag.
* **Envelopes leak nothing** — no stack trace, no internal filesystem path, no key fragment in any
  error response, swept across the whole failure surface.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from chartextract_api.routes import _MAX_TEXT_CHARS, _MAX_UPLOAD_BYTES

# ---------------------------------------------------------------------------
# Input validation — size caps
# ---------------------------------------------------------------------------


def test_oversized_upload_rejected_with_envelope(client: TestClient) -> None:
    blob = b"x" * (_MAX_UPLOAD_BYTES + 1)
    files = {"file": ("big.txt", io.BytesIO(blob), "text/plain")}
    resp = client.post("/api/extract", files=files, data={"schema": "pathology"})
    assert resp.status_code == 413
    assert resp.json()["error"]["type"] == "payload_too_large"


def test_oversized_inline_text_rejected_with_envelope(client: TestClient) -> None:
    resp = client.post("/api/extract", json={"text": "y" * (_MAX_TEXT_CHARS + 1)})
    assert resp.status_code == 413
    assert resp.json()["error"]["type"] == "payload_too_large"


def test_upload_at_limit_is_not_rejected_for_size(client: TestClient) -> None:
    # A doc exactly at the cap passes the size check (it then routes/extracts normally).
    doc = b"PATHOLOGY REPORT\nSpecimen: core biopsy\n"
    doc = doc + b"x" * (_MAX_UPLOAD_BYTES - len(doc))
    files = {"file": ("ok.txt", io.BytesIO(doc), "text/plain")}
    resp = client.post("/api/extract", files=files, data={"schema": "pathology"})
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Input validation — content-type allowlist + binary rejection
# ---------------------------------------------------------------------------


def test_unsupported_file_type_rejected(client: TestClient) -> None:
    files = {"file": ("scan.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")}
    resp = client.post("/api/extract", files=files)
    assert resp.status_code == 415
    assert resp.json()["error"]["type"] == "unsupported_file"


def test_binary_txt_upload_with_nul_rejected_not_crashed(client: TestClient) -> None:
    # Binary bytes with a .txt suffix → a clean 422 envelope, NOT a 500 from UnicodeDecodeError.
    files = {"file": ("fake.txt", io.BytesIO(b"\x00\x01\x02\xff\xfe binary"), "text/plain")}
    resp = client.post("/api/extract", files=files, data={"schema": "pathology"})
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "bad_request"


def test_non_utf8_txt_upload_rejected_not_crashed(client: TestClient) -> None:
    # Invalid UTF-8 (a lone continuation byte) with no NUL → still a clean 422, not a 500.
    files = {"file": ("latin.txt", io.BytesIO(b"caf\xe9 r\xe9sum\xe9"), "text/plain")}
    resp = client.post("/api/extract", files=files, data={"schema": "pathology"})
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "bad_request"


# ---------------------------------------------------------------------------
# sample_id is an allowlist, never a path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "evil",
    [
        "../../../../etc/passwd",
        "..\\..\\windows\\win.ini",
        "/etc/shadow",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "path_report/../intake_form",
    ],
)
def test_sample_id_path_traversal_rejected(client: TestClient, evil: str) -> None:
    resp = client.post("/api/extract", json={"sample_id": evil})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["type"] == "bad_request"
    # The path the attacker injected must not appear to have been opened (no leak of resolution).
    assert "Traceback" not in resp.text


# ---------------------------------------------------------------------------
# Dev hooks are off in production by default
# ---------------------------------------------------------------------------


def test_simulate_hook_inert_without_dev_flag(
    stub_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CHARTEXTRACT_DEV", raising=False)
    from chartextract_api.app import create_app

    client = TestClient(create_app())
    # Every simulate type must be ignored → a real extraction runs (or a real routing decision).
    resp = client.post("/api/extract?simulate=refusal", json={"sample_id": "path_report"})
    assert resp.status_code == 200
    assert resp.json()["doc_type"] == "pathology"


def test_cors_off_by_default(stub_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("CHARTEXTRACT_CORS_DEV", "CHARTEXTRACT_CORS_ORIGINS"):
        monkeypatch.delenv(var, raising=False)
    from chartextract_api.app import create_app

    client = TestClient(create_app())
    resp = client.get("/health", headers={"Origin": "http://evil.example"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}


def test_cors_on_only_behind_dev_flag(stub_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHARTEXTRACT_CORS_DEV", "1")
    from chartextract_api.app import create_app

    client = TestClient(create_app())
    origin = "http://localhost:5173"
    resp = client.get("/health", headers={"Origin": origin})
    assert resp.headers.get("access-control-allow-origin") == origin


# ---------------------------------------------------------------------------
# Envelope leak sweep — no traceback / path / key fragment in any error body
# ---------------------------------------------------------------------------


def test_no_error_response_leaks_internals(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Plant a recognizable fake secret in the env so we can assert it never echoes into a body.
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")  # keep stub mode
    secret = "sk-SUPERSECRET-do-not-leak-1234567890"
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("CHARTEXTRACT_FAKE_SECRET", secret)

    bad_requests = [
        ("json", {"json": {}}),  # zero inputs
        ("json", {"json": {"sample_id": "path_report", "text": "x\ny"}}),  # two inputs
        ("json", {"json": {"sample_id": "nope"}}),  # unknown sample
        ("json", {"json": {"text": "x\ny", "provider": "bogus"}}),  # bad provider
        ("json", {"json": {"text": "x\ny", "schema": "radiology"}}),  # bad schema
        ("raw", {"data": "{not json", "headers": {"content-type": "application/json"}}),
        ("files", {"files": {"file": ("a.png", io.BytesIO(b"\x00"), "image/png")}}),
    ]
    for kind, kwargs in bad_requests:
        resp = client.post("/api/extract", **kwargs)
        assert resp.status_code >= 400, (kind, resp.status_code)
        text = resp.text
        assert "Traceback" not in text
        assert "Traceback (most recent call last)" not in text
        assert secret not in text
        # No absolute filesystem path of the install leaks (Windows or POSIX site-packages).
        assert "site-packages" not in text
        assert "chartextract_api/src" not in text
        assert "/c/Users/" not in text
        # The body is the structured envelope, nothing else.
        assert set(resp.json().keys()) == {"error"}
