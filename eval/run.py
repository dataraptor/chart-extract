"""The eval harness + leaderboard printer (spec §9 / §11, UIUX §5.5).

``python -m eval.run`` drives ``chartextract.extract`` over the **frozen gold set** and scores the
result **per field**, producing the headline artifact: per-field precision / recall / F1, macro-F1,
**hallucination-rate** (the number to drive to zero), and routing accuracy — reported
**distributionally** (mean +/- spread over ``--repeats N``).

Two registers:

- **stub (default, no key, deterministic):** each gold doc is replayed through a per-doc *oracle*
  :class:`~chartextract.StubProvider` built from its labels, so the real ``load -> route -> ground
  -> assemble`` pipeline runs and the leaderboard is byte-reproducible. This is the screenshot.
- **live (``--provider openai``/``anthropic``, opt-in):** the same gold docs run against the live
  provider for the real quality numbers; auto-skips with no key.

The harness **imports** the engine — it never re-implements grounding, routing, or pricing. The
scorer (:func:`score_fields`) is a pure function over ``(GoldRecord, ExtractionResult)``, so the
metric maths is unit-tested against hand-computed confusion matrices without any provider.

Usage::

    python -m eval.run                         # stub, deterministic, no key, full leaderboard
    python -m eval.run --repeats 3             # distributional (spread ~0 on the stub)
    python -m eval.run --provider openai        # live GPT-5.5 sweep (needs a key)
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from chartextract import (
    BATCH_DISCOUNT,
    PRICING,
    PROMPT_VERSION,
    SCHEMAS,
    BatchRequest,
    ExtractionResult,
    Field,
    ListField,
    ProviderError,
    StubProvider,
    Usage,
    collate_results,
    default_provider,
    extract,
    field_names,
    live_key_present,
    price,
    run_openai_batch,
)
from chartextract.prompts import EXTRACTION_SYSTEM, extraction_user_content
from chartextract.router import UnknownDocTypeError

from .dataset import GOLD_DIR, GoldRecord, load_doc_text, load_gold
from .normalize import (
    NORMALIZE_VERSION,
    enum_members,
    infer_field_type,
    list_item_counts,
    numeric_is_integer,
    parse_measure,
    scalar_match,
)

#: The reference token usage for the Opus-vs-Sonnet cost row (the stub's per-doc usage). Both
#: Anthropic rows are **computed-from-pricing estimates** (this realized build has no Anthropic key,
#: so they can't be measured) — priced from this same usage so the comparison is apples-to-apples.
#: A live sweep adds the one row that IS measured: the run's own model from its real usage
#: (Split 11, ``aggregate``).
REF_USAGE = Usage(input_tokens=1200, output_tokens=180)

#: The default artifact directory (mirrors the template-repo's ``docs/eval/``).
ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "docs" / "eval"


# ---------------------------------------------------------------------------
# Per-field score + per-(doc, repeat) record — the jsonl row and aggregation unit.
# ---------------------------------------------------------------------------


class FieldScore(BaseModel):
    """One field's contribution to the confusion matrix (the scorer's atom)."""

    model_config = ConfigDict(extra="forbid")

    field: str
    ftype: str
    correct: bool
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    #: Non-null prediction where gold is null — the hallucination count (per item for a list).
    hallucinated: int = 0
    #: The gold empty kind (``not_found``/``not_assessed``) when the field is null-gold, else None.
    gold_empty: str | None = None
    #: The predicted flag (so the leaderboard can show empty-kind agreement).
    pred_flag: str | None = None
    #: For a null-gold scalar correctly predicted null: did the empty *kind* match too?
    empty_kind_correct: bool | None = None


class DocRecord(BaseModel):
    """One ``(gold doc, repeat)`` result — the deterministic jsonl row and aggregation unit.

    Deliberately carries **no latency or timestamp** so two stub runs serialize byte-identically
    (the reproducibility gate). Latency is reported in the rendered leaderboard only, never scored.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    doc_type: str
    split: str
    provider: str
    model: str
    prompt_version: str
    normalize_version: str
    repeat: int
    routing_pred: str | None
    routing_correct: bool
    #: Whether the document was field-scored (False for discharge/error rows).
    scored: bool
    fields: list[FieldScore] = []
    cost_usd: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# Scoring — pure functions over (GoldRecord, ExtractionResult). No provider here.
