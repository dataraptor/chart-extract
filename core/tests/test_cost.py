"""Split 03 — token-bucket usage + per-model pricing (cost.py)."""

from __future__ import annotations

import math

import pytest

from chartextract import BATCH_DISCOUNT, PRICING, Usage, price, price_batch


def test_pricing_reconciled_with_claude_api_reference():
    # Split 11: pricing pinned against the claude-api skill. Per MTok (input / output).
    assert PRICING["claude-opus-4-8"] == {"input": 5 / 1e6, "output": 25 / 1e6}
    assert PRICING["claude-sonnet-4-6"] == {"input": 3 / 1e6, "output": 15 / 1e6}
    # Haiku corrected from the Split 03/04 placeholder $0.80/$4 → $1.00/$5.00 (reference wins).
    assert PRICING["claude-haiku-4-5-20251001"] == {"input": 1.00 / 1e6, "output": 5 / 1e6}
    assert PRICING["gpt-5.5"] == {"input": 1.25 / 1e6, "output": 10 / 1e6}


def test_no_stale_haiku_todo_value():
    # The wrong 0.80 input rate must be gone (gate row 7: Split 03/04 TODOs resolved).
    assert PRICING["claude-haiku-4-5-20251001"]["input"] != 0.80 / 1e6


def test_batch_discount_is_half():
    assert BATCH_DISCOUNT == 0.5


def test_price_batch_is_half_of_sync():
    usage = Usage(input_tokens=1200, output_tokens=180)
    assert math.isclose(price_batch(usage, "gpt-5.5"), price(usage, "gpt-5.5") * 0.5, rel_tol=1e-9)


def test_sonnet_cost_delta_vs_opus_is_correct():
    # The UIUX §5.5 "down N% cost" delta: Sonnet vs Opus on the same reference usage.
    usage = Usage(input_tokens=1200, output_tokens=180)
    opus = price(usage, "claude-opus-4-8")
    sonnet = price(usage, "claude-sonnet-4-6")
    delta_pct = 100.0 * (opus - sonnet) / opus
    # opus = 1200*5 + 180*25 = 10500e-6 = 0.0105 ; sonnet = 1200*3 + 180*15 = 6300e-6 = 0.0063
    assert math.isclose(opus, 0.0105, rel_tol=1e-9)
    assert math.isclose(sonnet, 0.0063, rel_tol=1e-9)
    assert math.isclose(delta_pct, 40.0, rel_tol=1e-9)


def test_price_opus_matches_hand_computed():
    # 1000 input @ $5/MTok + 200 output @ $25/MTok = 0.005 + 0.005 = 0.010
    usage = Usage(input_tokens=1000, output_tokens=200)
    assert math.isclose(price(usage, "claude-opus-4-8"), 0.010, rel_tol=1e-9)


def test_price_counts_cache_reads_at_input_rate():
    # cache_read_input_tokens bill at the input rate (no separate read multiplier in v1).
    base = price(Usage(input_tokens=1000, output_tokens=0), "claude-opus-4-8")
    cached = price(
        Usage(input_tokens=1000, cache_read_input_tokens=1000, output_tokens=0), "claude-opus-4-8"
    )
    assert math.isclose(cached, 2 * base, rel_tol=1e-9)


def test_price_sonnet_distinct_from_opus():
    usage = Usage(input_tokens=1_000_000, output_tokens=0)
    assert math.isclose(price(usage, "claude-sonnet-4-6"), 3.0, rel_tol=1e-9)
    assert math.isclose(price(usage, "claude-opus-4-8"), 5.0, rel_tol=1e-9)


def test_usage_adds_bucket_wise():
    a = Usage(input_tokens=10, output_tokens=5, cache_read_input_tokens=2)
    b = Usage(input_tokens=1, output_tokens=2, cache_read_input_tokens=3)
    total = a + b
    assert (total.input_tokens, total.output_tokens, total.cache_read_input_tokens) == (11, 7, 5)


def test_usage_sum_starts_from_zero():
    usages = [Usage(input_tokens=1), Usage(input_tokens=2), Usage(input_tokens=3)]
    assert sum(usages, Usage()).input_tokens == 6
    # bare sum() (starts at int 0) works via __radd__
    assert sum(usages).input_tokens == 6


def test_unknown_model_raises_never_silent_zero():
    with pytest.raises(KeyError):
        price(Usage(input_tokens=10), "gpt-imaginary")


def test_all_pinned_models_priceable():
    for model in PRICING:
        assert price(Usage(input_tokens=1, output_tokens=1), model) >= 0.0


def test_usage_add_non_usage_returns_notimplemented():
    # Adding a non-Usage yields NotImplemented (so Python raises TypeError, not a silent bad sum).
    assert Usage().__add__(5) is NotImplemented
    with pytest.raises(TypeError):
        _ = Usage() + 5
