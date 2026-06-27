"""Split 11 — the eval Batch path scores identically to the sync path (Tier-1, no key).

The live OpenAI Batch submission is ``@pytest.mark.api``; here we inject a deterministic **oracle
batch_fn** (the same per-doc perfect extraction the stub sweep replays, but returned as one
unordered batch) and assert that ``run_suite_batch`` re-associates by ``custom_id`` and produces
**byte-identical field scores** to ``run_suite``. The only intended difference is cost — billed at
the 50% batch discount.
"""

from __future__ import annotations

from chartextract import SCHEMAS, BatchRequest
from eval.dataset import GOLD_DIR, load_doc_text
from eval.run import (
    REF_USAGE,
    aggregate,
    build_oracle_instance,
    run_suite,
    run_suite_batch,
)


def _oracle_batch_fn(records, root):
    """A batch backend that replays the gold oracle — returned **unordered** to prove re-keying."""
    by_id = {r.id: r for r in records}

    def batch_fn(requests: list[BatchRequest]):
        out = {}
        for req in requests:
            rec = by_id[req.custom_id]
            text = load_doc_text(rec, root=root)
            parsed = build_oracle_instance(rec, text)
            out[req.custom_id] = (parsed, REF_USAGE)
        # Hand them back in REVERSED order: a dict is keyed by id, so order must not matter.
        return dict(reversed(list(out.items())))

    return batch_fn


def test_batch_field_scores_equal_sync(gold_records):
    root = GOLD_DIR
    sync, _ = run_suite(gold_records, provider_name="stub", repeats=1, root=root)
    batch, _ = run_suite_batch(
        gold_records,
        repeats=1,
        batch_fn=_oracle_batch_fn(gold_records, root),
        model="claude-opus-4-8",
        root=root,
    )

    sync_by_id = {r.id: r for r in sync}
    # Every schema-bearing doc the batch scored must have identical FieldScores to the sync run.
    scored_ids = [r.id for r in batch]
    assert scored_ids, "batch produced no scored docs"
    for br in batch:
        sr = sync_by_id[br.id]
        assert br.fields == sr.fields, f"field scores diverged for {br.id}"
        assert br.scored == sr.scored


def test_batch_reassociates_unordered_results(gold_records):
    batch, _ = run_suite_batch(
        gold_records,
        repeats=1,
        batch_fn=_oracle_batch_fn(gold_records, GOLD_DIR),
        model="claude-opus-4-8",
        root=GOLD_DIR,
    )
    # Despite the reversed batch order, each record has the RIGHT doc's fields (zero hallucinated).
    halluc = sum(fs.hallucinated for r in batch for fs in r.fields)
    assert halluc == 0
    # only schema-bearing (pathology/intake) docs are batched.
    assert all(r.doc_type in SCHEMAS for r in batch)


def test_batch_cost_is_half_the_sync_cost(gold_records):
    sync, _ = run_suite(gold_records, provider_name="stub", repeats=1, root=GOLD_DIR)
    batch, _ = run_suite_batch(
        gold_records,
        repeats=1,
        batch_fn=_oracle_batch_fn(gold_records, GOLD_DIR),
        model="claude-opus-4-8",
        root=GOLD_DIR,
    )
    sync_by_id = {r.id: r for r in sync}
    for br in batch:
        sr = sync_by_id[br.id]
        if sr.cost_usd > 0:
            assert abs(br.cost_usd - sr.cost_usd * 0.5) < 1e-12


def test_measured_cost_row_only_on_live_runs(gold_records):
    batch, _ = run_suite_batch(
        gold_records,
        repeats=1,
        batch_fn=_oracle_batch_fn(gold_records, GOLD_DIR),
        model="claude-opus-4-8",
        root=GOLD_DIR,
    )
    n_docs = sum(1 for r in gold_records if r.labels)
    # A non-stub provider name adds the MEASURED row (the run's own model); estimates stay labeled.
    lb = aggregate(batch, n_docs=n_docs, generated_at="x", provider="openai-batch", repeats=1)
    measured_rows = [c for c in lb.cost_rows if c.measured]
    estimate_rows = [c for c in lb.cost_rows if not c.measured]
    assert len(measured_rows) == 1
    assert measured_rows[0].model == "claude-opus-4-8"  # the batch's model in this test
    assert {c.model for c in estimate_rows} == {"claude-opus-4-8", "claude-sonnet-4-6"} or len(
        estimate_rows
    ) >= 2

    # A stub run adds NO measured row — never present an estimate as measured.
    sync, _ = run_suite(gold_records, provider_name="stub", repeats=1, root=GOLD_DIR)
    lb_stub = aggregate(sync, n_docs=n_docs, generated_at="x", provider="stub", repeats=1)
    assert all(not c.measured for c in lb_stub.cost_rows)