# ---------------------------------------------------------------------------


def _score_scalar(record: GoldRecord, field: str, ftype: str, gf, schema_model) -> FieldScore:
    pred_val = gf.value if gf is not None else None
    pred_flag = gf.flag if gf is not None else None
    if record.is_empty(field):
        kind = record.empty_kind(field)
        if pred_val is None:  # correct empty — a true negative, NEVER a hallucination (§8)
            return FieldScore(
                field=field,
                ftype=ftype,
                correct=True,
                tn=1,
                gold_empty=kind,
                pred_flag=pred_flag,
                empty_kind_correct=(pred_flag == kind),
            )
        # predicted a value where gold is null → the hallucination we drive to zero, loudly.
        return FieldScore(
            field=field,
            ftype=ftype,
            correct=False,
            fp=1,
            hallucinated=1,
            gold_empty=kind,
            pred_flag=pred_flag,
        )
    gold = record.gold_value(field)
    if pred_val is None:  # missed a present value
        return FieldScore(field=field, ftype=ftype, correct=False, fn=1, pred_flag=pred_flag)
    members = enum_members(schema_model, field) if ftype == "enum" else ()
    if scalar_match(ftype, gold, pred_val, field_name=field, members=members):
        return FieldScore(field=field, ftype=ftype, correct=True, tp=1, pred_flag=pred_flag)
    return FieldScore(field=field, ftype=ftype, correct=False, fp=1, fn=1, pred_flag=pred_flag)


def _score_list(record: GoldRecord, field: str, result: ExtractionResult) -> FieldScore:
    pred_items = [f.value for f in result.fields if f.name.startswith(f"{field}[")]
    if record.is_empty(field):
        kind = record.empty_kind(field)
        if not pred_items:
            return FieldScore(field=field, ftype="list", correct=True, tn=1, gold_empty=kind)
        return FieldScore(
            field=field,
            ftype="list",
            correct=False,
            fp=len(pred_items),
            hallucinated=len(pred_items),
            gold_empty=kind,
        )
    gold_vals = [v for v, _ in record.list_items(field)]
    tp, fp, fn = list_item_counts(gold_vals, pred_items)
    return FieldScore(field=field, ftype="list", correct=(fp == 0 and fn == 0), tp=tp, fp=fp, fn=fn)


def score_fields(record: GoldRecord, result: ExtractionResult) -> list[FieldScore]:
    """Score every field of ``record`` against ``result`` → one :class:`FieldScore` per field.

    Pure and provider-agnostic: a present value matches under the per-type normalizer; a null gold
    matches a null prediction (and a ``not_assessed`` gold is rewarded, never punished); a non-null
    prediction against a null gold is a **hallucination**, counted separately.
    """
    schema_model = SCHEMAS[record.doc_type]
    by_name = {f.name: f for f in result.fields}
    scores: list[FieldScore] = []
    for name in field_names(schema_model):
        if name not in record.labels:  # only score fields this doc actually labels
            continue
        ftype = infer_field_type(schema_model, name)
        if ftype == "list":
            scores.append(_score_list(record, name, result))
        else:
            scores.append(_score_scalar(record, name, ftype, by_name.get(name), schema_model))
    return scores


# ---------------------------------------------------------------------------
# The deterministic oracle — replays a perfect extraction from the gold labels.
# ---------------------------------------------------------------------------


