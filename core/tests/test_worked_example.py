"""The §5 worked example — the headline test (spec §5/§11).

Feeds the recorded model output for ``examples/path_report.txt`` (transcribed by hand from the §5
table and the ``pathDefs()`` tuples in ``app/ChartExtract.dc.html``) through the grounding + flag
engine and asserts the full table verbatim — including the demo's two **distinctly** flagged nulls
(``margin_status`` → ``not_assessed`` vs ``lymph_nodes_positive`` → ``not_found``) and the caught-
hallucination variant.

Also cross-checks the engine against the JS reference: the expected flags/confidence here are
exactly what ``grounded()`` produces for the same ``(value, source_span, mc)`` inputs.
"""

from __future__ import annotations

from chartextract import (
    Field,
    IntakeSchema,
    ListField,
    PathologySchema,
    ground_fields,
    load,
)


def _pathology(*, caught: bool = False) -> PathologySchema:
    """Recorded model output for the pathology report (typed/enum-valid, per the §5 table)."""
    lymph = (
        Field(value=2, source_span="2 of 3 axillary nodes positive", confidence=0.71)
        if caught
        else Field(value=None, source_span="", confidence=0.0)
    )
    return PathologySchema(
        specimen=Field(
            value="Left breast core biopsy", source_span="Left breast core biopsy", confidence=0.96
        ),
        diagnosis=Field(
            value="Invasive ductal carcinoma",
            source_span="Invasive ductal carcinoma, grade 2",
            confidence=0.93,
        ),
        grade=Field(value="2", source_span="grade 2", confidence=0.9),
        tumor_size_cm=Field(value=1.4, source_span="Tumor size 1.4 cm", confidence=0.95),
        er_status=Field(value="positive", source_span="ER positive (90%)", confidence=0.94),
        pr_status=Field(value="positive", source_span="PR positive (40%)", confidence=0.92),
        her2_status=Field(value="negative", source_span="HER2 negative", confidence=0.93),
        margin_status=Field(
            value=None, source_span="Margins not assessed on this specimen", confidence=0.0
        ),
        lymph_nodes_positive=lymph,
    )


# The §5 table verbatim: (name, value, flag, match_quality).
WORKED_EXAMPLE = [
    ("specimen", "Left breast core biopsy", None, "exact"),
    ("diagnosis", "Invasive ductal carcinoma", None, "exact"),
    ("grade", "2", None, "exact"),
    ("tumor_size_cm", 1.4, None, "exact"),
    ("er_status", "positive", None, "exact"),
    ("pr_status", "positive", None, "exact"),
    ("her2_status", "negative", None, "exact"),
    ("margin_status", None, "not_assessed", "exact"),
    ("lymph_nodes_positive", None, "not_found", "none"),
]


def test_worked_example_reproduces_section5_table_exactly(path_report_path):
    doc = load(path_report_path)
    fields = ground_fields(_pathology(), doc)
    by_name = {f.name: f for f in fields}

    assert [f.name for f in fields] == [row[0] for row in WORKED_EXAMPLE]

    for name, value, flag, quality in WORKED_EXAMPLE:
        gf = by_name[name]
        assert gf.value == value, name
        assert gf.flag == flag, name
        assert gf.match_quality == quality, name


def test_the_two_nulls_are_distinctly_flagged(path_report_path):
    # The demo: a cited absence is NOT the same as a silent one.
    doc = load(path_report_path)
    by_name = {f.name: f for f in ground_fields(_pathology(), doc)}
    assert by_name["margin_status"].flag == "not_assessed"
    assert by_name["lymph_nodes_positive"].flag == "not_found"
    assert by_name["margin_status"].flag != by_name["lymph_nodes_positive"].flag


def test_offsets_index_real_text_for_every_grounded_field(path_report_path):
    doc = load(path_report_path)
    for f in ground_fields(_pathology(), doc):
        if f.value is not None:
            assert f.char_start is not None and f.char_end is not None
            # All worked-example spans are exact matches, so the slice equals the span verbatim.
            assert 0 <= f.char_start <= f.char_end <= doc.n_chars
            assert doc.text[f.char_start : f.char_end] == f.source_span
        else:
            assert f.char_start is None and f.char_end is None


def test_show_caught_variant_catches_hallucination(path_report_path):
    # The "Show caught" toggle: lymph_nodes_positive proposed 2 with a span not in the text.
    doc = load(path_report_path)
    by_name = {f.name: f for f in ground_fields(_pathology(caught=True), doc)}
    lymph = by_name["lymph_nodes_positive"]
    assert lymph.flag == "not_grounded"
    assert lymph.value is None
    assert lymph.model_value == 2  # the rejected proposal is retained for the UI disclosure
    assert lymph.confidence == 0.0


def _intake() -> IntakeSchema:
    """Recorded model output for the intake form (transcribed from ``intakeDefs()``)."""
    return IntakeSchema(
        patient_name=Field(value="Jane Doe", source_span="PATIENT: Jane Doe", confidence=0.97),
        dob=Field(value="1971-03-14", source_span="DOB: 1971-03-14", confidence=0.96),
        sex=Field(value="female", source_span="Sex: Female", confidence=0.95),
        chief_complaint=Field(
            value="Persistent cough", source_span="Persistent cough, 3 weeks", confidence=0.55
        ),
        medications=ListField(
            items=[
                Field(
                    value="Lisinopril 10 mg daily",
                    source_span="Lisinopril 10 mg daily",
                    confidence=0.95,
                ),
                Field(
                    value="Metformin 500 mg twice daily",
                    source_span="Metformin 500 mg twice daily",
                    confidence=0.94,
                ),
                Field(
                    value="Atorvastatin 20 mg nightly",
                    source_span="Atorvastatin 20 mg nightly",
                    confidence=0.93,
                ),
            ]
        ),
        allergies=ListField(
            items=[Field(value="Penicillin", source_span="Penicillin (rash)", confidence=0.94)]
        ),
        pcp=Field(value=None, source_span="", confidence=0.0),
    )


def test_intake_cross_check_matches_js_reference(intake_form_path):
    # Expected flags are exactly what grounded() produces for intakeDefs(): chief_complaint is
    # needs_review (mc 0.55 < τ), pcp is not_found (empty span), the rest accepted.
    doc = load(intake_form_path)
    by_name = {f.name: f for f in ground_fields(_intake(), doc)}
    expected = {
        "patient_name": None,
        "dob": None,
        "sex": None,
        "chief_complaint": "needs_review",
        "medications[0]": None,
        "medications[1]": None,
        "medications[2]": None,
        "allergies[0]": None,
        "pcp": "not_found",
    }
    assert {n: by_name[n].flag for n in expected} == expected
    # Footer-count parity (UIUX): 8 grounded · 1 null · 1 review.
    n_grounded = sum(1 for f in by_name.values() if f.value is not None)
    n_null = sum(1 for f in by_name.values() if f.value is None)
    n_review = sum(1 for f in by_name.values() if f.flag in ("needs_review", "ambiguous_span"))
    assert (n_grounded, n_null, n_review) == (8, 1, 1)


def test_pathology_cross_check_footer_counts(path_report_path):
    # Footer-count parity for the path stub: 7 grounded · 2 null · 0 review.
    doc = load(path_report_path)
    fields = ground_fields(_pathology(), doc)
    n_grounded = sum(1 for f in fields if f.value is not None)
    n_null = sum(1 for f in fields if f.value is None)
    n_review = sum(1 for f in fields if f.flag in ("needs_review", "ambiguous_span"))
    assert (n_grounded, n_null, n_review) == (7, 2, 0)
