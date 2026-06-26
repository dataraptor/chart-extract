"""Per-field-type normalizers + field-type inference (spec §9, versioned with the gold set).

**This module owns the comparison contract.** Whether a predicted value "matches" the gold label
is decided here, one function per field type — defined, not hand-wavy:

- **string**: ``casefold().strip()`` + collapse internal whitespace.
- **numeric**: parse a number and **convert to the field's canonical unit** (``tumor_size_cm`` is
  centimetres, so ``"14 mm" == "1.4 cm" == 1.4``); compare exactly after conversion, with a
  documented relative-tolerance knob (:data:`NUMERIC_REL_TOL`, default ``0.0`` — exact).
- **enum** (``Literal``): map known synonyms to the canonical member (``"ER+" -> "positive"``).
- **list** (``ListField``): set-match items after normalizing each → per-item TP / FP / FN.

The empty-matching rules (the point of the gold set) live in :mod:`eval.run`'s scorer, not here:
a ``not_assessed`` gold matches a ``not_assessed`` prediction and is **never** a hallucination; a
``not_found`` gold matches a null prediction. This module only normalizes *present* values.

``NORMALIZE_VERSION`` is bumped whenever a rule changes — the gold set is frozen against it, so a
normalizer change is a versioned event, not a silent tweak.
"""

from __future__ import annotations

import re
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from chartextract import ListField

#: Bumped when any normalization rule changes (the gold set is frozen against this).
NORMALIZE_VERSION = "v1"

FieldType = Literal["string", "numeric", "enum", "list"]

#: Relative tolerance for numeric comparison (a documented knob, §17). Default ``0.0`` means
#: **exact after unit conversion** — "14 mm" must equal "1.4 cm" to the float, no fuzz. Raise it
#: (e.g. ``0.02``) to accept rounding differences; the gold set is scored at the default.
NUMERIC_REL_TOL = 0.0
#: A tiny absolute floor so exact-equal floats compare equal despite IEEE representation.
_NUMERIC_ABS_TOL = 1e-9

#: Fields whose numeric value carries a unit; everything else (counts) is unit-less.
CANONICAL_UNIT: dict[str, str] = {"tumor_size_cm": "cm"}

#: Centimetre conversion factors for the units that appear in clinical measurements.
_TO_CM: dict[str, float] = {"mm": 0.1, "cm": 1.0, "m": 100.0}

#: Known enum synonyms → canonical member (case-folded keys). Generic across the two schemas; an
#: unmapped token falls through to itself, so an exact canonical member always matches.
ENUM_SYNONYMS: dict[str, str] = {
    "er+": "positive",
    "pr+": "positive",
    "her2+": "positive",
    "er-": "negative",
    "pr-": "negative",
    "her2-": "negative",
    "+": "positive",
    "-": "negative",
    "pos": "positive",
    "neg": "negative",
    "positive": "positive",
    "negative": "negative",
    "unknown": "unknown",
    "equivocal": "unknown",
    "m": "male",
    "male": "male",
    "f": "female",
    "female": "female",
    "other": "other",
}

_NUMBER_UNIT = re.compile(r"([-+]?\d*\.?\d+)\s*(mm|cm|m)?", re.IGNORECASE)
_WS = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Field-type inference — derive each field's type from the schema, never hand-maintained.
# ---------------------------------------------------------------------------


def infer_field_type(schema_model: type[BaseModel], name: str) -> FieldType:
    """Return the normalizer type for ``schema_model``'s field ``name``.

    Introspects the Pydantic annotation: a :class:`~chartextract.ListField` attribute → ``list``;
    otherwise the inner ``value: T | None`` of ``Field[T]`` decides — ``Literal[...]`` → ``enum``,
    ``int``/``float`` → ``numeric``, everything else → ``string``. Deriving (not hardcoding) keeps
    the normalizers in lock-step with the contract in ``schemas.py``.
    """
    ann = schema_model.model_fields[name].annotation
    if isinstance(ann, type) and issubclass(ann, ListField):
        return "list"
    inner = ann.model_fields["value"].annotation  # T | None
    member = next((a for a in get_args(inner) if a is not type(None)), inner)
    if get_origin(member) is Literal:
        return "enum"
    if member in (int, float):
        return "numeric"
    return "string"


def numeric_is_integer(schema_model: type[BaseModel], name: str) -> bool:
    """True iff a ``numeric`` field's value type is ``int`` (a count) rather than ``float``."""
    inner = schema_model.model_fields[name].annotation.model_fields["value"].annotation
    member = next((a for a in get_args(inner) if a is not type(None)), inner)
    return member is int


def enum_members(schema_model: type[BaseModel], name: str) -> tuple[str, ...]:
    """The canonical ``Literal`` members of an enum field (lower-cased, for synonym mapping)."""
    inner = schema_model.model_fields[name].annotation.model_fields["value"].annotation
    member = next((a for a in get_args(inner) if a is not type(None)), inner)
    return tuple(str(m).casefold() for m in get_args(member))


# ---------------------------------------------------------------------------
# Per-type normalizers
# ---------------------------------------------------------------------------


def normalize_string(value: Any) -> str:
    """``casefold().strip()`` with internal whitespace collapsed to single spaces."""
    return _WS.sub(" ", str(value)).strip().casefold()


def parse_measure(value: Any, field_name: str) -> float:
    """Parse ``value`` to a number in the field's canonical unit.

    A bare number is taken to already be in canonical units. A string like ``"14 mm"`` is parsed to
    its number + unit and converted (``-> 1.4`` for a centimetre field). Unit-less fields (counts)
    just yield the number. Raises ``ValueError`` if no number can be parsed (an authoring error).
    """
    if isinstance(value, bool):  # guard: bool is an int subclass, never a measurement
        raise ValueError(f"{field_name}: boolean is not a numeric value")
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUMBER_UNIT.search(str(value))
    if m is None:
        raise ValueError(f"{field_name}: no number found in {value!r}")
    number = float(m.group(1))
    canonical = CANONICAL_UNIT.get(field_name)
    found_unit = (m.group(2) or "").casefold()
    if canonical == "cm" and found_unit in _TO_CM:
        number *= _TO_CM[found_unit]
    return number


def normalize_enum(value: Any, members: tuple[str, ...]) -> str:
    """Map ``value`` to a canonical enum member via :data:`ENUM_SYNONYMS`.

    Strips trailing parenthetical detail (``"positive (90%)"`` → ``"positive"``) and a leading
    field tag (``"ER+"``/``"ER positive"`` → ``"positive"``) before the synonym lookup. If the
    result is not a known member it is returned as-is (so a genuine mismatch stays a mismatch).
    """
    raw = str(value).casefold().strip()
    raw = re.sub(r"\s*\(.*?\)\s*$", "", raw)  # drop "(90%)" style trailing detail
    if raw in ENUM_SYNONYMS:
        return ENUM_SYNONYMS[raw]
    if raw in members:
        return raw
    # "er positive" / "her2 negative" — drop a leading non-canonical tag word, retry.
    parts = raw.split()
    if len(parts) > 1:
        tail = parts[-1]
        if tail in ENUM_SYNONYMS:
            return ENUM_SYNONYMS[tail]
        if tail in members:
            return tail
    return raw


def normalize_list(values: Any) -> set[str]:
    """Normalize each item of an iterable to a string → the set used for set-matching."""
    if values is None:
        return set()
    return {normalize_string(v) for v in values}


# ---------------------------------------------------------------------------
# Match predicates — one boolean per field type (used by the scorer)
# ---------------------------------------------------------------------------


def numeric_match(gold: Any, pred: Any, field_name: str) -> bool:
    """True iff ``gold`` and ``pred`` are equal once parsed into the field's canonical unit."""
    try:
        g, p = parse_measure(gold, field_name), parse_measure(pred, field_name)
    except ValueError:
        return False
    tol = max(_NUMERIC_ABS_TOL, NUMERIC_REL_TOL * abs(g))
    return abs(g - p) <= tol


def scalar_match(
    field_type: FieldType,
    gold: Any,
    pred: Any,
    *,
    field_name: str,
    members: tuple[str, ...] = (),
) -> bool:
    """Match one *present* scalar value under the field-type normalizer."""
    if field_type == "numeric":
        return numeric_match(gold, pred, field_name)
    if field_type == "enum":
        return normalize_enum(gold, members) == normalize_enum(pred, members)
    return normalize_string(gold) == normalize_string(pred)


def list_item_counts(gold_items: Any, pred_items: Any) -> tuple[int, int, int]:
    """Per-item ``(tp, fp, fn)`` from set-matching two normalized item collections."""
    gset, pset = normalize_list(gold_items), normalize_list(pred_items)
    return len(gset & pset), len(pset - gset), len(gset - pset)