def _locate(text: str, hint: str) -> str:
    """Return the verbatim doc substring for ``hint`` (case-insensitive), else ``hint`` itself."""
    if not hint:
        return ""
    if hint in text:
        return hint
    i = text.lower().find(hint.lower())
    return text[i : i + len(hint)] if i != -1 else hint


def _typed_value(ftype: str, name: str, gold, schema_model):
    """Convert a gold label into the schema-typed value a perfect model would return."""
    from .normalize import normalize_enum  # local: keep the public import list tidy

    if ftype == "numeric":
        number = parse_measure(gold, name)
        return int(round(number)) if numeric_is_integer(schema_model, name) else number
    if ftype == "enum":
        return normalize_enum(gold, enum_members(schema_model, name))
    return str(gold)


def build_oracle_instance(record: GoldRecord, text: str) -> BaseModel:
    """Build the parsed schema instance a *perfect* model would return for ``record``.

    Present values become typed/enum-valid :class:`~chartextract.Field`\\s whose ``source_span`` is
    the verbatim doc text (so real grounding accepts them); ``not_found`` becomes an empty span;
    ``not_assessed`` becomes the cited statement (so grounding flags it ``not_assessed``).
    """
    schema_model = SCHEMAS[record.doc_type]
    data: dict[str, object] = {}
    for name in field_names(schema_model):
        ftype = infer_field_type(schema_model, name)
        if ftype == "list":
            items = [
                Field(value=str(val), source_span=_locate(text, span or str(val)), confidence=0.96)
                for val, span in record.list_items(name)
            ]
            data[name] = ListField(items=items)
        elif name not in record.labels or record.is_empty(name):
            # absent or explicitly-empty: null value, span only for a cited not_assessed.
            span = record.oracle_span(name) if record.empty_kind(name) == "not_assessed" else ""
            data[name] = Field(value=None, source_span=span, confidence=0.0)
        else:
            gold = record.gold_value(name)
            typed = _typed_value(ftype, name, gold, schema_model)
            span = _locate(text, record.oracle_span(name) or str(gold))
            data[name] = Field(value=typed, source_span=span, confidence=0.96)
    return schema_model(**data)


def build_oracle_provider(record: GoldRecord, text: str) -> StubProvider:
    """A per-doc :class:`StubProvider` that classifies to ``record.doc_type``, replaying the oracle.

    For a ``discharge`` record (no schema) it carries no extract result — the classifier returns
    ``discharge``, the router surfaces ``unknown``, and routing accuracy still scores correctly.
    """
    schema_model = SCHEMAS.get(record.doc_type)
    results = [build_oracle_instance(record, text)] if schema_model is not None else []
    return StubProvider(
        extract_results=results,
        classify_result=(record.doc_type, 0.99),
        usage=REF_USAGE,
        model="claude-opus-4-8",
    )


# ---------------------------------------------------------------------------
# Driving one (doc, repeat) through the real pipeline, then scoring it.
# ---------------------------------------------------------------------------


def run_doc(
    record: GoldRecord, text: str, *, provider, provider_name: str, repeat: int
) -> tuple[DocRecord, float]:
    """Run ``record`` through ``chartextract.extract`` and score it → ``(DocRecord, latency)``.

    Routing is **not** overridden (``schema=None``) so the classifier is exercised and routing
    accuracy is honest; an unresolved type (``unknown``/``discharge``) is caught and recorded, never
    crashed. A live provider error (missing key / refusal / truncation) is surfaced as a clean error
    row — the §15 "surface, never crash" rule — and that doc is reported as not-scored.
    """
    result: ExtractionResult | None = None
    routing_pred: str | None = None
    error: str | None = None
    latency = 0.0
    cost = 0.0
    try:
        result = extract(text, schema=None, provider=provider, source_name=record.id)
        routing_pred = result.doc_type
        cost = result.cost_usd
        latency = result.latency_s
    except UnknownDocTypeError as exc:
        routing_pred = exc.key or "unknown"  # router refused to guess — the correct discharge path
    except ProviderError as exc:  # missing key / refusal / truncation (live) — surfaced, not raised
        error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 — any other failure is reported honestly, not a crash
        error = f"{type(exc).__name__}: {exc}"

    routing_correct = routing_pred == record.doc_type
    scored = result is not None and record.doc_type in SCHEMAS and bool(record.labels)
    fields = score_fields(record, result) if scored else []
    model = result.model if result is not None else provider.model

    return (
        DocRecord(
            id=record.id,
            doc_type=record.doc_type,
            split=record.split,
            provider=provider_name,
            model=model,
            prompt_version=PROMPT_VERSION,
            normalize_version=NORMALIZE_VERSION,
            repeat=repeat,
            routing_pred=routing_pred,
            routing_correct=routing_correct,
            scored=scored,
            fields=fields,
            cost_usd=cost,
            error=error,
        ),
        latency,
    )


