"""Request/response contracts for the ChartExtract HTTP API (Split 06).

**One serialization, not two.** The success body of ``/api/extract`` is the engine's
:class:`chartextract.ExtractionResult` serialized *as-is* (``model_dump()``) — this module does
**not** redeclare it, so the HTTP shape can never drift from the engine's. The models here are only
the small request bodies and the meta/eval/error envelopes the UI binds to.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: The doc-type schema override the dropdown sends (null ⇒ route via the classifier).
SchemaName = Literal["pathology", "intake"]


class ExtractRequest(BaseModel):
    """Body of ``POST /api/extract`` (JSON form). Exactly one of ``sample_id`` / ``text`` must be
    set (the multipart form adds a third option, an uploaded ``file``). ``schema`` is the dropdown
    override; ``provider`` overrides the server default (``stub`` offline, ``openai`` live)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    sample_id: str | None = None
    text: str | None = None
    #: JSON key is ``schema``; aliased to avoid shadowing pydantic's ``BaseModel.schema``.
    schema_override: SchemaName | None = Field(default=None, alias="schema")
    provider: str | None = None


# ---------------------------------------------------------------------------
# Meta / health
# ---------------------------------------------------------------------------


class SampleItem(BaseModel):
    """One bundled example the UI can pick. ``text`` is the **canonical** ``load()`` output — the
    single offset source — so the document pane renders exactly the string offsets index into."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    doc_type_hint: str
    text: str


class HealthResponse(BaseModel):
    """``GET /health`` — names the *active* provider so the UI footer can say, honestly, whether
    the demo is canned (stub) or billed (live)."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    provider: str
    model: str


# ---------------------------------------------------------------------------
# Eval leaderboard (UIUX §5.5 shape)
# ---------------------------------------------------------------------------


class EvalRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    p: float
    r: float
    f1: float
    note: str = ""


class EvalCostRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    f1: float
    usd_per_doc: float
    delta: float | None = None


class EvalSummary(BaseModel):
    """The leaderboard the Eval view renders (mirrors UIUX §5.5). Built from the frozen artifact
    Split 05 emits, or — if absent — a synchronous stub run. Deterministic on the stub."""

    model_config = ConfigDict(extra="forbid")

    gold_count: int
    n_runs: int
    macro_f1: float
    hallucination_rate: float
    routing_accuracy: float
    rows: list[EvalRow] = []
    cost: list[EvalCostRow] = []
    caption: str


# ---------------------------------------------------------------------------
# Error envelope (§15 / UIUX §9) — a single structured shape; never a 500 stack trace.
# ---------------------------------------------------------------------------


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    message: str
    hint: str | None = None


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody
