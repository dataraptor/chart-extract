"""Dev-only ``?simulate=<type>`` affordance for ``POST /api/extract`` (Split 09).

Each designed UI edge state (UIUX §5/§7/§9) needs a **real backend signal** to render against, but
the deterministic stub can't naturally produce a refusal, a truncation, a no-text-layer document,
or an ambiguous span. This module manufactures each signal on demand so every edge state is
exercisable offline (and screenshot-able) — **strictly behind the ``CHARTEXTRACT_DEV`` flag**. It
is inert in production: :func:`is_enabled` is ``False`` unless the operator opts in, and
:func:`maybe_simulate` then ignores the query param entirely (Split 12 verifies the prod default).

Two kinds of simulation, neither hand-faked:

* **error envelopes** — raise the *same typed core exception* the real path would, so the existing
  handlers in :mod:`chartextract_api.errors` emit the identical envelope the UI maps to a notice.
* **degraded results** — return a genuine engine :class:`~chartextract.ExtractionResult`, tweaked
  to carry one edge signal (``highlight_available=False`` for no-text-layer; an ``ambiguous_span``
  field for ambiguity; a mostly-``not_found`` record for the misroute hint). Each is built off a
  real stub extraction, so the JSON shape is always valid.
"""

from __future__ import annotations

import os
from typing import Any

from chartextract import extract, stub_for_path_report
from chartextract.provider.base import (
    MissingAPIKeyError,
    RefusalError,
    TruncatedError,
)
from chartextract.router import UnknownDocTypeError

from . import deps
from .errors import APIError

#: The edge ``type`` codes the dev hook can produce (mirrors the error-envelope + result signals).
SIMULATABLE: frozenset[str] = frozenset(
    {
        "refusal",
        "truncated",
        "unknown_doc_type",
        "missing_api_key",
        "unsupported_file",
        "no_text_layer",
        "ambiguous",
        "misroute",
    }
)


def is_enabled() -> bool:
    """Whether the dev simulate hook is active. Off unless ``CHARTEXTRACT_DEV`` is truthy."""
    return os.environ.get("CHARTEXTRACT_DEV", "").strip().lower() in ("1", "true", "yes", "on")


def maybe_simulate(name: str | None) -> dict[str, Any] | None:
    """Return a simulated result dict, raise a typed error, or ``None`` to fall through to extract.

    Returns ``None`` (so the caller runs the normal extraction) when the hook is disabled or no
    ``simulate`` param was supplied. An unknown name is a ``400 bad_request`` so a typo is caught
    rather than silently ignored — but only while the hook is enabled.
    """
    if not name or not is_enabled():
        return None
    if name not in SIMULATABLE:
        known = ", ".join(sorted(SIMULATABLE))
        raise APIError(400, "bad_request", f"unknown simulate type {name!r} (known: {known})")

    # --- error envelopes: raise the real typed exception, reuse the real handlers. ---
    if name == "refusal":
        raise RefusalError("the model declined to extract from this document (safety refusal)")
    if name == "truncated":
        raise TruncatedError("the model output was truncated before the record was complete")
    if name == "unknown_doc_type":
        raise UnknownDocTypeError("unknown")
    if name == "missing_api_key":
        raise MissingAPIKeyError(
            "no live provider key configured (set AZURE_OPENAI_API_KEY or OPENAI_API_KEY)"
        )
    if name == "unsupported_file":
        raise APIError(
            415,
            "unsupported_file",
            "unsupported file type '.png'",
            hint="text-layer PDF or .txt only (OCR is out of scope)",
        )

    # --- degraded results: a genuine stub extraction, tweaked to carry one edge signal. ---
    if name == "no_text_layer":
        return _no_text_layer()
    if name == "ambiguous":
        return _ambiguous()
    if name == "misroute":
        return _misroute()
    raise AssertionError(f"unreachable simulate branch {name!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Degraded-result builders — start from a real stub ExtractionResult.
# ---------------------------------------------------------------------------


def _path_result() -> dict[str, Any]:
    """A real stub pathology extraction over the bundled sample (the honest base to tweak)."""
    base = extract(
        deps.sample_text("path_report"),
        schema="pathology",
        provider=stub_for_path_report(),
        source_name="path_report",
    )
    return base.model_dump()


def _recount(result: dict[str, Any]) -> dict[str, Any]:
    """Recompute the derived ``n_*`` counts after tweaking ``fields`` so the record stays honest."""
    fields = result["fields"]
    result["n_fields"] = len(fields)
    result["n_grounded"] = sum(1 for f in fields if f["value"] is not None)
    result["n_null"] = sum(1 for f in fields if f["value"] is None)
    result["n_needs_review"] = sum(
        1 for f in fields if f["flag"] in ("needs_review", "ambiguous_span")
    )
    return result


def _no_text_layer() -> dict[str, Any]:
    """The vision-fallback record: values were extracted, but offsets are unavailable (§4)."""
    result = _path_result()
    result["highlight_available"] = False
    for f in result["fields"]:
        f["char_start"] = None
        f["char_end"] = None
        f["match_quality"] = "none"
        f["n_matches"] = 0
    return result


def _ambiguous() -> dict[str, Any]:
    """A record where ``er_status`` grounds to a short span that occurs twice → ``ambiguous_span``.

    The span ``"positive"`` appears in both ``ER positive`` and ``PR positive``; the engine's §7
    rule (short span, >1 exact match) flags it ambiguous and keeps the first match's offsets — the
    anti-silent-wrong-highlight state the UI renders with a dotted underline + "1 of N" tag.
    """
    result = _path_result()
    text = deps.sample_text("path_report")
    span = "positive"
    start = text.find(span)
    n = text.count(span)
    for f in result["fields"]:
        if f["name"] == "er_status":
            f["source_span"] = span
            f["char_start"] = start
            f["char_end"] = start + len(span)
            f["match_quality"] = "exact"
            f["n_matches"] = n
            f["flag"] = "ambiguous_span"
            f["confidence"] = 0.92
            break
    return _recount(result)


def _misroute() -> dict[str, Any]:
    """A pathology record scored against intake text — most fields fail to ground (§9 misroute).

    A *genuine* mismatch: the pathology stub proposes pathology spans, but they're grounded against
    the intake document, so they don't locate and the fields null out. The UI surfaces the
    non-blocking "looks misrouted — change schema?" hint when grounded coverage collapses.
    """
    base = extract(
        deps.sample_text("intake_form"),
        schema="pathology",
        provider=stub_for_path_report(),
        source_name="intake_form",
    )
    return base.model_dump()
