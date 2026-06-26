"""Adapter wiring — provider selection, bundled samples, and the eval-leaderboard mapping.

Everything here **reuses** core/eval; it reinvents nothing. Provider selection mirrors the CLI's
rule (live GPT-5.5 when a key is configured, else the deterministic stub); samples are read through
the engine's :func:`chartextract.load` so their ``text`` is byte-identical to the offset source;
the eval mapping folds the frozen leaderboard artifact (or an on-demand stub run) into the UIUX
§5.5 shape.
"""

from __future__ import annotations

from pathlib import Path

import chartextract
from chartextract import (
    StubProvider,
    default_provider,
    live_key_present,
    load,
    stub_for_intake,
    stub_for_path_report,
)
from chartextract.provider.base import ProviderClient

from .errors import APIError
from .schemas import EvalCostRow, EvalRow, EvalSummary, SampleItem

#: Repo-root-relative locations, resolved from the installed (editable) ``chartextract`` package:
#: ``core/src/chartextract`` → ``parents[3]`` is the repo root.
_REPO_ROOT = Path(chartextract.__file__).resolve().parents[3]
_EXAMPLES_DIR = _REPO_ROOT / "examples"
_EVAL_ARTIFACT_DIR = _REPO_ROOT / "docs" / "eval"

#: The bundled examples the UI offers (file stem → display name → doc-type hint).
_SAMPLES: tuple[tuple[str, str, str], ...] = (
    ("path_report", "path_report.txt", "pathology"),
    ("intake_form", "intake_form.txt", "intake"),
)


# ---------------------------------------------------------------------------
# Provider selection (reuse Split 03/04 — never reinvent).
# ---------------------------------------------------------------------------


def server_default_provider_name() -> str:
    """The provider the server uses when a request doesn't override it: live when a key is
    configured (same rule as the CLI), else the offline stub."""
    return "openai" if live_key_present() else "stub"


def _stub_for(text: str, schema: str | None) -> ProviderClient:
    """Build the offline stub preloaded to match the resolved doc type (mirrors the CLI).

    An explicit ``schema`` selects the canned output; otherwise a header-keyword guess does. An
    unrecognized doc returns a bare stub so the router surfaces the "pick a schema" path (409).
    """
    key = schema or _guess_doc_type(text)
    if key == "intake":
        return stub_for_intake()
    if key == "pathology":
        return stub_for_path_report()
    return StubProvider(classify_result=("unknown", 0.0))


def _guess_doc_type(text: str) -> str:
    """Minimal offline doc-type guess from header keywords (``unknown`` if unsure)."""
    head = text[:200].lower()
    if "pathology" in head:
        return "pathology"
    if "intake" in head:
        return "intake"
    return "unknown"


def get_provider(name: str | None, *, text: str, schema: str | None) -> ProviderClient:
    """Resolve the :class:`ProviderClient` for a request.

    ``"stub"`` → the deterministic packaged stub; ``"openai"`` (alias ``"anthropic"``/``"live"``,
    per the realized GPT-5.5 build) → the live provider, which raises
    :class:`~chartextract.provider.base.MissingAPIKeyError` (→ 503 envelope) when no key is set.
    A default ``name`` follows :func:`server_default_provider_name`.
    """
    chosen = name or server_default_provider_name()
    if chosen == "stub":
        return _stub_for(text, schema)
    if chosen in ("openai", "anthropic", "live"):
        return default_provider()
    raise APIError(422, "bad_request", f"unknown provider {chosen!r} (use 'stub' or 'openai')")


def active_provider_health() -> tuple[str, str]:
    """``(provider_name, model_id)`` for ``/health`` — computed without constructing a client (no
    key, no network), so the probe is honest about canned vs live without billing anything."""
    if live_key_present():
        from chartextract.provider.openai import DEFAULT_MODEL

        return "openai", DEFAULT_MODEL
    return "stub", "stub"


# ---------------------------------------------------------------------------
# Bundled samples — read through the engine's loader (the offset-source invariant).
# ---------------------------------------------------------------------------


