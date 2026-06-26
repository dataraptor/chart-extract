"""Normalizer + match-predicate tests (spec §9 — the comparison contract).

These exercise the four per-type normalizers (string / numeric / enum / list) and the empty-matching
rules the scorer relies on, with no provider involved.
"""

from __future__ import annotations

import pytest

from chartextract import IntakeSchema, PathologySchema
from eval.normalize import (
    NORMALIZE_VERSION,
    enum_members,
    infer_field_type,
    list_item_counts,
    normalize_enum,
    normalize_string,
    numeric_is_integer,
    numeric_match,
    parse_measure,
    scalar_match,
)


def test_normalize_version_pinned():
    assert NORMALIZE_VERSION == "v1"


# --- field-type inference is derived from the schema, not hand-maintained ---


def test_infer_field_types_pathology():
    assert infer_field_type(PathologySchema, "specimen") == "string"
    assert infer_field_type(PathologySchema, "tumor_size_cm") == "numeric"
    assert infer_field_type(PathologySchema, "lymph_nodes_positive") == "numeric"
    assert infer_field_type(PathologySchema, "er_status") == "enum"
    assert numeric_is_integer(PathologySchema, "lymph_nodes_positive") is True
    assert numeric_is_integer(PathologySchema, "tumor_size_cm") is False
    assert set(enum_members(PathologySchema, "er_status")) == {"positive", "negative", "unknown"}


def test_infer_field_types_intake():
    assert infer_field_type(IntakeSchema, "medications") == "list"
    assert infer_field_type(IntakeSchema, "allergies") == "list"
    assert infer_field_type(IntakeSchema, "sex") == "enum"
    assert infer_field_type(IntakeSchema, "patient_name") == "string"


# --- string ---


def test_string_fold_and_whitespace_collapse():
    assert normalize_string("  Invasive   Ductal\nCarcinoma  ") == "invasive ductal carcinoma"
    assert scalar_match("string", "Jane Doe", "jane   doe", field_name="patient_name")
    assert not scalar_match("string", "Jane Doe", "John Doe", field_name="patient_name")


# --- numeric: unit conversion to the field's canonical unit ---


@pytest.mark.parametrize(
    "raw,expected",
    [("14 mm", 1.4), ("1.4 cm", 1.4), ("1.4", 1.4), (1.4, 1.4), ("8 mm", 0.8), ("0.85 m", 85.0)],
)
def test_parse_measure_to_cm(raw, expected):
    assert parse_measure(raw, "tumor_size_cm") == pytest.approx(expected)


def test_numeric_match_14mm_equals_1p4cm():
    # The headline normalizer case: "14 mm" must equal "1.4 cm" after conversion.
    assert numeric_match("14 mm", "1.4 cm", "tumor_size_cm")
    assert numeric_match("14 mm", 1.4, "tumor_size_cm")
    assert not numeric_match("14 mm", "1.5 cm", "tumor_size_cm")


def test_numeric_count_field_is_unitless():
    assert parse_measure("3", "lymph_nodes_positive") == 3.0
    assert numeric_match("3", 3, "lymph_nodes_positive")
    assert numeric_match("0", 0, "lymph_nodes_positive")  # a real zero is a present value


def test_parse_measure_rejects_non_numeric():
    with pytest.raises(ValueError):
        parse_measure("not a number", "tumor_size_cm")


# --- enum: synonym → canonical member ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ER+", "positive"),
        ("PR+", "positive"),
        ("HER2+", "positive"),
        ("ER positive (90%)", "positive"),
        ("negative", "negative"),
        ("HER2 negative", "negative"),
        ("equivocal", "unknown"),
        ("Female", "female"),
        ("M", "male"),
    ],
)
def test_enum_synonyms(raw, expected):
    members = ("positive", "negative", "unknown", "male", "female", "other")
    assert normalize_enum(raw, members) == expected


def test_enum_match_via_normalizer():
    members = enum_members(PathologySchema, "er_status")
    assert scalar_match("enum", "ER+", "positive", field_name="er_status", members=members)
    assert not scalar_match("enum", "ER+", "negative", field_name="er_status", members=members)


# --- list: set-match with per-item TP/FP/FN ---


def test_list_item_counts_set_match():
    gold = ["Lisinopril 10 mg daily", "Metformin 500 mg twice daily", "Atorvastatin 20 mg nightly"]
    pred = ["lisinopril 10 mg daily", "metformin 500 mg twice daily"]  # missed one, case-folded
    tp, fp, fn = list_item_counts(gold, pred)
    assert (tp, fp, fn) == (2, 0, 1)


def test_list_item_counts_extra_item_is_fp():
    tp, fp, fn = list_item_counts(["Penicillin"], ["Penicillin", "Sulfa"])
    assert (tp, fp, fn) == (1, 1, 0)


def test_list_empty_collections():
    assert list_item_counts([], []) == (0, 0, 0)
    assert list_item_counts(None, ["x"]) == (0, 1, 0)
