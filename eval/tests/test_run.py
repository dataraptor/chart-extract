"""Scorer + leaderboard tests (spec §9 / §11, UIUX §5.5).

The scorer is a pure function over ``(GoldRecord, ExtractionResult)``, so the confusion-matrix maths
is checked against **hand-computed** expected values on canned results — no provider, deterministic.
Then the full stub run is checked for the 0-hallucination headline and byte-reproducibility.
"""

from __future__ import annotations

from chartextract import ExtractionResult, GroundedField
from eval.dataset import GoldRecord
from eval.run import (
    DocRecord,
    aggregate,
    build_oracle_instance,
    main,
    read_jsonl,
    run_suite,
    score_fields,
    write_jsonl,
)

PROV = dict(prompt_version="v3", normalize_version="v1")


def _gold(labels) -> GoldRecord:
    return GoldRecord(id="t", doc_type="pathology", doc="t.txt", split="tuning", labels=labels)


def _result(rows: list[GroundedField]) -> ExtractionResult:
    return ExtractionResult(
        doc_type="pathology",
        fields=rows,
        n_fields=len(rows),
        n_grounded=sum(1 for r in rows if r.value is not None),
        n_null=sum(1 for r in rows if r.value is None),
        n_needs_review=0,
        prompt_version="v3",
        schema_version="v2",
        model="claude-opus-4-8",
        cost_usd=0.0105,
    )


def _doc_record(
    record: GoldRecord, result: ExtractionResult, *, repeat=1, routing_ok=True
) -> DocRecord:
    return DocRecord(
        id=record.id,
        doc_type=record.doc_type,
        split=record.split,
        provider="stub",
        model="claude-opus-4-8",
        prompt_version="v3",
        normalize_version="v1",
        repeat=repeat,
        routing_pred=record.doc_type if routing_ok else "intake",
        routing_correct=routing_ok,
        scored=True,
        fields=score_fields(record, result),
        cost_usd=result.cost_usd,
    )


# A fixed labeled record reused across the scoring tests.
LABELS = {
    "specimen": {"value": "Left breast core biopsy", "span": "Left breast core biopsy"},
    "diagnosis": {"value": "Invasive ductal carcinoma", "span": "Invasive ductal carcinoma"},
    "grade": "2",
    "tumor_size_cm": "1.4 cm",
    "margin_status": {"empty": "not_assessed", "cite": "Margins not assessed"},
    "lymph_nodes_positive": {"empty": "not_found"},
}


def _by(scores):
    return {s.field: s for s in scores}


# --- per-field scoring: the confusion-matrix atoms ---


def test_all_correct_scores_tp_and_tn():
    record = _gold(LABELS)
    rows = [
        GroundedField(name="specimen", value="Left breast core biopsy", flag=None),
        GroundedField(name="diagnosis", value="Invasive ductal carcinoma", flag=None),
        GroundedField(name="grade", value="2", flag=None),
        GroundedField(name="tumor_size_cm", value=1.4, flag=None),
        GroundedField(name="margin_status", value=None, flag="not_assessed"),
        GroundedField(name="lymph_nodes_positive", value=None, flag="not_found"),
    ]
    s = _by(score_fields(record, _result(rows)))
    assert all(s[f].correct for f in s)
    assert s["specimen"].tp == 1 and s["tumor_size_cm"].tp == 1
    # the two empties are true negatives, NOT hallucinations, and their KIND matched
    assert s["margin_status"].tn == 1 and s["margin_status"].hallucinated == 0
    assert s["margin_status"].empty_kind_correct is True
    assert s["lymph_nodes_positive"].empty_kind_correct is True
    assert sum(f.hallucinated for f in s.values()) == 0


def test_not_assessed_match_is_correct_not_hallucination():
    record = _gold({"margin_status": {"empty": "not_assessed", "cite": "Margins not assessed"}})
    rows = [GroundedField(name="margin_status", value=None, flag="not_assessed")]
    s = _by(score_fields(record, _result(rows)))["margin_status"]
    assert s.correct and s.tn == 1 and s.hallucinated == 0


def test_non_null_against_null_gold_is_hallucination():
    record = _gold({"lymph_nodes_positive": {"empty": "not_found"}})
    rows = [
        GroundedField(name="lymph_nodes_positive", value=2, flag=None)
    ]  # the model invents a count
    s = _by(score_fields(record, _result(rows)))["lymph_nodes_positive"]
    assert not s.correct and s.hallucinated == 1 and s.fp == 1


