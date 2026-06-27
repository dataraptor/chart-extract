"""``/api/extract`` — the core call, offline on the stub (E2/E3/E6/E7).

The response body is exactly ``ExtractionResult.model_dump()``; the §5 flags reproduce, the intake
ListField flattens, routing never silently guesses, and the no-text-layer signal is carried.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from chartextract import ExtractionResult


def _result(resp) -> ExtractionResult:
    assert resp.status_code == 200, resp.text
    # The body round-trips back into the engine's own type — proof it's the core shape (E3).
    return ExtractionResult.model_validate(resp.json())


def test_path_report_reproduces_section5(client: TestClient) -> None:
    resp = client.post("/api/extract", json={"sample_id": "path_report", "schema": "pathology"})
    result = _result(resp)

    assert result.doc_type == "pathology"
    by_name = {f.name: f for f in result.fields}
    # The two distinct nulls from the §5 worked example.
    assert by_name["margin_status"].value is None
    assert by_name["margin_status"].flag == "not_assessed"
    assert by_name["lymph_nodes_positive"].value is None
    assert by_name["lymph_nodes_positive"].flag == "not_found"
    # Footer counts: 7 grounded · 2 null · 0 review.
    assert (result.n_grounded, result.n_null, result.n_needs_review) == (7, 2, 0)

    # Grounded fields carry real integer offsets and provenance.
    spec = by_name["specimen"]
    assert isinstance(spec.char_start, int) and isinstance(spec.char_end, int)
    assert spec.char_end > spec.char_start

    # Cost / latency / versions all present.
    assert result.cost_usd > 0
    assert result.latency_s >= 0
    assert result.prompt_version and result.schema_version
    assert result.highlight_available is True


def test_intake_listfield_flattened(client: TestClient) -> None:
    resp = client.post("/api/extract", json={"sample_id": "intake_form", "schema": "intake"})
    result = _result(resp)

    assert result.doc_type == "intake"
    names = [f.name for f in result.fields]
    assert "medications[0]" in names and "medications[2]" in names
    assert "allergies[0]" in names
    by_name = {f.name: f for f in result.fields}
    assert by_name["pcp"].value is None
    assert by_name["pcp"].flag == "not_found"
    assert (result.n_grounded, result.n_null, result.n_needs_review) == (8, 1, 1)


def test_routing_unknown_returns_409(client: TestClient) -> None:
    # Inline text the stub classifier can't place → the router refuses to guess (409), not a
    # silent default-to-pathology.
    resp = client.post(
        "/api/extract", json={"text": "Some unrelated note about the weather.\nNo clinical header."}
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["type"] == "unknown_doc_type"


def test_short_single_line_inline_text_is_not_treated_as_a_path(client: TestClient) -> None:
    # A short, single-line paste ("chest pain") is a document body, not a file path. It must route
    # through the engine (here: unclassifiable → 409), never surface load()'s path heuristic as a
    # 500 internal error. Regression for the inline-text-vs-path misread.
    resp = client.post("/api/extract", json={"text": "chest pain"})
    assert resp.status_code == 409
    assert resp.json()["error"]["type"] == "unknown_doc_type"


def test_short_single_line_inline_text_with_schema_extracts(client: TestClient) -> None:
    # The same short single-line input, with an explicit schema, extracts cleanly (200) instead of
    # erroring — proof the body reaches the pipeline as text.
    resp = client.post(
        "/api/extract", json={"text": "Left breast core biopsy", "schema": "pathology"}
    )
    assert resp.status_code == 200
    assert resp.json()["doc_type"] == "pathology"


def test_schema_override_bypasses_classifier(client: TestClient) -> None:
    # The same inline text, but with an explicit schema → routed without the classifier.
    resp = client.post(
        "/api/extract",
        json={"text": "PATHOLOGY REPORT\nSpecimen: Left breast core biopsy", "schema": "pathology"},
    )
    assert resp.status_code == 200
    assert resp.json()["doc_type"] == "pathology"


def test_body_json_round_trips(client: TestClient) -> None:
    resp = client.post("/api/extract", json={"sample_id": "path_report", "schema": "pathology"})
    assert resp.status_code == 200
    # The UI parses this JSON; it must be valid, round-trippable JSON.
    reparsed = json.loads(resp.text)
    assert reparsed == json.loads(json.dumps(reparsed))