def run_suite(
    records: list[GoldRecord], *, provider_name: str, repeats: int, root: Path | str = GOLD_DIR
) -> tuple[list[DocRecord], list[float]]:
    """Run every gold doc ``repeats`` times. Returns ``(doc_records, latencies)``.

    ``provider_name == "stub"`` builds a fresh deterministic oracle per doc (no key, no network).
    Any other name uses the live provider once (it must be available; the caller checks first).
    Runs serially so the stub's record order — and therefore the jsonl artifact — is reproducible.
    """
    live = None if provider_name == "stub" else default_provider()
    out: list[DocRecord] = []
    latencies: list[float] = []
    for repeat in range(1, repeats + 1):
        for record in records:
            text = load_doc_text(record, root=root)
            provider = build_oracle_provider(record, text) if live is None else live
            rec, latency = run_doc(
                record, text, provider=provider, provider_name=provider_name, repeat=repeat
            )
            out.append(rec)
            if rec.error is None and rec.scored:
                latencies.append(latency)
    return out, latencies


#: The default batch backend: submit the live OpenAI Batch job (opt-in, needs a key).
def _live_batch_fn(requests: list[BatchRequest]) -> dict[str, tuple[BaseModel, Usage]]:
    return run_openai_batch(default_provider(), requests)


def run_suite_batch(
    records: list[GoldRecord],
    *,
    repeats: int,
    batch_fn=_live_batch_fn,
    model: str = "gpt-5.5",
    provider_name: str = "openai-batch",
    root: Path | str = GOLD_DIR,
) -> tuple[list[DocRecord], list[float]]:
    """Score the field-labeled docs through the **Batch API** (50% cheaper), not one call each.

    Every schema-bearing gold doc becomes a :class:`~chartextract.BatchRequest` keyed by its id;
    ``batch_fn`` submits them as one job and returns ``{custom_id: (parsed, usage)}`` **unordered**.
    :func:`~chartextract.collate_results` re-associates each result to its request (surfacing any
    missing id), then each parsed instance is replayed through the **same** ``load -> route ->
    ground -> assemble -> score`` path as the sync sweep (via a one-shot :class:`StubProvider`), so
    the field scores are identical — only the cost differs (priced at the
    :data:`~chartextract.BATCH_DISCOUNT`). ``batch_fn`` is injectable so the gate's "batch == sync"
    proof runs Tier-1 with a deterministic oracle and no network.

    Batching pins each request's ``response_format`` up front, so routing is by the gold doc_type
    (a batch request can't run the classifier inside itself); routing accuracy is the sync sweep's
    job. Routing-only discharge docs (no schema) are not batched.
    """
    schema_records = [r for r in records if r.doc_type in SCHEMAS and r.labels]
    out: list[DocRecord] = []
    latencies: list[float] = []
    for repeat in range(1, repeats + 1):
        texts = {r.id: load_doc_text(r, root=root) for r in schema_records}
        requests = [
            BatchRequest(
                custom_id=r.id,
                system=EXTRACTION_SYSTEM,
                document_text=extraction_user_content(texts[r.id]),
                schema_model=SCHEMAS[r.doc_type],
            )
            for r in schema_records
        ]
        results = batch_fn(requests)
        # collate_results surfaces any missing custom_id and re-orders to the request order.
        by_id = {req.custom_id: result for req, result in collate_results(requests, results)}
        for r in schema_records:
            parsed, usage = by_id[r.id]
            stub = StubProvider(
                extract_results=[parsed],
                classify_result=(r.doc_type, 0.99),
                usage=usage,
                model=model,
            )
            rec, latency = run_doc(
                r, texts[r.id], provider=stub, provider_name=provider_name, repeat=repeat
            )
            # The batch is ~50% cheaper than the sync call — reflect the real billed cost.
            rec = rec.model_copy(update={"cost_usd": rec.cost_usd * BATCH_DISCOUNT})
            out.append(rec)
            if rec.error is None and rec.scored:
                latencies.append(latency)
    return out, latencies


