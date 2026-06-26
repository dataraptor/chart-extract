"""ListField partial-grounding test — the §16 "k of n grounded" guarantee.

A multi-value field is grounded item-by-item: one bad item is flagged while the rest survive,
and the flattened names are ``field[i]``.
"""

from __future__ import annotations

from chartextract import Field, IntakeSchema, ListField, ground, ground_fields, load


def _intake_with_one_bad_medication() -> IntakeSchema:
    """An intake parse whose 2nd medication was fabricated (span not in the document)."""
    return IntakeSchema(
        patient_name=Field(value="Jane Doe", source_span="PATIENT: Jane Doe", confidence=0.97),
        dob=Field(value="1971-03-14", source_span="DOB: 1971-03-14", confidence=0.96),
        sex=Field(value="female", source_span="Sex: Female", confidence=0.95),
        chief_complaint=Field(
            value="Persistent cough", source_span="Persistent cough, 3 weeks", confidence=0.95
        ),
        medications=ListField(
            items=[
                Field(
                    value="Lisinopril 10 mg daily",
                    source_span="Lisinopril 10 mg daily",
                    confidence=0.95,
                ),
                # Fabricated — not in the document → must be caught, the others survive.
                Field(
                    value="Warfarin 5 mg daily", source_span="Warfarin 5 mg daily", confidence=0.9
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


def test_listfield_partial_grounding(intake_form_path):
    doc = load(intake_form_path)
    fields = ground_fields(_intake_with_one_bad_medication(), doc)
    by_name = {f.name: f for f in fields}

    # Flattened item names.
    assert "medications[0]" in by_name
    assert "medications[1]" in by_name
    assert "medications[2]" in by_name
    assert "allergies[0]" in by_name

    meds = [by_name[f"medications[{i}]"] for i in range(3)]
    # k of n grounded: item 0 and 2 survive as accepted; item 1 is caught.
    assert meds[0].flag is None and meds[0].value == "Lisinopril 10 mg daily"
    assert meds[2].flag is None and meds[2].value == "Atorvastatin 20 mg nightly"
    assert meds[1].flag == "not_grounded"
    assert meds[1].value is None
    assert meds[1].model_value == "Warfarin 5 mg daily"  # rejected proposal retained

    n_grounded = sum(1 for m in meds if m.value is not None)
    assert n_grounded == 2  # "2 of 3 grounded"


def test_listfield_offsets_index_real_text(intake_form_path):
    doc = load(intake_form_path)
    fields = ground_fields(_intake_with_one_bad_medication(), doc)
    for f in fields:
        if f.value is not None and f.char_start is not None:
            # Real-substring invariant: recorded offsets slice back into the canonical text and
            # reproduce exactly what `ground()` located for that span.
            assert 0 <= f.char_start <= f.char_end <= doc.n_chars
            expected = ground(f.source_span, doc.text)
            assert (
                doc.text[f.char_start : f.char_end]
                == doc.text[expected.char_start : expected.char_end]
            )
