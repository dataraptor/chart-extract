"""Canonical data contracts for ChartExtract (spec §6 + UI/UX §0).

**This module owns the cross-stack data contract.** The model-facing extraction schemas
(`PathologySchema`, `IntakeSchema`), the field primitives (`Field[T]`, `ListField`), and the
assembled result types (`GroundedField`, `ExtractionResult`) are imported by every later split
— grounding (02), the pipeline (03), the provider (04), the eval harness (05), the API (06), and
consumed by name in the UI (`app/ChartExtract.dc.html`). Field names and enum members are a
contract: renaming anything here cascades into every downstream layer, so change only with the
spec.

This split (01) defines the *types* only. The grounded values — `char_start`/`char_end`,
structural `confidence`, and `flag` — are **computed in code** in Split 02; here they are just
declared so all splits import one definition.
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

#: Bump only when an extraction schema changes shape. Recorded on every result.
SCHEMA_VERSION = "v2"

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Field primitives — exactly what the MODEL returns (spec §4/§6).
# The model returns {value, source_span, confidence}; it never returns offsets.
# ---------------------------------------------------------------------------


class Field(BaseModel, Generic[T]):
    """One scalar field the model returns.

    ``source_span`` is the verbatim text the model claims supports ``value`` (``""`` when the
    value is null). ``confidence`` is the model's *self-reported* 0..1 score — it is an input to
    the structural confidence computed in Split 02, never trusted alone.
    """

    model_config = ConfigDict(extra="forbid")

    value: T | None
    source_span: str = ""
    confidence: float


class ListField(BaseModel):
    """A multi-value field (medications, allergies, problems).

    Each item is its own :class:`Field`, so each carries its **own** span and confidence and is
    grounded independently. Flattened at grounding time into ``name[i]`` rows (Split 02).
    """

    model_config = ConfigDict(extra="forbid")

    items: list[Field] = []


# ---------------------------------------------------------------------------
# Extraction schemas (spec §6) — the structured-output targets sent to the model.
# ---------------------------------------------------------------------------


class PathologySchema(BaseModel):
    """Headline schema — the §5 worked example (surgical pathology report).

    ``pr_status`` is **added** per the UI/UX reconciliation of the §5↔§6 conflict (the worked
    example reports PR alongside ER). ``margin_status`` is a 2-way enum: an *absent* margin
    assessment is null + a flag downstream, never a value.
    """

    model_config = ConfigDict(extra="forbid")

    specimen: Field[str]
    diagnosis: Field[str]
    grade: Field[str]
    tumor_size_cm: Field[float]
    er_status: Field[Literal["positive", "negative", "unknown"]]
    pr_status: Field[Literal["positive", "negative", "unknown"]]
    her2_status: Field[Literal["positive", "negative", "unknown"]]
    margin_status: Field[Literal["negative", "positive"]]
    lymph_nodes_positive: Field[int]


class IntakeSchema(BaseModel):
    """Intake schema — exercises the multi-value (`ListField`) path.

    ``pcp`` is frequently absent, which proves the ``not_found`` case on a list-schema document.
    """

    model_config = ConfigDict(extra="forbid")

    patient_name: Field[str]
    dob: Field[str]
    sex: Field[Literal["male", "female", "other", "unknown"]]
    chief_complaint: Field[str]
    medications: ListField
    allergies: ListField
    pcp: Field[str]


#: The doc-type → schema registry. `router.py` (Split 03) uses this for routing.
#: TODO discharge: a DischargeSchema is on the roadmap (routing-only in v1); add here when built.
SCHEMAS: dict[str, type[BaseModel]] = {
    "pathology": PathologySchema,
    "intake": IntakeSchema,
}


# ---------------------------------------------------------------------------
# Assembled result contract — produced in code (Split 02/03), the types live here.
# ---------------------------------------------------------------------------

#: The one flag taxonomy (spec §8), used everywhere. ``None`` == accepted.
GroundFlag = Literal[
    None,
    "not_found",
    "not_assessed",
    "not_grounded",
    "needs_review",
    "ambiguous_span",
]

#: How the source span matched the canonical text (spec §7).
MatchQuality = Literal["exact", "whitespace", "prefix", "none"]


class GroundedField(BaseModel):
    """One field after grounding — what the UI renders and the eval scores.

    Scalar fields appear under their bare ``name``; flattened ``ListField`` items appear as
    ``name[i]``. ``char_start``/``char_end`` and the structural ``confidence`` are computed in
    code (Split 02) against the canonical loaded text; both offsets are ``None`` when ``value`` is
    null.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    value: object | None
    source_span: str = ""
    char_start: int | None = None
    char_end: int | None = None
    match_quality: MatchQuality = "none"
    confidence: float = 0.0
    flag: GroundFlag = None
    model_value: object | None = None
    """The value the model PROPOSED, retained when code nulls it (``flag == "not_grounded"``).

    Lets the UI's "what the model said" disclosure (UIUX §5.3 / shot 03) work in *live* mode, not
    only on canned data. ``None`` for every other flag. Mirrors the JS mockup's ``proposed`` field
    in ``pathDefs()``. Populated in Split 02; surfaced in Splits 06/07/09.
    """


class ExtractionResult(BaseModel):
    """The top-level result of an extraction run (assembled in Split 03).

    The ``n_*`` counts are derived from ``fields`` and drive the UI footer; ``cost_usd`` /
    ``latency_s`` / ``model`` are populated by the live pipeline.
    """

    model_config = ConfigDict(extra="forbid")

    doc_type: str
    fields: list[GroundedField]
    n_fields: int
    n_grounded: int
    n_null: int
    n_needs_review: int
    prompt_version: str
    schema_version: str
    model: str
    cost_usd: float = 0.0
    latency_s: float = 0.0
    highlight_available: bool = True
    """Whether character offsets are usable for highlighting.

    ``False`` when the source document had no text layer (a scanned PDF): the engine still returns
    fields, but every ``char_start``/``char_end`` is ``None`` and the UI shows a "highlight
    unavailable" banner (Split 09) instead of faking offsets. Mirrors ``LoadedDoc.has_text_layer``.
    """


def field_names(schema: type[BaseModel]) -> list[str]:
    """Return the stable, flattened field-name order for a schema.

    Scalar (`Field`) attributes yield their bare name; `ListField` attributes yield the bare name
    too (individual items are numbered as ``name[i]`` only at grounding time, since the item count
    isn't known until the model responds). The order is the declaration order of the model fields
    — later splits and the UI's "ghost rows / contract before values" rely on it being stable.
    """
    return list(schema.model_fields.keys())
