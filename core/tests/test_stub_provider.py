"""Split 03 — the deterministic StubProvider (provider/stub.py)."""

from __future__ import annotations

import pytest

from chartextract import (
    IntakeSchema,
    PathologySchema,
    ProviderClient,
    StubProvider,
    Usage,
    stub_for_intake,
    stub_for_path_report,
)
from chartextract.prompts import EXTRACTION_SYSTEM


def test_stub_satisfies_provider_protocol():
    assert isinstance(StubProvider(), ProviderClient)


def test_extract_dispatches_by_schema_type():
    stub = stub_for_path_report()
    parsed, usage = stub.extract(EXTRACTION_SYSTEM, "DOCUMENT:\n...", PathologySchema)
    assert isinstance(parsed, PathologySchema)
    assert isinstance(usage, Usage)
    assert usage.input_tokens > 0


def test_schema_matched_dispatch_does_not_collide():
    # Queue both: a pathology call must not consume the intake instance, and vice versa.
    stub = StubProvider(
        extract_results=[PathologySchema.model_construct(), IntakeSchema.model_construct()]
    )
    # ask for intake first — it must skip the queued pathology instance, not pop it
    intake, _ = stub.extract("sys", "doc", IntakeSchema)
    assert isinstance(intake, IntakeSchema)
    path, _ = stub.extract("sys", "doc", PathologySchema)
    assert isinstance(path, PathologySchema)


def test_extract_without_canned_result_raises():
    stub = StubProvider(extract_results=[])
    with pytest.raises(LookupError):
        stub.extract("sys", "doc", PathologySchema)


def test_classify_returns_canned_key_conf_usage():
    key, conf, usage = stub_for_intake().classify_doc_type("PATIENT INTAKE FORM ...")
    assert key == "intake"
    assert 0.0 <= conf <= 1.0
    assert isinstance(usage, Usage)


def test_default_classify_is_unknown_never_guesses():
    key, conf, _ = StubProvider().classify_doc_type("anything")
    assert key == "unknown"
    assert conf == 0.0


def test_calls_are_recorded():
    stub = stub_for_path_report()
    stub.classify_doc_type("text")
    stub.extract("sys", "doc", PathologySchema)
    assert [c[0] for c in stub.calls] == ["classify_doc_type", "extract"]


def test_caught_variant_carries_proposed_value():
    stub = stub_for_path_report(caught=True)
    parsed, _ = stub.extract("sys", "doc", PathologySchema)
    assert parsed.lymph_nodes_positive.value == 2
    assert parsed.lymph_nodes_positive.source_span == "2 of 3 axillary nodes positive"


def test_factory_values_are_typed_not_display_strings():
    parsed, _ = stub_for_path_report().extract("sys", "doc", PathologySchema)
    assert parsed.tumor_size_cm.value == 1.4  # float, not "1.4 cm"
    intake, _ = stub_for_intake().extract("sys", "doc", IntakeSchema)
    assert intake.sex.value == "female"  # lowercase enum member, not "Female"
