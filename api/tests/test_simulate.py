"""The dev-only ``?simulate=<type>`` edge-state hook (Split 09).

Two contracts: (1) **disabled by default** — without ``CHARTEXTRACT_DEV`` the param is ignored and
a normal extraction runs (the prod-safety guarantee Split 12 re-verifies); (2) **enabled** — each
``type`` produces exactly the typed envelope or degraded result the UI's designed edge state binds
to, never a crash or a stack trace.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def dev_client(stub_env: None, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A stub-provider client with the dev simulate hook enabled."""
    monkeypatch.setenv("CHARTEXTRACT_DEV", "1")
    from chartextract_api.app import create_app

    return TestClient(create_app())


# --- prod safety: the hook is inert unless explicitly enabled --------------


def test_simulate_ignored_when_dev_disabled(
    stub_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With the dev flag off, ?simulate=refusal is ignored → a normal extraction runs (prod safety).
    monkeypatch.delenv("CHARTEXTRACT_DEV", raising=False)
    from chartextract_api.app import create_app

    client = TestClient(create_app())
    res = client.post("/api/extract?simulate=refusal", json={"sample_id": "path_report"})
    assert res.status_code == 200
    assert res.json()["doc_type"] == "pathology"


# --- error envelopes -------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "status", "type_code"),
    [
        ("refusal", 422, "refusal"),
        ("truncated", 422, "truncated"),
        ("unknown_doc_type", 409, "unknown_doc_type"),
        ("missing_api_key", 503, "missing_api_key"),
        ("unsupported_file", 415, "unsupported_file"),
    ],
)
def test_simulate_error_envelopes(
    dev_client: TestClient, name: str, status: int, type_code: str
) -> None:
    res = dev_client.post(f"/api/extract?simulate={name}", json={"sample_id": "path_report"})
    assert res.status_code == status
    body = res.json()
    assert body["error"]["type"] == type_code
    assert "message" in body["error"]
    assert "traceback" not in res.text.lower()  # never leak a stack trace


# --- degraded results ------------------------------------------------------


def test_simulate_no_text_layer(dev_client: TestClient) -> None:
    res = dev_client.post("/api/extract?simulate=no_text_layer", json={"sample_id": "path_report"})
    assert res.status_code == 200
    body = res.json()
    assert body["highlight_available"] is False
    # Values still present (vision fallback extracted them), but every offset is unavailable.
    assert all(f["char_start"] is None and f["char_end"] is None for f in body["fields"])
    assert any(f["value"] is not None for f in body["fields"])


def test_simulate_ambiguous(dev_client: TestClient) -> None:
    res = dev_client.post("/api/extract?simulate=ambiguous", json={"sample_id": "path_report"})
    assert res.status_code == 200
    fields = {f["name"]: f for f in res.json()["fields"]}
    er = fields["er_status"]
    assert er["flag"] == "ambiguous_span"
    assert er["n_matches"] >= 2  # the "1 of N" tag has a real N
    assert er["char_start"] is not None  # the first match is still highlightable


def test_simulate_misroute_is_mostly_ungrounded(dev_client: TestClient) -> None:
    res = dev_client.post("/api/extract?simulate=misroute", json={"sample_id": "path_report"})
    assert res.status_code == 200
    body = res.json()
    # pathology spans grounded against intake text → coverage collapses (the misroute signal).
    assert body["n_grounded"] == 0


def test_simulate_unknown_type_is_bad_request(dev_client: TestClient) -> None:
    res = dev_client.post("/api/extract?simulate=bogus", json={"sample_id": "path_report"})
    assert res.status_code == 400
    assert res.json()["error"]["type"] == "bad_request"
