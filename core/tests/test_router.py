"""Split 03 — document-type routing (router.py). Never silently guesses the schema."""

from __future__ import annotations

import pytest

from chartextract import (
    IntakeSchema,
    PathologySchema,
    StubProvider,
    UnknownDocTypeError,
    route,
)


def test_override_wins_and_skips_classifier():
    stub = StubProvider(classify_result=("intake", 0.9))  # would route to intake if consulted
    schema, key, conf = route("any text", "pathology", stub)
    assert schema is PathologySchema
    assert key == "pathology"
    assert conf == 1.0
    # classifier must NOT have been called when an override is given
    assert stub.calls == []


def test_classifier_routes_to_intake():
    stub = StubProvider(classify_result=("intake", 0.88))
    schema, key, conf = route("PATIENT INTAKE FORM ...", None, stub)
    assert schema is IntakeSchema
    assert key == "intake"
    assert conf == 0.88
    assert stub.calls[0][0] == "classify_doc_type"


def test_unknown_classification_raises_never_defaults():
    stub = StubProvider(classify_result=("unknown", 0.2))
    with pytest.raises(UnknownDocTypeError):
        route("mystery doc", None, stub)


def test_in_enum_but_no_schema_type_raises():
    # "discharge" is a valid classifier enum key but has no schema in v1 → surfaced, not a default.
    stub = StubProvider(classify_result=("discharge", 0.95))
    with pytest.raises(UnknownDocTypeError):
        route("discharge summary ...", None, stub)


def test_bad_override_raises_unknown_not_keyerror():
    stub = StubProvider(classify_result=("pathology", 0.9))
    with pytest.raises(UnknownDocTypeError):
        route("text", "discharge", stub)  # not in SCHEMAS
    # specifically NOT a bare KeyError
    try:
        route("text", "nonsense", stub)
    except UnknownDocTypeError:
        pass
    except KeyError:  # pragma: no cover
        pytest.fail("route leaked a raw KeyError instead of UnknownDocTypeError")
