"""Multipart upload path (R2): a ``.txt`` upload extracts; form fields drive schema/provider."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from chartextract import ExtractionResult


def test_txt_upload_extracts_on_stub(client: TestClient) -> None:
    doc = "PATHOLOGY REPORT\nSpecimen: Left breast core biopsy\nDiagnosis: Invasive carcinoma"
    files = {"file": ("report.txt", io.BytesIO(doc.encode("utf-8")), "text/plain")}
    resp = client.post("/api/extract", files=files, data={"schema": "pathology"})
    assert resp.status_code == 200, resp.text
    result = ExtractionResult.model_validate(resp.json())
    assert result.doc_type == "pathology"
    assert result.highlight_available is True


def test_upload_requires_a_schema_or_routes(client: TestClient) -> None:
    # An uploaded doc with no schema + an unclassifiable body → 409 (router refuses to guess).
    files = {"file": ("note.txt", io.BytesIO(b"random unrelated text\nno header"), "text/plain")}
    resp = client.post("/api/extract", files=files)
    assert resp.status_code == 409
    assert resp.json()["error"]["type"] == "unknown_doc_type"
