"""§8 structural-confidence tests — the model's number is an input, never trusted alone."""

from __future__ import annotations

import pytest

from chartextract import MATCH_WEIGHT, TAU, structural_confidence
from chartextract.confidence import nonspace_len


def test_prefix_caps_confidence_below_tau_even_with_high_model_conf():
    # The model reported 0.99, but only a prefix matched → structural confidence caps at 0.5,
    # which is below τ=0.6. Proves §8: a weak match overrides a confident-sounding model.
    conf = structural_confidence(0.99, "prefix")
    assert conf == 0.5
    assert conf < TAU


def test_exact_high_conf_passes_tau():
    conf = structural_confidence(0.94, "exact")
    assert conf == 0.94
    assert conf >= TAU


def test_whitespace_weight_applied():
    # weight(whitespace)=0.92 caps a higher model number.
    assert structural_confidence(0.95, "whitespace") == 0.92
    # ...but does not raise a lower one.
    assert structural_confidence(0.5, "whitespace") == 0.5


def test_none_match_zero_confidence():
    assert structural_confidence(0.99, "none") == 0.0


@pytest.mark.parametrize(
    "quality,weight",
    [("exact", 1.0), ("whitespace", 0.92), ("prefix", 0.5), ("none", 0.0)],
)
def test_match_weight_table_matches_js_reference(quality, weight):
    assert MATCH_WEIGHT[quality] == weight


def test_nonspace_len():
    assert nonspace_len("positive") == 8
    assert nonspace_len(" a b\tc\n") == 3
    assert nonspace_len("") == 0