# ---------------------------------------------------------------------------
# Aggregation → Leaderboard.
# ---------------------------------------------------------------------------


class FieldMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    ftype: str
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int
    support: int  # tp + fn (gold-present instances)


class Stat(BaseModel):
    """A distributional metric: mean +/- spread over the per-repeat values (§9)."""

    model_config = ConfigDict(extra="forbid")

    mean: float
    spread: float
    n_repeats: int


class CostRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    cost_per_doc: float
    #: True only when the row priced a **real** sweep (this run's measured per-doc usage). The
    #: Anthropic comparison rows are computed-from-pricing **estimates** (no Anthropic key in this
    #: build), so they carry ``measured=False`` — never an estimate shown as measured (§9 honesty).
    measured: bool = False


class Leaderboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: str
    prompt_version: str
    normalize_version: str
    provider: str
    repeats: int
    n_docs: int  # field-labeled docs in the set
    n_scored: int  # field-labeled docs actually scored (repeat 1) — the "k of n" honesty
    n_routing_docs: int
    fields: list[FieldMetric] = []
    macro_f1: Stat
    hallucination_rate: Stat
    hallucination_count: int
    n_null_gold: int
    routing_accuracy: float
    empty_kind_accuracy: float | None = None
    measured_cost_per_doc: float
    cost_rows: list[CostRow] = []
    sonnet_cost_delta_pct: float | None = None


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


#: Canonical leaderboard field order — the headline pathology schema first, then intake (UIUX §5.5).
CANONICAL_FIELD_ORDER: list[str] = [
    name for schema in SCHEMAS.values() for name in field_names(schema)
]


def _field_metrics(records: list[DocRecord]) -> list[FieldMetric]:
    """Pooled per-field P/R/F1 over the scored records (all repeats), in canonical order."""
    agg: dict[str, dict[str, object]] = {}
    seen: list[str] = []
    for r in records:
        for fs in r.fields:
            if fs.field not in agg:
                agg[fs.field] = {"ftype": fs.ftype, "tp": 0, "fp": 0, "fn": 0}
                seen.append(fs.field)
            agg[fs.field]["tp"] += fs.tp
            agg[fs.field]["fp"] += fs.fp
            agg[fs.field]["fn"] += fs.fn
    order = [n for n in CANONICAL_FIELD_ORDER if n in agg] + [
        n for n in seen if n not in CANONICAL_FIELD_ORDER
    ]
    out: list[FieldMetric] = []
    for name in order:
        a = agg[name]
        p, rc, f1 = _prf(a["tp"], a["fp"], a["fn"])
        out.append(
            FieldMetric(
                field=name,
                ftype=a["ftype"],
                precision=p,
                recall=rc,
                f1=f1,
                tp=a["tp"],
                fp=a["fp"],
                fn=a["fn"],
                support=a["tp"] + a["fn"],
            )
        )
    return out


