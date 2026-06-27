"""Token-bucket usage + per-model pricing (spec §10, Appendix A).

**This module owns the money number.** A run accumulates a :class:`Usage` (classify + extract)
and :func:`price` turns it into the USD ``cost_usd`` recorded on every ``ExtractionResult``.
Pricing is pinned per model id (Appendix A, verified 2026-06-26); an unknown model **raises**
(never a silent ``0.0``) so nobody ships a fabricated cost. No model and no network here — pure
arithmetic over recorded token counts.

claude-api reference consulted (Split 11, the ``claude-api`` skill, 2026-06-27) — facts pinned
below so nobody re-derives them:

- **Pricing (per MTok, input / output):** Opus 4.8 ``$5 / $25``; Sonnet 4.6 ``$3 / $15``;
  Haiku 4.5 ``$1.00 / $5.00``. The Split 03/04 Haiku placeholder (``$0.80 / $4``) was *wrong* and
  is corrected here — the claude-api reference wins per the Split 11 brief.
- **Prompt caching:** apply ``cache_control: {"type": "ephemeral"}`` to the stable prefix; verify a
  hit via ``usage.cache_read_input_tokens``. Cache reads cost ~0.1x the base input rate on
  Anthropic; **this engine prices them conservatively at the full input rate** (no read discount in
  v1 — the reported ``cost_usd`` is therefore an *upper bound*, never an understatement). The
  minimum cacheable prefix is model-dependent (:data:`MIN_CACHEABLE_PREFIX_TOKENS`); a prefix below
  the floor silently does **not** cache — a cache miss on one short demo doc is expected, not a bug.
- **Batch API:** 50% cheaper, async, results **unordered → key by ``custom_id``**
  (see :mod:`chartextract.batch`).

This build's realized live provider is **GPT-5.5** (Azure OpenAI) — its caching is *automatic*
(no ``cache_control`` param; cached prompt tokens are reported under
``usage.prompt_tokens_details.cached_tokens`` and surfaced into the same
``cache_read_input_tokens`` bucket). The Anthropic rows stay as the spec's reference pricing.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Usage(BaseModel):
    """Token buckets for one (or, when summed, several) model inferences.

    ``cache_read_input_tokens`` mirrors Anthropic's response field name; cached reads are billed at
    the model's **input** rate (no separate read multiplier in v1 — kept honest, §10). The fresh
    ``input_tokens`` already excludes the cache bucket, so the price formula never double-counts.
    """

    model_config = ConfigDict(extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        """Bucket-wise sum so a run can accumulate the classify call + the extract call."""
        if not isinstance(other, Usage):
            return NotImplemented
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
        )

    def __radd__(self, other: object) -> Usage:
        """Let ``sum(usages)`` work — it starts from the int ``0``."""
        if other == 0:
            return self
        return self.__add__(other)  # type: ignore[arg-type]


#: USD per token, keyed by model id.
#: ``gpt-5.5`` is the **live** provider in this build (Azure OpenAI; the only credential available
#: in this repo — see ``provider/openai.py`` and the Split 04 progress note). The Anthropic rows are
#: retained as the reference pricing from spec Appendix A (verified 2026-06-26): Opus would headline
#: extraction, Sonnet is the cost row, Haiku the classifier — kept so the eval leaderboard
#: (Split 05/11) can still report them, even though this build calls GPT-5.5.
PRICING: dict[str, dict[str, float]] = {
    # Azure OpenAI GPT-5.5 — the live extraction + classifier model in this build.
    # NOTE: pinned to the published GPT-5.x list price; revisit if the deployment's rate differs.
    "gpt-5.5": {"input": 1.25 / 1e6, "output": 10 / 1e6},
    # Anthropic reference rows (spec Appendix A; reconciled against the claude-api skill, Split 11)
    # — not called in this build; see note above.
    "claude-opus-4-8": {"input": 5 / 1e6, "output": 25 / 1e6},
    "claude-sonnet-4-6": {"input": 3 / 1e6, "output": 15 / 1e6},
    "claude-haiku-4-5-20251001": {"input": 1.00 / 1e6, "output": 5 / 1e6},
    # The stub provider reports this model id; price it as free so offline runs show $0 cleanly.
    "stub-model": {"input": 0.0, "output": 0.0},
}

#: Minimum cacheable prefix (tokens) per model — a prefix shorter than this silently does **not**
#: cache (no error, ``cache_read_input_tokens`` stays 0). Anthropic floors from the claude-api
#: reference (Opus/Haiku 4.5 = 4096; Sonnet 4.6 = 2048); the realized GPT-5.5 build uses OpenAI
#: automatic caching, which kicks in at ~1024 prompt tokens. A single short demo doc is below every
#: floor — its cache *miss* is expected behaviour, not a defect (Split 11 carry-forward).
MIN_CACHEABLE_PREFIX_TOKENS: dict[str, int] = {
    "claude-opus-4-8": 4096,
    "claude-sonnet-4-6": 2048,
    "claude-haiku-4-5-20251001": 4096,
    "gpt-5.5": 1024,
}

#: 50% batch discount on the Batch API (claude-api reference; OpenAI's Batch API matches it). Used
#: by :mod:`chartextract.batch` to price an N-doc eval sweep submitted as one batch.
BATCH_DISCOUNT = 0.5


def price(usage: Usage, model: str) -> float:
    """USD cost of ``usage`` for ``model`` — cached reads billed at the input rate.

    An unknown model id raises ``KeyError`` (never a silent ``0.0``), so a mis-keyed model surfaces
    immediately instead of shipping a fabricated number.
    """
    try:
        rates = PRICING[model]
    except KeyError as exc:
        raise KeyError(f"No pricing pinned for model {model!r}. Known: {sorted(PRICING)}") from exc
    billable_input = usage.input_tokens + usage.cache_read_input_tokens
    return billable_input * rates["input"] + usage.output_tokens * rates["output"]


def price_batch(usage: Usage, model: str) -> float:
    """USD cost of ``usage`` for ``model`` **at the Batch API discount** (50%, §10).

    The Batch API is ~50% cheaper than synchronous calls, so an N-doc eval sweep submitted as one
    batch (:mod:`chartextract.batch`) is priced through here. Pure scaling of :func:`price` — same
    cache-read handling, same unknown-model ``KeyError``.
    """
    return price(usage, model) * BATCH_DISCOUNT
