"""Split 11 — prompt caching surfaced + priced (Tier-1, no key, mocked SDK).

The live provider is GPT-5.5 (automatic caching, no ``cache_control``). These exercise the realized
caching path: a mocked ``prompt_tokens_details.cached_tokens`` flows into ``Usage.cache_read_input_
tokens``, the fresh ``input_tokens`` excludes it (no double-count), ``price`` charges cache reads at
the input rate, the shared prefix is sent stable-and-first (so the provider's cache can hit), and a
sub-floor miss is just a miss — never an error.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

from chartextract import MIN_CACHEABLE_PREFIX_TOKENS, Usage, price
from chartextract.provider.openai import OpenAIProvider
from chartextract.schemas import Field, PathologySchema


def _usage(prompt: int = 0, completion: int = 0, cached: int | None = None) -> SimpleNamespace:
    details = SimpleNamespace(cached_tokens=cached) if cached is not None else None
    return SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion, prompt_tokens_details=details
    )


def _path_json() -> str:
    inst = PathologySchema(
        specimen=Field(value="Left breast core biopsy", source_span="x", confidence=0.9),
        diagnosis=Field(value="Invasive ductal carcinoma", source_span="x", confidence=0.9),
        grade=Field(value="2", source_span="x", confidence=0.9),
        tumor_size_cm=Field(value=1.4, source_span="x", confidence=0.9),
        er_status=Field(value="positive", source_span="x", confidence=0.9),
        pr_status=Field(value="positive", source_span="x", confidence=0.9),
        her2_status=Field(value="negative", source_span="x", confidence=0.9),
        margin_status=Field(value=None, source_span="", confidence=0.0),
        lymph_nodes_positive=Field(value=None, source_span="", confidence=0.0),
    )
    return inst.model_dump_json()


def _response(usage: SimpleNamespace) -> SimpleNamespace:
    msg = SimpleNamespace(content=_path_json(), refusal=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=usage
    )


class _FakeCompletions:
    def __init__(self, resp: SimpleNamespace) -> None:
        self._resp = resp
        self.calls: list[dict[str, Any]] = []

    def create(self, **kw: Any) -> SimpleNamespace:
        self.calls.append(kw)
        return self._resp


class _FakeClient:
    def __init__(self, resp: SimpleNamespace) -> None:
        self.completions = _FakeCompletions(resp)
        self.chat = SimpleNamespace(completions=self.completions)


def _provider(resp: SimpleNamespace) -> OpenAIProvider:
    return OpenAIProvider(client=_FakeClient(resp))


# --- cached_tokens → Usage split (no double-count) ----------------------------


def test_cached_tokens_flow_into_cache_bucket_and_split_off_fresh_input() -> None:
    # prompt_tokens INCLUDES the cached prefix: 5000 total, 4096 cached → 904 fresh + 4096 cache.
    p = _provider(_response(_usage(prompt=5000, completion=180, cached=4096)))
    _parsed, usage = p.extract("SYS", "DOCUMENT:\n...", PathologySchema)
    assert usage.input_tokens == 904
    assert usage.cache_read_input_tokens == 4096
    assert usage.output_tokens == 180
    # the two buckets reconstruct the provider's prompt_tokens exactly (no token lost or doubled).
    assert usage.input_tokens + usage.cache_read_input_tokens == 5000


def test_no_details_means_no_cache_read_not_an_error() -> None:
    # Sub-floor / first call: no cached prefix reported → a clean cache MISS, never raised.
    p = _provider(_response(_usage(prompt=1000, completion=180)))  # no prompt_tokens_details
    _parsed, usage = p.extract("SYS", "x", PathologySchema)
    assert usage.cache_read_input_tokens == 0
    assert usage.input_tokens == 1000


def test_zero_cached_tokens_is_a_clean_miss() -> None:
    p = _provider(_response(_usage(prompt=900, completion=10, cached=0)))
    _parsed, usage = p.extract("SYS", "x", PathologySchema)
    assert usage.cache_read_input_tokens == 0
    assert usage.input_tokens == 900


# --- pricing: cache reads at the input rate -----------------------------------


def test_price_charges_cache_reads_at_input_rate() -> None:
    # 904 fresh + 4096 cache-read, both at the input rate; output at the output rate.
    usage = Usage(input_tokens=904, cache_read_input_tokens=4096, output_tokens=180)
    expected = (904 + 4096) * (1.25 / 1e6) + 180 * (10 / 1e6)
    assert math.isclose(price(usage, "gpt-5.5"), expected, rel_tol=1e-9)
    # A fully-cached prefix costs the same as a fully-fresh one of the same size (conservative v1).
    cached = price(Usage(input_tokens=0, cache_read_input_tokens=5000), "gpt-5.5")
    fresh = price(Usage(input_tokens=5000), "gpt-5.5")
    assert math.isclose(cached, fresh, rel_tol=1e-9)


# --- the prefix is stable and first (so the provider's cache CAN hit) ---------


def test_prefix_is_stable_and_first_system_then_document() -> None:
    p = _provider(_response(_usage(prompt=1000, completion=10)))
    p.extract("STABLE-SYSTEM-PREFIX", "DOCUMENT:\nvolatile body", PathologySchema)
    messages = p._client.completions.calls[0]["messages"]
    # system prefix first, per-doc document second — the cache-friendly order (claude-api ref).
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "STABLE-SYSTEM-PREFIX"
    assert messages[1]["role"] == "user"


# --- the documented caching floors ------------------------------------------


def test_caching_floors_match_the_claude_api_reference() -> None:
    assert MIN_CACHEABLE_PREFIX_TOKENS["claude-opus-4-8"] == 4096
    assert MIN_CACHEABLE_PREFIX_TOKENS["claude-sonnet-4-6"] == 2048
    assert MIN_CACHEABLE_PREFIX_TOKENS["claude-haiku-4-5-20251001"] == 4096
    assert MIN_CACHEABLE_PREFIX_TOKENS["gpt-5.5"] == 1024
