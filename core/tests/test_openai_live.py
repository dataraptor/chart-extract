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