def load_samples() -> list[SampleItem]:
    """The bundled examples as picker entries. ``text`` is the canonical ``load()`` output."""
    out: list[SampleItem] = []
    for stem, name, hint in _SAMPLES:
        path = _EXAMPLES_DIR / name
        if not path.is_file():
            continue
        out.append(SampleItem(id=stem, name=name, doc_type_hint=hint, text=load(path).text))
    return out


def sample_text(sample_id: str) -> str:
    """The canonical text of a bundled sample, or a 422 ``bad_request`` for an unknown id."""
    for stem, name, _ in _SAMPLES:
        if stem == sample_id:
            return load(_EXAMPLES_DIR / name).text
    known = ", ".join(stem for stem, _, _ in _SAMPLES)
    raise APIError(422, "bad_request", f"unknown sample_id {sample_id!r} (known: {known})")


# ---------------------------------------------------------------------------
# Eval leaderboard → UIUX §5.5 summary.
# ---------------------------------------------------------------------------


def _latest_artifact() -> Path | None:
    """The newest frozen ``leaderboard-*.jsonl`` artifact, or ``None`` if none was committed."""
    if not _EVAL_ARTIFACT_DIR.is_dir():
        return None
    artifacts = sorted(_EVAL_ARTIFACT_DIR.glob("leaderboard-*.jsonl"))
    return artifacts[-1] if artifacts else None


def build_eval_summary() -> EvalSummary:
    """The leaderboard the Eval view renders.

    Prefers the **frozen artifact** Split 05 emits (deterministic, no run); falls back to a
    synchronous stub sweep when none is present. Requires the optional ``chartextract-eval``
    package; a clean 503 envelope is raised if it isn't installed.
    """
    try:
        from eval.dataset import load_gold
        from eval.run import aggregate, read_jsonl, run_suite
    except ImportError as exc:  # pragma: no cover - only when the optional extra is absent
        raise APIError(
            503,
            "internal",
            "the eval harness is not installed",
            hint="install the optional extra: pip install -e 'api/[eval]'",
        ) from exc

    records = load_gold()
    n_docs = sum(1 for r in records if r.labels)

    artifact = _latest_artifact()
    if artifact is not None:
        doc_records = read_jsonl(artifact)
        stamp = artifact.stem.removeprefix("leaderboard-")
        repeats = max((r.repeat for r in doc_records), default=1)
        lb = aggregate(
            doc_records, n_docs=n_docs, generated_at=stamp, provider="stub", repeats=repeats
        )
    else:  # pragma: no cover - the artifact is committed in this repo
        doc_records, _ = run_suite(records, provider_name="stub", repeats=1)
        lb = aggregate(
            doc_records, n_docs=n_docs, generated_at="on-demand", provider="stub", repeats=1
        )

    rows = [
        EvalRow(
            name=m.field,
            p=m.precision,
            r=m.recall,
            f1=m.f1,
            note="null-only" if m.support == 0 else "",
        )
        for m in lb.fields
    ]
    # The cost rows price the same reference usage under each model (quality is the run's macro-F1);
    # the delta is carried on the cheaper comparison row, mirroring the eval leaderboard.
    cost = [
        EvalCostRow(
            model=cr.model,
            f1=lb.macro_f1.mean,
            usd_per_doc=cr.cost_per_doc,
            delta=(lb.sonnet_cost_delta_pct if cr.model == "claude-sonnet-4-6" else None),
        )
        for cr in lb.cost_rows
    ]
    caption = (
        f"{lb.n_docs} synthetic docs (N={lb.repeats}); "
        f"hallucination-rate {lb.hallucination_rate.mean:.2f} "
        f"({lb.hallucination_count} hallucinated / {lb.n_null_gold} null-gold fields); "
        "report F1 with wide intervals — not real PHI."
    )
    return EvalSummary(
        gold_count=lb.n_docs,
        n_runs=lb.repeats,
        macro_f1=lb.macro_f1.mean,
        hallucination_rate=lb.hallucination_rate.mean,
        routing_accuracy=lb.routing_accuracy,
        rows=rows,
        cost=cost,
        caption=caption,
    )
