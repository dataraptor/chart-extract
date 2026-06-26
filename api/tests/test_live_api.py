"""Tier-2 live conformance (``@api``) — auto-skips with no key, so CI never fails on it.

Proves the HTTP seam works end-to-end against the real GPT-5.5 provider: the §5 pathology table
reproduces through ``/api/extract`` with ``provider=openai`` and a positive cost.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from chartextract import ExtractionResult
from chartextract_api.app import create_app

_HAS_KEY = bool(os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY"))


@pytest.mark.api
@pytest.mark.skipif(not _HAS_KEY, reason="no live provider key configured")
def test_live_path_report_via_http() -> None:
    client = TestClient(create_app())
    resp = client.post(
        "/api/extract",
        json={"sample_id": "path_report", "schema": "pathology", "provider": "openai"},
    )
    assert resp.status_code == 200, resp.text
    result = ExtractionResult.model_validate(resp.json())

    by_name = {f.name: f for f in result.fields}
    # The two distinct nulls — the model must not hallucinate them (§5).
    assert by_name["margin_status"].value is None
    assert by_name["lymph_nodes_positive"].value is None
    assert (result.n_grounded, result.n_null, result.n_needs_review) == (7, 2, 0)
    assert result.model == "gpt-5.5"
    assert result.cost_usd > 0
