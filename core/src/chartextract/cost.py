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
    # Anthropic reference rows (spec Appendix A) — not called in this build; see note above.
    "claude-opus-4-8": {"input": 5 / 1e6, "output": 25 / 1e6},
    "claude-sonnet-4-6": {"input": 3 / 1e6, "output": 15 / 1e6},
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