def test_wrong_present_value_is_fp_and_fn_not_hallucination():
    record = _gold({"diagnosis": {"value": "Invasive ductal carcinoma", "span": "x"}})
    rows = [GroundedField(name="diagnosis", value="Lobular carcinoma", flag=None)]
    s = _by(score_fields(record, _result(rows)))["diagnosis"]
    assert not s.correct and s.fp == 1 and s.fn == 1 and s.hallucinated == 0


def test_missed_present_value_is_fn():
    record = _gold({"specimen": {"value": "Left breast core biopsy", "span": "x"}})
    rows = [GroundedField(name="specimen", value=None, flag="not_found")]
    s = _by(score_fields(record, _result(rows)))["specimen"]
    assert not s.correct and s.fn == 1 and s.tp == 0


def test_unit_conversion_scores_correct():
    record = _gold({"tumor_size_cm": "1.4 cm"})
    rows = [GroundedField(name="tumor_size_cm", value=1.4, flag=None)]  # "14 mm" → 1.4 in the doc
    assert _by(score_fields(record, _result(rows)))["tumor_size_cm"].tp == 1


def test_listfield_per_item_scoring():
    record = GoldRecord(
        id="i",
        doc_type="intake",
        doc="i.txt",
        labels={"medications": ["Lisinopril 10 mg daily", "Metformin 500 mg twice daily"]},
    )
    result = ExtractionResult(
        doc_type="intake",
        fields=[
            GroundedField(name="medications[0]", value="lisinopril 10 mg daily", flag=None),
            GroundedField(name="medications[1]", value="Aspirin 81 mg", flag=None),  # wrong item
        ],
        n_fields=2,
        n_grounded=2,
        n_null=0,
        n_needs_review=0,
        prompt_version="v3",
        schema_version="v2",
        model="claude-opus-4-8",
    )
    s = _by(score_fields(record, result))["medications"]
    assert (s.tp, s.fp, s.fn) == (1, 1, 1)


# --- aggregation: hand-computed leaderboard numbers ---


def test_aggregate_hand_computed_confusion_matrix():
    record = _gold(LABELS)
    # diagnosis wrong (fp+fn); lymph invented (hallucination); everything else correct.
    rows = [
        GroundedField(name="specimen", value="Left breast core biopsy", flag=None),
        GroundedField(name="diagnosis", value="Lobular carcinoma", flag=None),
        GroundedField(name="grade", value="2", flag=None),
        GroundedField(name="tumor_size_cm", value=1.4, flag=None),
        GroundedField(name="margin_status", value=None, flag="not_assessed"),
        GroundedField(name="lymph_nodes_positive", value=2, flag=None),
    ]
    lb = aggregate(
        [_doc_record(record, _result(rows))],
        n_docs=1,
        generated_at="20260627",
        provider="stub",
        repeats=1,
    )
    f1 = {m.field: m.f1 for m in lb.fields}
    # present fields: specimen/grade/tumor F1=1, diagnosis F1=0 → macro over support>0 = 0.75
    assert f1["specimen"] == 1.0 and f1["diagnosis"] == 0.0
    assert lb.macro_f1.mean == 0.75
    # null-gold fields = margin_status + lymph_nodes_positive = 2; one hallucinated → rate 0.5
    assert lb.hallucination_count == 1 and lb.n_null_gold == 2
    assert lb.hallucination_rate.mean == 0.5


def test_zero_hallucination_headline_on_all_correct():
    record = _gold(LABELS)
    rows = [
        GroundedField(name="specimen", value="Left breast core biopsy", flag=None),
        GroundedField(name="diagnosis", value="Invasive ductal carcinoma", flag=None),
        GroundedField(name="grade", value="2", flag=None),
        GroundedField(name="tumor_size_cm", value=1.4, flag=None),
        GroundedField(name="margin_status", value=None, flag="not_assessed"),
        GroundedField(name="lymph_nodes_positive", value=None, flag="not_found"),
    ]
    lb = aggregate(
        [_doc_record(record, _result(rows))],
        n_docs=1,
        generated_at="20260627",
        provider="stub",
        repeats=1,
    )
    assert lb.hallucination_count == 0
    assert lb.hallucination_rate.mean == 0.0
    assert lb.macro_f1.mean == 1.0


