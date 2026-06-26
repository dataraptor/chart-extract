"""Structural confidence + the §8 flag-decision procedure — *code disposes*.

**This module owns the null-discipline contract:** no field survives without a real source. The
model proposes ``(value, source_span, confidence)``; here we (a) collapse the model's *self-
reported* confidence with the structural quality of the match (a prefix match **caps** confidence
no matter what number the model claimed) and (b) assign the one §8 flag by a deterministic
procedure that nulls any value whose span could not be located.

The procedure is a byte-for-byte port of ``grounded()`` in the UI mockup
(``app/ChartExtract.dc.html``). **Where the JS and the spec §8 prose disagree on flag ORDER the JS
wins** — it tests ``ambiguous_span`` *before* ``needs_review`` (see :func:`assign_flag`). That
divergence only changes the *label* of a value that is simultaneously ambiguous and low-confidence;
both labels count as "review", so counts and the eval are identical either way. We keep the JS
order so the engine stays byte-identical with the shipped offline reference.

Pure functions, no LLM, no network, no hidden state.
"""

from __future__ import annotations

from .schemas import GroundFlag, MatchQuality

#: Review threshold on the **structural** confidence (spec §8). Below this → ``needs_review``.
TAU = 0.6

#: Per-match-quality confidence weight (spec §8 / JS ``{exact:1, whitespace:0.92, prefix:0.5}``).
#: ``structural_confidence`` is ``min(model_conf, weight)`` — a weak match caps the score.
MATCH_WEIGHT: dict[MatchQuality, float] = {
    "exact": 1.0,
    "whitespace": 0.92,
    "prefix": 0.5,
    "none": 0.0,
}

#: "Short span" cutoff (non-space chars) for ambiguity (spec §7 / JS ``< 12``). A span shorter
#: than this that matches more than once is ``ambiguous_span`` rather than silently accepted.
AMBIG_MAX_NONSPACE = 12


def nonspace_len(s: str) -> int:
    """Length of ``s`` with all whitespace removed (JS ``span.replace(/\\s/g,'').length``)."""
    return sum(1 for ch in s if not ch.isspace())


def structural_confidence(model_conf: float, match_quality: MatchQuality) -> float:
    """Collapse the model's self-reported confidence with the structural match quality.

    Returns ``min(model_conf, weight(match_quality))`` — so a ``prefix`` match caps confidence at
    0.5 and a ``none`` match at 0.0 *regardless* of the number the model reported (spec §8: the
    model's confidence is an input, never trusted alone). Mirrors the JS ``Math.min(f.mc, w)``.
    """
    return min(model_conf, MATCH_WEIGHT[match_quality])


def assign_flag(
    *,
    value: object | None,
    source_span: str,
    match_quality: MatchQuality,
    n_matches: int,
    structural_conf: float,
) -> tuple[GroundFlag, object | None]:
    """The §8 decision procedure, verbatim — returns the (possibly nulled) value AND its flag.

    Mirrors ``grounded()`` in ``app/ChartExtract.dc.html`` exactly, **including the JS flag order**
    (``ambiguous_span`` is checked *before* ``needs_review``)::

        value present:
          match == none                  -> not_grounded   (value nulled; model invented it)
          n_matches > 1 and short span   -> ambiguous_span (kept; first match marked)   [1st]
          conf < TAU or match == prefix  -> needs_review   (kept; structurally uncertain) [2nd]
          else                           -> None           (accepted)
        value absent (None):
          empty span                     -> not_found      (model said: silent)
          span locatable (match != none) -> not_assessed   (doc states a non-value, cited)
          non-empty span NOT locatable   -> not_found      (uncitable "not assessed" degrades)

    The last branch is load-bearing (§8): a ``value=None`` with a non-empty span that cannot be
    located is **not** awarded ``not_assessed`` (indistinguishable from a fabricated citation) — it
    degrades to ``not_found``.
    """
    if value is not None:
        if match_quality == "none":
            # Model proposed a value but its span isn't in the document → caught hallucination.
            return "not_grounded", None
        if n_matches > 1 and nonspace_len(source_span) < AMBIG_MAX_NONSPACE:
            # Short span matching several places — kept, but the first match is only a guess.
            return "ambiguous_span", value
        if structural_conf < TAU or match_quality == "prefix":
            # Structurally uncertain (low collapsed confidence, or only a prefix matched).
            return "needs_review", value
        return None, value

    # value is None — distinguish a silent document from a cited non-value.
    if source_span == "":
        return "not_found", None
    if match_quality != "none":
        return "not_assessed", None
    # Non-empty span that can't be located: an uncitable "not assessed" is treated as silent.
    return "not_found", None
