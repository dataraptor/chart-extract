"""Token-bucket usage + per-model pricing (spec §10, Appendix A).

**This module owns the money number.** A run accumulates a :class:`Usage` (classify + extract)
and :func:`price` turns it into the USD ``cost_usd`` recorded on every ``ExtractionResult``.
Pricing is pinned per model id (Appendix A, verified 2026-06-26); an unknown model **raises**
(never a silent ``0.0``) so nobody ships a fabricated cost. No model and no network here — pure
arithmetic over recorded token counts.
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


#: USD per token, keyed by model id (Appendix A, verified 2026-06-26).
#: Opus headlines extraction; Sonnet is the cost-row comparison; Haiku is the doc-type classifier.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-8": {"input": 5 / 1e6, "output": 25 / 1e6},
    "claude-sonnet-4-6": {"input": 3 / 1e6, "output": 15 / 1e6},
    # TODO verify (Split 04) against the bundled `claude-api` reference; placeholder for now.
    "claude-haiku-4-5-20251001": {"input": 0.80 / 1e6, "output": 4 / 1e6},
    # The stub provider reports this model id; price it as free so offline runs show $0 cleanly.
    "stub-model": {"input": 0.0, "output": 0.0},
}


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