def test_routing_accuracy_against_gold_doc_type():
    rows = [GroundedField(name="grade", value="2", flag=None)]
    good = _doc_record(
        GoldRecord(id="g", doc_type="pathology", doc="g.txt", labels={"grade": "2"}),
        _result(rows),
        routing_ok=True,
    )
    bad = _doc_record(
        GoldRecord(id="b", doc_type="pathology", doc="b.txt", labels={"grade": "2"}),
        _result(rows),
        routing_ok=False,
    )
    # a routing-only discharge row (no fields, not scored), routed correctly
    discharge = DocRecord(
        id="d",
        doc_type="discharge",
        split="tuning",
        provider="stub",
        model="claude-opus-4-8",
        prompt_version="v3",
        normalize_version="v1",
        repeat=1,
        routing_pred="discharge",
        routing_correct=True,
        scored=False,
    )
    lb = aggregate([good, bad, discharge], n_docs=2, generated_at="x", provider="stub", repeats=1)
    assert lb.routing_accuracy == 2 / 3
    assert lb.n_routing_docs == 3


# --- the full stub run: determinism, reproducibility, partial honesty ---


def test_full_stub_run_zero_hallucination(gold_records):
    records, _ = run_suite(gold_records, provider_name="stub", repeats=1)
    lb = aggregate(
        records,
        n_docs=sum(1 for r in gold_records if r.labels),
        generated_at="20260627",
        provider="stub",
        repeats=1,
    )
    assert lb.hallucination_count == 0
    assert lb.macro_f1.mean == 1.0
    assert lb.routing_accuracy == 1.0
    assert lb.n_scored == lb.n_docs  # every labeled doc scored


def test_stub_run_is_reproducible(tmp_path, gold_records):
    r1, _ = run_suite(gold_records, provider_name="stub", repeats=2)
    r2, _ = run_suite(gold_records, provider_name="stub", repeats=2)
    p1 = write_jsonl(r1, tmp_path / "a.jsonl")
    p2 = write_jsonl(r2, tmp_path / "b.jsonl")
    assert p1.read_bytes() == p2.read_bytes()
    assert read_jsonl(p1) == read_jsonl(p2)


def test_distributional_spread_is_zero_on_stub(gold_records):
    records, _ = run_suite(gold_records, provider_name="stub", repeats=3)
    lb = aggregate(records, n_docs=15, generated_at="x", provider="stub", repeats=3)
    assert lb.macro_f1.spread == 0.0
    assert lb.hallucination_rate.spread == 0.0
    assert lb.macro_f1.n_repeats == 3


def test_partial_run_reports_k_of_n():
    record = _gold({"grade": "2"})
    rows = [GroundedField(name="grade", value="2", flag=None)]
    scored = _doc_record(record, _result(rows))
    errored = DocRecord(
        id="err",
        doc_type="pathology",
        split="tuning",
        provider="stub",
        model="claude-opus-4-8",
        prompt_version="v3",
        normalize_version="v1",
        repeat=1,
        routing_pred=None,
        routing_correct=False,
        scored=False,
        error="RefusalError: boom",
    )
    lb = aggregate([scored, errored], n_docs=2, generated_at="x", provider="stub", repeats=1)
    assert lb.n_scored == 1 and lb.n_docs == 2  # "1 of 2 scored", never a fabricated total


def test_oracle_instance_round_trips_through_real_grounding(gold_records):
    """The oracle replays a perfect extraction that the REAL grounding code accepts (no nulling)."""
    from chartextract import load
    from eval.dataset import load_doc_text
    from eval.run import score_fields as sf

    rec = next(r for r in gold_records if r.id == "path_00_worked_example")
    text = load_doc_text(rec)
    instance = build_oracle_instance(rec, text)
    from chartextract import ground_fields

    grounded = ground_fields(instance, load(text))
    result = _result(grounded)
    result.doc_type = "pathology"
    assert all(s.correct for s in sf(rec, result))


def test_main_writes_artifact_and_exits_zero(tmp_path):
    out = tmp_path / "lb.jsonl"
    code = main(["--provider", "stub", "--date", "20260627", "--out", str(out)])
    assert code == 0
    assert out.exists() and out.with_suffix(".txt").exists()
    rows = read_jsonl(out)
    assert len(rows) == 17  # every gold doc (incl. routing-only discharge) produced a row
