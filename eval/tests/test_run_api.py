"""Live provider sweep (opt-in, ``-m api``) — auto-skips without a key, never fails CI.

Runs a small slice of the gold set against the **live** provider (Azure GPT-5.5) through the same
``run_suite`` the leaderboard uses, proving the harness scores a real model end-to-end. It asserts
structure (every doc scored, routing correct, the report exists), not exact numbers — live output is
distributional, so the leaderboard reports it, the test does not pin it.
"""

from __future__ import annotations

import pytest

from chartextract import live_key_present
from eval.run import _load_dotenv, aggregate, run_suite

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _require_key():
    _load_dotenv()
    if not live_key_present():
        pytest.skip("no live provider key (set OPENAI_API_KEY / AZURE_OPENAI_* to run -m api)")


def test_live_sweep_pathology(gold_records):
    """The pathology slice scores end-to-end on the live model (routing + grounding + pricing)."""
    subset = [r for r in gold_records if r.id in {"path_00_worked_example", "path_09_sparse"}]
    records, latencies = run_suite(subset, provider_name="openai", repeats=1)
    lb = aggregate(records, n_docs=len(subset), generated_at="live", provider="openai", repeats=1)

    assert lb.n_scored == len(subset)  # both pathology docs produced a scored result
    assert all(r.routing_correct for r in records)  # classifier routed pathology correctly
    assert lb.measured_cost_per_doc > 0  # a real, priced GPT-5.5 cost
    assert all(latency > 0 for latency in latencies)


def test_live_error_surfaced_not_crashed(gold_records):
    """A live provider/schema failure is surfaced as a clean error row, never a crash (§15).

    (Known core finding, carried to the next split: ``strict_json_schema(IntakeSchema)`` currently
    emits an invalid ``ListField`` item schema, so live intake 400s. The harness must still produce
    a row for that doc and report it as not-scored rather than blow up.)
    """
    subset = [r for r in gold_records if r.id == "intake_00_form"]
    records, _ = run_suite(subset, provider_name="openai", repeats=1)
    assert len(records) == 1  # a row exists for every doc, even on provider failure
    rec = records[0]
    assert rec.scored or rec.error is not None  # scored, or honestly flagged as errored