def _macro_f1(records: list[DocRecord]) -> float:
    """Mean F1 over fields that have at least one gold-present instance (support > 0)."""
    metrics = [m for m in _field_metrics(records) if m.support > 0]
    return statistics.mean(m.f1 for m in metrics) if metrics else 0.0


def _halluc(records: list[DocRecord]) -> tuple[int, int]:
    """``(hallucination_count, null_gold_count)`` over the scored records."""
    halluc = sum(fs.hallucinated for r in records for fs in r.fields)
    null_gold = sum(1 for r in records for fs in r.fields if fs.gold_empty is not None)
    return halluc, null_gold


def _stat_over_repeats(records: list[DocRecord], fn) -> Stat:
    """Apply ``fn`` per repeat group, then mean +/- population-stdev across repeats."""
    by_repeat: dict[int, list[DocRecord]] = defaultdict(list)
    for r in records:
        by_repeat[r.repeat].append(r)
    per = [fn(group) for group in by_repeat.values()]
    spread = statistics.pstdev(per) if len(per) > 1 else 0.0
    return Stat(mean=statistics.mean(per) if per else 0.0, spread=spread, n_repeats=len(per))


def aggregate(
    records: list[DocRecord], *, n_docs: int, generated_at: str, provider: str, repeats: int
) -> Leaderboard:
    """Fold the per-doc records into the leaderboard (§9 / UIUX §5.5)."""
    scored = [r for r in records if r.scored]
    halluc, null_gold = _halluc(scored)
    halluc_rate = _stat_over_repeats(
        scored,
        lambda g: (
            (sum(f.hallucinated for r in g for f in r.fields) / n)
            if (n := sum(1 for r in g for f in r.fields if f.gold_empty is not None))
            else 0.0
        ),
    )
    routing = [r for r in records]
    routing_acc = sum(1 for r in routing if r.routing_correct) / len(routing) if routing else 1.0
    # Empty-kind agreement over scalar empties that were correctly predicted null (secondary).
    kind_samples = [
        fs.empty_kind_correct
        for r in scored
        for fs in r.fields
        if fs.empty_kind_correct is not None
    ]
    empty_kind_acc = sum(1 for k in kind_samples if k) / len(kind_samples) if kind_samples else None

    measured = statistics.mean([r.cost_usd for r in scored]) if scored else 0.0
    # Anthropic comparison rows: priced from the same REF_USAGE under each model — ESTIMATES (no
    # Anthropic key in this realized build). The Opus-vs-Sonnet delta is the spec's cost-trade.
    cost_rows = [
        CostRow(model="claude-opus-4-8", cost_per_doc=price(REF_USAGE, "claude-opus-4-8")),
        CostRow(model="claude-sonnet-4-6", cost_per_doc=price(REF_USAGE, "claude-sonnet-4-6")),
    ]
    # A live sweep (not the deterministic stub) adds the one MEASURED row: the run's own model
    # priced from its real per-doc usage. This is the only row marked measured=True.
    run_model = scored[0].model if scored else None
    if provider != "stub" and run_model is not None and run_model in PRICING:
        cost_rows.append(CostRow(model=run_model, cost_per_doc=measured, measured=True))
    opus, sonnet = cost_rows[0].cost_per_doc, cost_rows[1].cost_per_doc
    delta = round(100.0 * (opus - sonnet) / opus, 1) if opus else None

    n_scored = len({r.id for r in records if r.repeat == 1 and r.scored})
    return Leaderboard(
        generated_at=generated_at,
        prompt_version=PROMPT_VERSION,
        normalize_version=NORMALIZE_VERSION,
        provider=provider,
        repeats=repeats,
        n_docs=n_docs,
        n_scored=n_scored,
        n_routing_docs=len({r.id for r in records}),
        fields=_field_metrics(scored),
        macro_f1=_stat_over_repeats(scored, _macro_f1),
        hallucination_rate=halluc_rate,
        hallucination_count=halluc,
        n_null_gold=null_gold,
        routing_accuracy=routing_acc,
        empty_kind_accuracy=empty_kind_acc,
        measured_cost_per_doc=measured,
        cost_rows=cost_rows,
        sonnet_cost_delta_pct=delta,
    )


