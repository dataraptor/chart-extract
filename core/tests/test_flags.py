"""§8 flag-decision tests — the null-discipline suite (spec §11).

Exercises :func:`assign_flag` directly with hand-built :class:`SpanMatch`-equivalents so each
branch of the decision procedure is pinned, including the load-bearing distinctions
``not_found`` vs ``not_assessed`` and the JS flag ORDER (``ambiguous_span`` before
``needs_review``).
"""

from __future__ import annotations

from chartextract import assign_flag, structural_confidence


def _flag(value, span, quality, n_matches, model_conf):
    """Helper: ground-truthless flag assignment from raw inputs (mirrors a per-field call)."""
    sconf = structural_confidence(model_conf, quality)
    return assign_flag(
        value=value,
        source_span=span,
        match_quality=quality,
        n_matches=n_matches,
        structural_conf=sconf,
    )


def test_not_grounded_nulls_a_fabricated_value():
    # Model proposed a value but its span isn't in the document → value forced to None.
    flag, value = _flag("2", "2 of 3 axillary nodes positive", "none", 0, 0.71)
    assert flag == "not_grounded"
    assert value is None


def test_not_found_on_empty_span():
    flag, value = _flag(None, "", "none", 0, 0.0)
    assert flag == "not_found"
    assert value is None


def test_not_assessed_on_locatable_absence_span():
    # value=None but a real "...not assessed..." span was located → cited absence, NOT silent.
    flag, value = _flag(None, "Margins not assessed on this specimen", "exact", 1, 0.0)
    assert flag == "not_assessed"
    assert value is None


def test_uncitable_not_assessed_degrades_to_not_found():
    # The load-bearing last branch: value=None with a NON-empty span that cannot be located
    # degrades to not_found (an uncitable "not assessed" is indistinguishable from fabricated).
    flag, value = _flag(None, "some claim that is not in the document", "none", 0, 0.0)
    assert flag == "not_found"
    assert value is None


def test_ambiguous_span_keeps_value():
    # Short span (< 12 non-space) matching > 1 place, with a non-null value → ambiguous, value kept.
    flag, value = _flag("positive", "positive", "exact", 2, 0.9)
    assert flag == "ambiguous_span"
    assert value == "positive"


def test_ambiguous_beats_needs_review_order_lock():
    # The one input where the two orderings diverge: a short span matching > 1 place whose
    # collapsed confidence is BELOW τ. The JS order checks ambiguity FIRST → ambiguous_span,
    # not needs_review. This is the parity-critical assertion.
    flag, value = _flag("positive", "positive", "exact", 2, 0.4)  # mc 0.4 < τ
    assert structural_confidence(0.4, "exact") < 0.6
    assert flag == "ambiguous_span"
    assert value == "positive"


def test_needs_review_on_low_confidence():
    flag, value = _flag("Persistent cough", "Persistent cough, 3 weeks", "exact", 1, 0.55)
    assert flag == "needs_review"
    assert value == "Persistent cough"


def test_needs_review_on_prefix_even_with_high_conf():
    flag, value = _flag("X", "X", "prefix", 1, 0.99)
    assert flag == "needs_review"
    assert value == "X"


def test_accepted_on_exact_high_conf():
    flag, value = _flag("Left breast core biopsy", "Left breast core biopsy", "exact", 1, 0.96)
    assert flag is None
    assert value == "Left breast core biopsy"


def test_long_ambiguous_span_is_not_ambiguous():
    # A span matching > 1 place but ≥ 12 non-space chars is NOT ambiguous (cutoff guard).
    flag, value = _flag("positive result", "positive result", "exact", 2, 0.9)
    assert flag is None  # accepted — long enough to be unambiguous despite the duplicate
    assert value == "positive result"
