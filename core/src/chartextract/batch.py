"""Batch-API support — submit many docs as one job, re-associate results by ``custom_id``.

**This module owns the batch contract.** The Batch API is ~50% cheaper than synchronous calls
(:data:`~chartextract.cost.BATCH_DISCOUNT`), runs asynchronously, and returns results **in any
order** — so every request is keyed by an opaque ``custom_id`` (the gold doc id) and the caller
re-associates on the way out. The load-bearing, pure, fully-offline-testable piece is
:func:`collate_results`; the live submission (:func:`run_openai_batch`) is opt-in and needs a key.

A result that never comes back (a ``custom_id`` in the requests but absent from the results) is
**surfaced**, never silently dropped — the §15 "honest, never fake" rule applied to batching.

claude-api reference (Split 11): batches are 50% cheaper, async, unordered → key by ``custom_id``;
structured output (``response_format``) works inside a batch unchanged. The realized live provider
is GPT-5.5, whose OpenAI Batch API mirrors that contract (``/v1/batches`` over a JSONL of
``/v1/chat/completions`` request bodies, each carrying its ``custom_id``).
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, TypeVar

from pydantic import BaseModel

from .cost import Usage
from .provider.base import ProviderError
from .provider.openai import OpenAIProvider, _strict_response_format, _usage

T = TypeVar("T")


@dataclass(frozen=True)
class BatchRequest:
    """One extraction queued in a batch — its ``custom_id`` is how the result is found again.

    ``system`` / ``document_text`` are the same two turns the synchronous
    :meth:`~chartextract.provider.openai.OpenAIProvider.extract` sends; ``schema_model`` is the
    structured-output target (its strict JSON schema becomes the request's ``response_format``).
    """

    custom_id: str
    system: str
    document_text: str
    schema_model: type[BaseModel]


class MissingBatchResultError(ProviderError):
    """Raised when a ``custom_id`` was submitted but no result came back (surfaced, not dropped)."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = list(missing)
        super().__init__(
            f"batch is missing {len(self.missing)} result(s) by custom_id: {sorted(self.missing)}"
        )


def collate_results(
    requests: Iterable[BatchRequest], results: Mapping[str, T]
) -> list[tuple[BatchRequest, T]]:
    """Re-associate **unordered** ``results`` (keyed by ``custom_id``) to ``requests``, in order.

    Returns ``[(request, result), ...]`` in the original request order regardless of the order the
    batch produced them. A ``custom_id`` present in ``requests`` but absent from ``results`` raises
    :class:`MissingBatchResultError` listing every missing id — a batch that lost a doc never scores
    as if that doc had passed. A duplicate ``custom_id`` across requests is rejected up front (it is
    the join key, so it must be unique).
    """
    reqs = list(requests)
    seen: set[str] = set()
    for r in reqs:
        if r.custom_id in seen:
            raise ValueError(f"duplicate custom_id in batch requests: {r.custom_id!r}")
        seen.add(r.custom_id)

    missing = [r.custom_id for r in reqs if r.custom_id not in results]
    if missing:
        raise MissingBatchResultError(missing)
    return [(r, results[r.custom_id]) for r in reqs]


# ---------------------------------------------------------------------------
# Live submission (opt-in; needs a key). The pure path above is what CI tests.
# ---------------------------------------------------------------------------


def run_openai_batch(
    provider: OpenAIProvider,
    requests: list[BatchRequest],
    *,
    poll_seconds: float = 10.0,
    timeout_seconds: float = 86_400.0,
) -> dict[str, tuple[BaseModel, Usage]]:
    """Submit ``requests`` as one OpenAI Batch job, poll to completion, collect by ``custom_id``.

    Returns ``{custom_id: (parsed_instance, usage)}`` — the **same** ``(BaseModel, Usage)`` shape
    :meth:`OpenAIProvider.extract` yields, so the eval scorer treats a batched result exactly like a
    synchronous one. Results arrive unordered; we re-key by ``custom_id`` here and the caller hands
    the dict to :func:`collate_results`. Raises :class:`~chartextract.provider.base.ProviderError`
    if the batch fails or times out — surfaced, never a partial-as-complete.

    This is the **only** place that touches the network in this module; it is exercised live
    (``@pytest.mark.api``) and never in the keyless Tier-1 suite.
    """
    client = provider._client  # the configured (Azure/std) OpenAI client
    lines = [
        json.dumps(
            {
                "custom_id": r.custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": provider.model,
                    "messages": [
                        {"role": "system", "content": r.system},
                        {"role": "user", "content": r.document_text},
                    ],
                    "response_format": _strict_response_format(r.schema_model),
                    "max_completion_tokens": provider._max_completion_tokens,
                },
            }
        )
        for r in requests
    ]
    payload = ("\n".join(lines) + "\n").encode("utf-8")

    upload = client.files.create(file=("batch.jsonl", payload), purpose="batch")
    batch = client.batches.create(
        input_file_id=upload.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
    )

    deadline = time.monotonic() + timeout_seconds
    while True:
        batch = client.batches.retrieve(batch.id)
        if batch.status == "completed":
            break
        if batch.status in {"failed", "expired", "cancelled", "cancelling"}:
            raise ProviderError(f"batch {batch.id} ended with status {batch.status!r}")
        if time.monotonic() > deadline:
            raise ProviderError(f"batch {batch.id} did not complete within {timeout_seconds}s")
        time.sleep(poll_seconds)

    by_id: dict[str, tuple[BaseModel, Usage]] = {}
    schema_by_id = {r.custom_id: r.schema_model for r in requests}
    content = client.files.content(batch.output_file_id)
    for raw in content.text.splitlines():
        if not raw.strip():
            continue
        rec = json.loads(raw)
        cid = rec["custom_id"]
        body = rec["response"]["body"]
        message = body["choices"][0]["message"]
        parsed = schema_by_id[cid].model_validate_json(message["content"])
        # _usage reads usage off a response's `.usage`; wrap the batch line's usage dict to match.
        by_id[cid] = (parsed, _usage(SimpleNamespace(usage=_as_obj(body.get("usage")))))
    return by_id


def _as_obj(d: Any) -> Any:
    """Turn a usage dict from a batch JSON line into the attribute-shape :func:`_usage` expects."""
    if d is None:
        return None
    details = d.get("prompt_tokens_details")
    return SimpleNamespace(
        prompt_tokens=d.get("prompt_tokens", 0),
        completion_tokens=d.get("completion_tokens", 0),
        prompt_tokens_details=(
            SimpleNamespace(cached_tokens=details.get("cached_tokens", 0))
            if isinstance(details, dict)
            else None
        ),
    )
