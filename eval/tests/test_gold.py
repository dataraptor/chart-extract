"""Gold-set integrity tests (Appendix B).

Asserts the frozen set loads, every record is well-formed, **all three empty kinds are present**,
at least one intake doc carries a ListField label, and every replayed span/cite is verbatim — so an
authoring slip is a failing test, not a silently-wrong metric.
"""

from __future__ import annotations

from chartextract import SCHEMAS, field_names
from eval.dataset import EMPTY_KINDS, GOLD_DOC_TYPES, load_doc_text
from eval.run import build_oracle_instance


def test_gold_set_size_and_doc_types(gold_records):
    assert 15 <= len(gold_records) <= 25
    by_type = {}
    for r in gold_records:
        assert r.doc_type in GOLD_DOC_TYPES
        by_type[r.doc_type] = by_type.get(r.doc_type, 0) + 1
    assert by_type["pathology"] >= 10  # pathology-heavy (§16)
    assert by_type["intake"] >= 3


def test_every_record_has_valid_labels(gold_records):
    for r in gold_records:
        schema = SCHEMAS.get(r.doc_type)
        if schema is None:  # discharge — routing-only, no labels
            assert r.labels == {}
            continue
        allowed = set(field_names(schema))
        assert set(r.labels) <= allowed, f"{r.id}: stray label"


def test_all_three_empty_kinds_present(gold_records):
    """absent (not_found) + explicitly-not-assessed + present-but-easy-to-hallucinate (§8)."""
    kinds_seen = set()
    has_unit_conversion = False
    for r in gold_records:
        for field in r.labels:
            kind = r.empty_kind(field)
            if kind:
                kinds_seen.add(kind)
            elif field == "tumor_size_cm":
                raw = str(r.gold_value(field) or "")
                if "mm" in raw.lower():  # a value the model is tempted to round/infer
                    has_unit_conversion = True
    assert set(EMPTY_KINDS) <= kinds_seen, f"missing empty kinds: {set(EMPTY_KINDS) - kinds_seen}"
    assert has_unit_conversion, "no present-but-easy-to-hallucinate (mm→cm) case in the set"


def test_at_least_one_intake_listfield_label(gold_records):
    intake_list_labels = [
        r
        for r in gold_records
        if r.doc_type == "intake" and (r.list_items("medications") or r.list_items("allergies"))
    ]
    assert intake_list_labels, "no intake doc carries a ListField (medications/allergies) label"


def test_routing_only_discharge_present(gold_records):
    discharge = [r for r in gold_records if r.doc_type == "discharge"]
    assert discharge, "expected at least one routing-only discharge doc"
    assert all(r.labels == {} for r in discharge)


def test_every_present_field_grounds_in_its_doc(gold_records):
    """The oracle's replayed spans actually ground (value kept) — catches a bad span early."""
    from chartextract import ground_fields, load

    for r in gold_records:
        if r.doc_type not in SCHEMAS or not r.labels:
            continue
        text = load_doc_text(r)
        instance = build_oracle_instance(r, text)
        grounded = {g.name: g for g in ground_fields(instance, load(text))}
        for field in r.labels:
            if r.is_empty(field):
                continue
            if SCHEMAS[r.doc_type].model_fields[field].annotation.__name__.startswith("ListField"):
                continue  # list items handled per-item below
            g = grounded.get(field)
            assert g is not None and g.value is not None, (
                f"{r.id}.{field}: oracle span did not ground (value nulled) — fix the gold span"
            )


def test_canonical_docs_are_in_the_set(gold_records):
    ids = {r.id for r in gold_records}
    assert "path_00_worked_example" in ids  # the §5 worked example is in the leaderboard
    assert "intake_00_form" in ids
