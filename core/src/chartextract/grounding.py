"""Span grounding — locate a model-proposed ``source_span`` in the canonical text.

**This module owns the offset contract:** every ``char_start``/``char_end`` it returns indexes the
*unmodified* canonical text, so ``text[char_start:char_end]`` is always a real substring. It is a
byte-for-byte port of ``ground()`` in the UI mockup (``app/ChartExtract.dc.html``), tried in a
fixed order — ``exact → whitespace-tolerant → prefix → none`` — so the live engine highlights the
exact characters the offline reference does.

:func:`ground_fields` glues this to the §8 flag procedure (:mod:`chartextract.confidence`) to turn
a parsed, schema-shaped model output into the flattened ``list[GroundedField]`` the UI renders and
the eval scores. No LLM and no network — it runs on a recorded ``(value, source_span, confidence)``
tuple, fully deterministic.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from .confidence import assign_flag, structural_confidence
from .load import LoadedDoc
from .schemas import Field, GroundedField, ListField, MatchQuality

#: Guard against catastrophic regex builds on the whitespace branch: a span with more tokens than
#: this (or whose escaped pattern is longer than :data:`_WS_MAX_PATTERN_LEN`) skips the regex and
#: falls through to the prefix match. Spans this large never come from real field values.
_WS_MAX_TOKENS = 200
_WS_MAX_PATTERN_LEN = 4000

#: Prefix length for the last-resort match (JS ``span.replace(/\\s+/g,' ').slice(0,40)``).
_PREFIX_LEN = 40

#: Token-escaping for the whitespace regex (JS ``/[.*+?^${}()|[\\]\\\\]/g``). ``re.escape`` is a
#: superset (it also escapes ``-``/``#`` etc.) and is safe here — we only need the metachars
#: neutralized; the join with ``\s+`` is what makes the match whitespace-tolerant.
_WS_SPLIT = re.compile(r"\s+")


class SpanMatch(BaseModel):
    """Where (and how well) a ``source_span`` was located in the canonical text.

    ``n_matches`` is the count of places the span occurs and is only ever ``> 1`` on the **exact**
    branch (ambiguity is detected there alone); the whitespace and prefix branches hardcode
    ``n_matches = 1`` to stay byte-identical with the JS reference.
    """

    model_config = ConfigDict(extra="forbid")

    match_quality: MatchQuality
    char_start: int | None
    char_end: int | None
    n_matches: int


def ground(source_span: str, canonical_text: str) -> SpanMatch:
    """Locate ``source_span`` in ``canonical_text`` — ``exact → whitespace → prefix → none``.

    Mirrors ``ground()`` in ``app/ChartExtract.dc.html``:

    1. Empty/whitespace-only span → ``none`` (offsets ``None``, ``n_matches=0``).
    2. **Exact** (``text.find(span)``): ``n_matches`` = non-overlapping occurrences of the span.
    3. **Whitespace-tolerant**: escape each whitespace-split token, join with ``\\s+``, search the
       *original* text and return *original* offsets — tolerates newline/space drift. Always
       ``n_matches=1`` (the JS hardcodes ``count:1`` here; counting more would flip
       ``ambiguous_span``↔``needs_review`` versus the UI).
    4. **Prefix**: collapse internal whitespace to single spaces, take the first ~40 chars,
       ``text.find(prefix)``. Always ``n_matches=1``.
    5. Else → ``none``.

    Offsets always index the unmodified ``canonical_text``, so ``text[start:end]`` is a real
    substring. (Deviation from JS, documented: the JS guards only empty spans with ``!span``; we
    also treat a whitespace-only span as ``none`` — the JS empty-regex edge case would otherwise
    match at index 0. No reference input is whitespace-only, so this never diverges on the gate.)
    """
    if not source_span or not source_span.strip():
        return SpanMatch(match_quality="none", char_start=None, char_end=None, n_matches=0)

    # 2. Exact.
    i = canonical_text.find(source_span)
    if i != -1:
        n_matches = canonical_text.count(source_span)
        return SpanMatch(
            match_quality="exact",
            char_start=i,
            char_end=i + len(source_span),
            n_matches=n_matches,
        )

    # 3. Whitespace-tolerant — build a `\s+`-joined regex over the escaped tokens.
    tokens = _WS_SPLIT.split(source_span.strip())
    if 0 < len(tokens) <= _WS_MAX_TOKENS:
        pattern = r"\s+".join(re.escape(tok) for tok in tokens)
        if len(pattern) <= _WS_MAX_PATTERN_LEN:
            try:
                m = re.search(pattern, canonical_text)
            except re.error:
                m = None
            if m is not None:
                return SpanMatch(
                    match_quality="whitespace",
                    char_start=m.start(),
                    char_end=m.end(),
                    n_matches=1,
                )

    # 4. Prefix — first ~40 chars with internal whitespace collapsed.
    prefix = _WS_SPLIT.sub(" ", source_span)[:_PREFIX_LEN]
    j = canonical_text.find(prefix)
    if j != -1:
        return SpanMatch(
            match_quality="prefix",
            char_start=j,
            char_end=j + len(prefix),
            n_matches=1,
        )

    # 5. Not found.
    return SpanMatch(match_quality="none", char_start=None, char_end=None, n_matches=0)


def _ground_one(name: str, field: Field, text: str) -> GroundedField:
    """Ground a single scalar :class:`Field` into a :class:`GroundedField` (§7 + §8)."""
    span = field.source_span or ""
    match = ground(span, text)
    sconf = structural_confidence(field.confidence, match.match_quality)
    flag, value = assign_flag(
        value=field.value,
        source_span=span,
        match_quality=match.match_quality,
        n_matches=match.n_matches,
        structural_conf=sconf,
    )
    # `model_value` carries the rejected proposal so the UI's "what the model said" disclosure
    # works in live mode; populated only when code nulled the value (§ carry-forward / UIUX §5.3).
    model_value = field.value if flag == "not_grounded" else None
    # Confidence is 0 for every null-value branch (JS leaves `conf` at its 0 init there).
    confidence = sconf if field.value is not None else 0.0
    # Offsets follow the *match*, not the value: a ``not_assessed`` field is null yet its cited
    # absence span ("Margins not assessed …") DID ground, so it keeps its offsets — that drives the
    # cyan cited-absence wash in the UI money demo (Beat 3) and restores parity with the JS
    # `grounded()`, which keeps ``s``/``e`` for not_assessed. ``match.char_start`` is already
    # ``None`` whenever the span didn't ground (``not_found``, ``not_grounded``), so those null
    # branches stay offset-less with no special case.
    return GroundedField(
        name=name,
        value=value,
        source_span=span,
        char_start=match.char_start,
        char_end=match.char_end,
        match_quality=match.match_quality,
        confidence=confidence,
        flag=flag,
        model_value=model_value,
    )


def ground_fields(parsed: BaseModel, doc: LoadedDoc) -> list[GroundedField]:
    """Ground every field of a parsed schema instance into a flattened ``list[GroundedField]``.

    Iterates the schema's fields in **declaration order** (``field_names()`` from Split 01).
    Scalar (:class:`Field`) attributes yield one row named ``field``; :class:`ListField`
    attributes yield one row per item named ``field[0]``, ``field[1]``, … — each grounded
    **independently**, so an ungroundable item is flagged while the rest survive (the §16
    "k of n grounded" guarantee). Each row carries its offsets, structural confidence and §8 flag.
    """
    text = doc.text
    rows: list[GroundedField] = []
    for name in parsed.__class__.model_fields:
        attr = getattr(parsed, name)
        if isinstance(attr, ListField):
            for idx, item in enumerate(attr.items):
                rows.append(_ground_one(f"{name}[{idx}]", item, text))
        elif isinstance(attr, Field):
            rows.append(_ground_one(name, attr, text))
        # Any non-Field/ListField attribute is not part of the model contract; skip it.
    return rows
