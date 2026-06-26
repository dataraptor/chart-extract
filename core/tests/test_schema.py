"""Split 01 — the data contract: type enforcement, enum bounds, stable field order."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chartextract import (
    SCHEMA_VERSION,
    SCHEMAS,
    ExtractionResult,
    Field,
    GroundedField,
    IntakeSchema,
    ListField,
    PathologySchema,
    field_names,
)

# --- valid construction + extra="forbid" -----------------------------------


def _valid_pathology() -> PathologySchema:
    return PathologySchema(
        specimen=Field[str](value="Left breast core biopsy", source_span="x", confidence=0.9),
        diagnosis=Field[str](value="IDC", source_span="x", confidence=0.9),
        grade=Field[str](value="2", source_span="grade 2", confidence=0.9),
        tumor_size_cm=Field[float](value=1.4, source_span="1.4 cm", confidence=0.9),
        er_status=Field(value="positive", source_span="ER positive", confidence=0.9),
        pr_status=Field(value="positive", source_span="PR positive", confidence=0.9),
        her2_status=Field(value="negative", source_span="HER2 negative", confidence=0.9),
        margin_status=Field(value=None, confidence=0.0),
        lymph_nodes_positive=Field[int](value=None, confidence=0.0),
    )


def test_pathology_valid_instance() -> None:
    schema = _valid_pathology()
    assert schema.tumor_size_cm.value == 1.4
    assert schema.er_status.value == "positive"


def test_intake_valid_instance() -> None:
    schema = IntakeSchema(
        patient_name=Field[str](value="Jane Doe", source_span="Jane Doe", confidence=0.97),
        dob=Field[str](value="1971-03-14", source_span="1971-03-14", confidence=0.96),
        sex=Field(value="female", source_span="Female", confidence=0.95),
        chief_complaint=Field[str](value="cough", source_span="cough", confidence=0.6),
        medications=ListField(
            items=[Field(value="Lisinopril 10 mg daily", source_span="Lisinopril", confidence=0.9)]
        ),
        allergies=ListField(
            items=[Field(value="Penicillin", source_span="Penicillin", confidence=0.9)]
        ),
        pcp=Field[str](value=None, confidence=0.0),
    )
    assert schema.medications.items[0].value == "Lisinopril 10 mg daily"


def test_extra_key_rejected() -> None:
    with pytest.raises(ValidationError):
        PathologySchema(
            **_valid_pathology().model_dump(),
            surprise=Field[str](value="x", confidence=0.1),
        )


# --- Field[T] type enforcement ----------------------------------------------


def test_float_field_accepts_float_and_none_rejects_string() -> None:
    assert Field[float](value=1.4, confidence=0.9).value == 1.4
    assert Field[float](value=None, confidence=0.0).value is None
    with pytest.raises(ValidationError):
        Field[float](value="big", confidence=0.9)


def test_enum_field_accepts_members_and_none_rejects_other() -> None:
    for member in ("positive", "negative", "unknown"):
        assert PathologySchema.model_fields  # schema importable
        f = Field[str](value=member, confidence=0.9)
        assert f.value == member
    # er_status is a 3-way enum + None; an out-of-enum value is rejected by the schema.
    base = _valid_pathology().model_dump()
    base["er_status"] = {"value": "maybe", "source_span": "", "confidence": 0.9}
    with pytest.raises(ValidationError):
        PathologySchema(**base)


def test_er_status_accepts_none() -> None:
    base = _valid_pathology().model_dump()
    base["er_status"] = {"value": None, "source_span": "", "confidence": 0.0}
    assert PathologySchema(**base).er_status.value is None


# --- ListField round-trip ---------------------------------------------------


def test_listfield_items_carry_own_spans() -> None:
    lf = ListField(
        items=[
            Field(value="a", source_span="span-a", confidence=0.9),
            Field(value="b", source_span="span-b", confidence=0.8),
        ]
    )
    dumped = ListField.model_validate(lf.model_dump())
    assert [i.source_span for i in dumped.items] == ["span-a", "span-b"]


# --- GroundedField / ExtractionResult ---------------------------------------


def test_grounded_field_defaults() -> None:
    gf = GroundedField(name="grade", value="2", source_span="grade 2")
    assert gf.flag is None
    assert gf.match_quality == "none"
    assert gf.char_start is None
    assert gf.model_value is None


def test_extraction_result_validates() -> None:
    result = ExtractionResult(
        doc_type="pathology",
        fields=[GroundedField(name="grade", value="2")],
        n_fields=1,
        n_grounded=1,
        n_null=0,
        n_needs_review=0,
        prompt_version="p1",
        schema_version=SCHEMA_VERSION,
        model="stub",
    )
    assert result.schema_version == "v2"
    assert result.fields[0].name == "grade"


# --- field_names ordering + SCHEMAS registry --------------------------------


def test_field_names_pathology_order() -> None:
    assert field_names(PathologySchema) == [
        "specimen",
        "diagnosis",
        "grade",
        "tumor_size_cm",
        "er_status",
        "pr_status",
        "her2_status",
        "margin_status",
        "lymph_nodes_positive",
    ]


def test_field_names_intake_order() -> None:
    assert field_names(IntakeSchema) == [
        "patient_name",
        "dob",
        "sex",
        "chief_complaint",
        "medications",
        "allergies",
        "pcp",
    ]


def test_schemas_registry_keys() -> None:
    assert set(SCHEMAS.keys()) == {"pathology", "intake"}
    assert SCHEMAS["pathology"] is PathologySchema
    assert SCHEMAS["intake"] is IntakeSchema