# ---------------------------------------------------------------------------
# Rendering (ASCII-only — prints identically on any console, pastes into the README).
# ---------------------------------------------------------------------------

_RULE = "=" * 78


def _bar(value: float, width: int = 10) -> str:
    filled = round(value * width)
    return "#" * filled + "-" * (width - filled)


def render_leaderboard(lb: Leaderboard, latencies: list[float] | None = None) -> str:
    lines = [
        _RULE,
        f" CHARTEXTRACT EVAL  |  frozen gold set  |  {lb.n_docs} docs  |  N={lb.repeats} runs",
        f" prompt {lb.prompt_version}  |  normalize {lb.normalize_version}  |  "
        f"provider {lb.provider}  |  {lb.generated_at}",
        _RULE,
        f"  MACRO-F1            {lb.macro_f1.mean:.2f} +/- {lb.macro_f1.spread:.2f}",
        f"  HALLUCINATION-RATE  {lb.hallucination_rate.mean:.2f}  "
        f"({lb.hallucination_count} hallucinated / {lb.n_null_gold} null-gold fields)  "
        f"{'<<< 0 across the frozen set' if lb.hallucination_count == 0 else '<<< NON-ZERO'}",
        "",
        f"  {'Field':<22}{'Prec':>6}{'Recall':>8}{'F1':>6}   distribution",
    ]
    for m in lb.fields:
        note = ""
        if m.support == 0:
            note = "  (null-only)"
        lines.append(
            f"  {m.field:<22}{m.precision:>6.2f}{m.recall:>8.2f}{m.f1:>6.2f}   {_bar(m.f1)}{note}"
        )

    lines += [
        "",
        f"  Routing accuracy  {lb.routing_accuracy:.2f}   "
        f"({lb.n_routing_docs} docs incl. routing-only discharge)",
    ]
    if lb.empty_kind_accuracy is not None:
        lines.append(
            f"  Empty-kind agreement  {lb.empty_kind_accuracy:.2f}   "
            "(not_found vs not_assessed labelled correctly)"
        )

    lines += ["", "  -- cost comparison (per doc) --"]
    for row in lb.cost_rows:
        tag = "(measured)" if row.measured else "(estimate)"
        if row.model == "claude-sonnet-4-6" and lb.sonnet_cost_delta_pct is not None:
            tag = f"(down {lb.sonnet_cost_delta_pct:.0f}% cost vs Opus, estimate)"
        lines.append(f"  {row.model:<20} ${row.cost_per_doc:.4f}/doc   {tag}")
    lines.append(
        f"  measured this run    ${lb.measured_cost_per_doc:.4f}/doc  (provider {lb.provider})"
    )

    if latencies:
        lines.append(
            f"  latency  mean {statistics.mean(latencies):.3f}s  "
            f"max {max(latencies):.3f}s  (n={len(latencies)})"
        )

    if lb.n_scored < lb.n_docs:
        lines.append(
            f"  NOTE: partial run - {lb.n_scored} of {lb.n_docs} docs scored "
            "(the rest errored; numbers cover only the scored docs)."
        )

    lines += [
        "",
        f"  (i) {lb.n_docs} synthetic docs - report F1 with wide intervals; not real PHI.",
        _RULE,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persistence (jsonl per-record rows — deterministic, no timestamp/latency inside).
# ---------------------------------------------------------------------------


def write_jsonl(records: list[DocRecord], path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(r.model_dump_json() + "\n")
    return path


def read_jsonl(path: Path | str) -> list[DocRecord]:
    return [
        DocRecord.model_validate_json(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def _load_dotenv() -> None:
    """Load provider keys from a repo-root (or eval/) ``.env`` so ``--provider openai`` works.

    Same tiny no-overwrite parser as the engine's; the stub path never needs it. Keys already in
    the environment win; a missing file is ignored.
    """
    here = Path(__file__).resolve().parent
    for path in (here.parent / ".env", here / ".env"):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m eval.run", description="ChartExtract eval harness.")
    p.add_argument(
        "--provider",
        choices=["stub", "anthropic", "openai", "live"],
        default="stub",
        help="stub (default, deterministic, no key) or a live provider (opt-in, needs a key)",
    )
    p.add_argument("--repeats", type=int, default=1, help="repeats per doc (N); stub spread is ~0")
    p.add_argument(
        "--batch",
        action="store_true",
        help="run the live sweep through the Batch API (50%% cheaper; needs a live key)",
    )
    p.add_argument("--gold", default=str(GOLD_DIR), help="gold-set root")
    p.add_argument("--date", default=None, help="artifact date stamp (YYYYMMDD); default today")
    p.add_argument(
        "--out", default=None, help="jsonl output path (default docs/eval/leaderboard-<date>.jsonl)"
    )
    p.add_argument("--no-write", action="store_true", help="print only; do not write the artifact")
    return p


def _today_stamp() -> str:
    from datetime import date  # local import: only the CLI needs a wall-clock date

    return date.today().strftime("%Y%m%d")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # never crash on a non-UTF-8 console (§15)
        reconfig = getattr(stream, "reconfigure", None)
        if reconfig is not None:
            try:
                reconfig(errors="replace")
            except (ValueError, OSError):  # pragma: no cover - defensive
                pass

    provider_name = "openai" if args.provider == "live" else args.provider
    if provider_name != "stub":
        _load_dotenv()
        if not live_key_present():
            print(
                f"note: no live key available - falling back to the deterministic stub "
                f"(set a provider key to run --provider {provider_name}).",
                file=sys.stderr,
            )
            provider_name = "stub"

    try:
        records = load_gold(args.gold)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    repeats = max(1, args.repeats)
    use_batch = args.batch and provider_name != "stub"
    if args.batch and provider_name == "stub":
        print(
            "note: --batch needs a live key (the Batch API is a network call) - "
            "running the synchronous stub sweep instead.",
            file=sys.stderr,
        )
    if use_batch:
        doc_records, latencies = run_suite_batch(
            records, repeats=repeats, model=default_provider().model, root=args.gold
        )
    else:
        doc_records, latencies = run_suite(
            records, provider_name=provider_name, repeats=repeats, root=args.gold
        )

    n_docs = sum(1 for r in records if r.labels)
    stamp = args.date or _today_stamp()
    leaderboard = aggregate(
        doc_records,
        n_docs=n_docs,
        generated_at=stamp,
        provider="openai-batch" if use_batch else provider_name,
        repeats=repeats,
    )
    rendered = render_leaderboard(leaderboard, latencies)
    print(rendered)

    if not args.no_write:
        out = Path(args.out) if args.out else ARTIFACT_DIR / f"leaderboard-{stamp}.jsonl"
        write_jsonl(doc_records, out)
        out.with_suffix(".txt").write_text(rendered + "\n", encoding="utf-8", newline="\n")
        print(f"\nwrote {len(doc_records)} run records -> {out}", file=sys.stderr)

    # The headline is a soft gate: a non-zero hallucination count on the deterministic stub means
    # the oracle/scoring regressed. Live runs report honestly and never fail the process here.
    if provider_name == "stub" and leaderboard.hallucination_count != 0:
        print("STUB HALLUCINATION-RATE REGRESSED (expected 0)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - thin entrypoint
    raise SystemExit(main())
