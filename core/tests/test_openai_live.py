"""Live conformance proof for the GPT-5.5 provider (Tier-2, ``@pytest.mark.api``).

These call the real Azure OpenAI deployment and are **auto-skipped without a key**, so Tier-1 CI
stays green and free. To run them, export the credentials first, e.g.::

    set -a; source .env; set +a
    python -m pytest core/tests/test_openai_live.py -m api -v

They assert the **contract** — schema-valid result, no hallucinated value, real cost/latency — not
exact strings (the model's spans vary run to run; deterministic exactness lives in the stub tests).
"""

from __future__ import annotations

import os

import pytest

from chartextract import extract
from chartextract.provider.openai import OpenAIProvider

_HAS_KEY = bool(os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY"))

pytestmark = [
    pytest.mark.api,
    pytest.mark.skipif(not _HAS_KEY, reason="needs AZURE_OPENAI_API_KEY or OPENAI_API_KEY"),
]


def test_live_extract_path_report_no_hallucination(path_report_path) -> None:
    """The headline anti-hallucination check: the model must not invent a node count or a margin."""
    result = extract(path_report_path, schema="pathology", provider=OpenAIProvider())

    assert result.doc_type == "pathology"
    assert result.n_fields == 9
    assert result.model == "gpt-5.5"

    by_name = {f.name: f for f in result.fields}
    # lymph_nodes_positive is never mentioned → must be null, never a fabricated count.
    assert by_name["lymph_nodes_positive"].value is None
    assert by_name["lymph_nodes_positive"].flag in {"not_found", "not_grounded"}
    # "Margins not assessed on this specimen" → null (a cited absence), never a value.
    assert by_name["margin_status"].value is None
    assert by_name["margin_status"].flag in {"not_assessed", "not_found", "not_grounded"}
    # A value the model SHOULD get and ground (sanity that extraction actually worked).
    assert by_name["tumor_size_cm"].value == pytest.approx(1.4)
    assert by_name["tumor_size_cm"].char_start is not None


def test_live_cost_and_latency_are_real(path_report_path) -> None:
    result = extract(path_report_path, schema="pathology", provider=OpenAIProvider())
    assert result.cost_usd > 0
    assert result.latency_s > 0


def test_live_classify_doc_type_is_pathology(path_report_path) -> None:
    text = path_report_path.read_text(encoding="utf-8")
    key, conf, usage = OpenAIProvider().classify_doc_type(text)
    assert key == "pathology"
    assert conf >= 0.5
    assert usage.input_tokens > 0


def test_live_caching_breakdown_is_honest(path_report_path) -> None:
    """Split 11: the per-run token breakdown is real, and a sub-floor cache MISS is handled.

    The demo doc's prefix is well under GPT-5.5's ~1024-token caching floor, so a cache miss
    (``cache_read_tokens == 0``) is the *expected* outcome, asserted as handled — never a failure.
    Whatever the provider reports, the buckets must be non-negative and the fresh input must be > 0.
    """
    r1 = extract(path_report_path, schema="pathology", provider=OpenAIProvider())
    # Second call: the provider MAY now serve the prefix from cache (only if it cleared the floor).
    r2 = extract(path_report_path, schema="pathology", provider=OpenAIProvider())
    for r in (r1, r2):
        assert r.input_tokens > 0
        assert r.output_tokens > 0
        assert r.cache_read_tokens >= 0  # 0 (sub-floor miss) is fine — handled, not an error
        # cost prices both input buckets at the input rate; never understated.
        assert r.cost_usd > 0


@pytest.mark.skipif(
    not os.environ.get("CHARTEXTRACT_RUN_BATCH"),
    reason="live Batch API is async (minutes); set CHARTEXTRACT_RUN_BATCH=1 to run it",
)
def test_live_batch_sweep_reassociates_by_custom_id(path_report_path, intake_form_path) -> None:
    """A small live Batch sweep: results come back unordered and re-key by ``custom_id``.

    Opt-in (``CHARTEXTRACT_RUN_BATCH=1``) because the Batch API is asynchronous and can take several
    minutes. Proves the realized OpenAI batch path end-to-end: submit → poll → collect → collate.
    """
    from chartextract import BatchRequest, collate_results, run_openai_batch
    from chartextract.prompts import EXTRACTION_SYSTEM, extraction_user_content
    from chartextract.schemas import IntakeSchema, PathologySchema

    provider = OpenAIProvider()
    docs = [
        ("path", path_report_path.read_text(encoding="utf-8"), PathologySchema),
        ("intake", intake_form_path.read_text(encoding="utf-8"), IntakeSchema),
    ]
    requests = [
        BatchRequest(
            custom_id=cid,
            system=EXTRACTION_SYSTEM,
            document_text=extraction_user_content(text),
            schema_model=schema,
        )
        for cid, text, schema in docs
    ]
    results = run_openai_batch(provider, requests, poll_seconds=15.0)
    pairs = collate_results(requests, results)  # surfaces a missing id; re-orders by request
    assert [r.custom_id for r, _ in pairs] == ["path", "intake"]
    for req, (parsed, usage) in pairs:
        assert isinstance(parsed, req.schema_model)
        assert usage.input_tokens + usage.cache_read_input_tokens > 0
