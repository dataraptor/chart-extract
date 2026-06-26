"""Split 03 — the end-to-end offline pipeline (pipeline.py).

Runs the WHOLE ``load → route → parse(stub) → ground → assemble`` chain and asserts the §5 worked
example reproduces through it, the counts/cost/versions are right, and the result is JSON-safe.
"""

from __future__ import annotations

import json

import pytest

from chartextract import (
    ExtractionResult,
    StubProvider,
    UnknownDocTypeError,
    extract,
    stub_for_intake,
    stub_for_path_report,
)

# The §5 table verbatim: (name, value, flag).
PATH_WORKED_EXAMPLE = [
    ("specimen", "Left breast core biopsy", None),
    ("diagnosis", "Invasive ductal carcinoma", None),
    ("grade", "2", None),
    ("tumor_size_cm", 1.4, None),
    ("er_status", "positive", None),
    ("pr_status", "positive", None),
    ("her2_status", "negative", None),
    ("margin_status", None, "not_assessed"),
    ("lymph_nodes_positive", None, "not_found"),
]


def test_path_report_end_to_end(path_report_path):
    stub = stub_for_path_report()
    result = extract(path_report_path, schema="pathology", provider=stub)

    assert isinstance(result, ExtractionResult)
    assert result.doc_type == "pathology"
    assert result.n_fields == 9
    by_name = {f.name: f for f in result.fields}
    for name, value, flag in PATH_WORKED_EXAMPLE:
        assert by_name[name].value == value, name
        assert by_name[name].flag == flag, name

    # counts: 7 grounded · 2 null · 0 review
    assert (result.n_grounded, result.n_null, result.n_needs_review) == (7, 2, 0)
    # cost priced from real usage, latency measured, versions + model recorded
    assert result.cost_usd > 0
    assert result.latency_s >= 0
    assert result.prompt_version == "v3"
    assert result.schema_version == "v2"
    assert result.model == stub.model
    assert result.highlight_available is True


def test_every_grounded_field_offset_is_real_substring(path_report_path):
    from chartextract import load

    doc = load(path_report_path)
    result = extract(path_report_path, schema="pathology", provider=stub_for_path_report())
    for f in result.fields:
        if f.value is not None:
            assert doc.text[f.char_start : f.char_end] == f.source_span


def test_caught_hallucination_round_trips_model_value(path_report_path):
    result = extract(
        path_report_path, schema="pathology", provider=stub_for_path_report(caught=True)
    )
    lymph = next(f for f in result.fields if f.name == "lymph_nodes_positive")
    assert lymph.flag == "not_grounded"
    assert lymph.value is None
    assert lymph.model_value == 2


def test_intake_listfield_flattened_and_partial(intake_form_path):
    result = extract(intake_form_path, schema="intake", provider=stub_for_intake())
    names = [f.name for f in result.fields]
    # ListField items flattened as name[i]
    assert "medications[0]" in names
    assert "medications[1]" in names
    assert "medications[2]" in names
    assert "allergies[0]" in names
    by_name = {f.name: f for f in result.fields}
    assert by_name["pcp"].flag == "not_found"
    assert by_name["chief_complaint"].flag == "needs_review"
    # 8 grounded · 1 null · 1 review
    assert (result.n_grounded, result.n_null, result.n_needs_review) == (8, 1, 1)


def test_result_is_json_serializable(path_report_path):
    result = extract(path_report_path, schema="pathology", provider=stub_for_path_report())
    blob = json.dumps(result.model_dump())
    assert '"doc_type": "pathology"' in blob
    # round-trips back into the model unchanged
    assert ExtractionResult.model_validate_json(result.model_dump_json()) == result


def test_classifier_route_no_override(path_report_path):
    # No --schema: the stub's canned classifier picks pathology and the pipeline runs.
    result = extract(path_report_path, provider=stub_for_path_report())
    assert result.doc_type == "pathology"
    assert result.n_fields == 9


def test_unknown_route_surfaces_error(path_report_path):
    stub = StubProvider(classify_result=("unknown", 0.0))
    with pytest.raises(UnknownDocTypeError):
        extract(path_report_path, provider=stub)


def test_no_text_layer_marks_highlight_unavailable_and_nulls_offsets(monkeypatch, path_report_path):
    # Simulate a scanned PDF: same text, but has_text_layer=False. The result must say highlight is
    # unavailable and carry no offsets — honest, not faked (the Split 09 banner reads this).
    from chartextract import load as real_load
    from chartextract import pipeline

    def fake_load(doc, *, source_name=None):
        d = real_load(doc, source_name=source_name)
        return d.model_copy(update={"has_text_layer": False})

    monkeypatch.setattr(pipeline, "load", fake_load)
    result = extract(path_report_path, schema="pathology", provider=stub_for_path_report())
    assert result.highlight_available is False
    assert all(f.char_start is None and f.char_end is None for f in result.fields)
