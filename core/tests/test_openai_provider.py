"""OpenAIProvider (live GPT-5.5 backend) — Tier-1, no key, driven by canned OpenAI payloads.

These exercise everything reachable without the network: strict-schema compilation, usage
normalization, the stop/refusal/truncation handling the §15/Appendix-A rules require, the bounded
parse-retry, and the doc-type classifier's never-guess fallback. The live conformance proof lives
in ``test_openai_live.py`` (``@pytest.mark.api``, auto-skipped without a key).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from chartextract.provider.base import (
    MissingAPIKeyError,
    ProviderClient,
    ProviderError,
    RefusalError,
    TruncatedError,
)
from chartextract.provider.openai import DEFAULT_MODEL, OpenAIProvider
from chartextract.schemas import (
    Field,
    IntakeSchema,
    PathologySchema,
    strict_json_schema,
)

# --- fakes (the only thing standing in for the network) ----------------------


def _usage(prompt: int = 0, completion: int = 0) -> SimpleNamespace:
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)


def _message(content: str | None = None, *, refusal: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(content=content, refusal=refusal)


def _response(
    message: SimpleNamespace,
    finish_reason: str = "stop",
    usage: SimpleNamespace | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=usage if usage is not None else _usage(),
    )


class _FakeCompletions:
    """Returns canned responses in sequence (last repeats); records each create() kwargs."""

    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = responses
        self._i = 0
        self.calls: list[dict[str, Any]] = []

    def create(self, **kw: Any) -> SimpleNamespace:
        self.calls.append(kw)
        resp = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return resp


class _FakeClient:
    def __init__(self, *responses: SimpleNamespace) -> None:
        self.completions = _FakeCompletions(list(responses))
        self.chat = SimpleNamespace(completions=self.completions)


def _provider(*responses: SimpleNamespace, **kw: Any) -> OpenAIProvider:
    return OpenAIProvider(client=_FakeClient(*responses), **kw)


def _path_json() -> str:
    """A schema-valid PathologySchema payload (the §5 worked example), as the model would return."""
    inst = PathologySchema(
        specimen=Field(
            value="Left breast core biopsy", source_span="Left breast core biopsy", confidence=0.96
        ),
        diagnosis=Field(
            value="Invasive ductal carcinoma",
            source_span="Invasive ductal carcinoma, grade 2",
            confidence=0.93,
        ),
        grade=Field(value="2", source_span="grade 2", confidence=0.9),
        tumor_size_cm=Field(value=1.4, source_span="Tumor size 1.4 cm", confidence=0.95),
        er_status=Field(value="positive", source_span="ER positive (90%)", confidence=0.94),
        pr_status=Field(value="positive", source_span="PR positive (40%)", confidence=0.92),
        her2_status=Field(value="negative", source_span="HER2 negative", confidence=0.93),
        margin_status=Field(
            value=None, source_span="Margins not assessed on this specimen", confidence=0.0
        ),
        lymph_nodes_positive=Field(value=None, source_span="", confidence=0.0),
    )
    return inst.model_dump_json()


def _classify_json(doc_type: str = "pathology", confidence: float = 0.95) -> str:
    return f'{{"doc_type": "{doc_type}", "confidence": {confidence}}}'


# --- construction / config ---------------------------------------------------


def test_missing_key_raises_catchable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    with pytest.raises(MissingAPIKeyError, match="OPENAI_API_KEY"):
        OpenAIProvider()


def test_azure_endpoint_without_key_names_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(MissingAPIKeyError, match="AZURE_OPENAI_API_KEY"):
        OpenAIProvider()


def test_unknown_model_rejected() -> None:
    with pytest.raises(ValueError, match="unknown OpenAI model"):
        OpenAIProvider(model="gpt-4o", client=_FakeClient())


def test_provider_and_model_attributes_and_protocol() -> None:
    p = _provider()
    assert p.provider == "openai"
    assert p.model == DEFAULT_MODEL == "gpt-5.5"
    assert isinstance(p, ProviderClient)  # satisfies the seam (runtime_checkable)


def test_standard_openai_client_built_from_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    from openai import OpenAI

    assert isinstance(OpenAIProvider()._client, OpenAI)


def test_azure_client_selected_when_endpoint_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "az-test-not-real")
    monkeypatch.setenv("OPENAI_API_VERSION", "2025-01-01-preview")
    from openai import AzureOpenAI

    assert isinstance(OpenAIProvider()._client, AzureOpenAI)


# --- strict-schema compilation -----------------------------------------------

_FORBIDDEN = {
    "minLength",
    "maxLength",
    "maximum",
    "minimum",
    "exclusiveMaximum",
    "exclusiveMinimum",
}


def _iter_nodes(node: Any):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_nodes(v)
    elif isinstance(node, list):
        for it in node:
            yield from _iter_nodes(it)


@pytest.mark.parametrize("model", [PathologySchema, IntakeSchema])
def test_schema_compiles_to_strict_shape(model: type) -> None:
    schema = strict_json_schema(model)
    for node in _iter_nodes(schema):
        if node.get("type") == "object" and "properties" in node:
            assert node.get("additionalProperties") is False
            assert set(node["required"]) == set(node["properties"].keys())
    keys: set[str] = set()
    for node in _iter_nodes(schema):
        keys.update(node.keys())
    assert keys.isdisjoint(_FORBIDDEN)
    # `default` keys are stripped (strict mode rejects them).
    assert "default" not in keys


def test_nullable_scalar_collapses_to_type_array() -> None:
    schema = strict_json_schema(PathologySchema)
    # lymph_nodes_positive is Field[int]: its `value` is a required int|null union.
    field_int = schema["$defs"]["Field_int_"]["properties"]["value"]
    assert field_int["type"] == ["integer", "null"]


# --- extract: happy path + request hygiene -----------------------------------


def test_extract_parses_schema_and_usage() -> None:
    resp = _response(_message(content=_path_json()), usage=_usage(prompt=1200, completion=180))
    p = _provider(resp)
    parsed, usage = p.extract("SYS", "DOCUMENT:\n...", PathologySchema)
    assert isinstance(parsed, PathologySchema)
    assert parsed.tumor_size_cm.value == 1.4
    assert parsed.lymph_nodes_positive.value is None  # null round-trips (no hallucinated count)
    assert usage.input_tokens == 1200 and usage.output_tokens == 180
    assert usage.cache_read_input_tokens == 0


def test_extract_sends_strict_schema_no_sampling_no_citations() -> None:
    p = _provider(_response(_message(content=_path_json())))
    p.extract("SYS", "DOCUMENT:\n...", PathologySchema)
    kw = p._client.completions.calls[0]
    rf = kw["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["name"] == "PathologySchema"
    # No forbidden sampling/thinking params; no citations feature.
    assert not ({"temperature", "top_p", "top_k", "seed", "budget_tokens"} & set(kw))
    assert "citations" not in kw
    # Tokens are bounded via max_completion_tokens (reasoning-model param), not max_tokens.
    assert "max_completion_tokens" in kw and "max_tokens" not in kw


# --- extract: the §15 / Appendix-A edges -------------------------------------


def test_extract_refusal_raises_without_indexing_content() -> None:
    resp = _response(_message(content=None, refusal="I can't help with that."))
    p = _provider(resp)
    with pytest.raises(RefusalError, match="refus"):
        p.extract("SYS", "x", PathologySchema)


def test_extract_content_filter_finish_reason_is_a_refusal() -> None:
    resp = _response(_message(content=None), finish_reason="content_filter")
    with pytest.raises(RefusalError):
        _provider(resp).extract("SYS", "x", PathologySchema)


def test_extract_truncation_retries_once_then_raises() -> None:
    # Both responses truncate (finish_reason=length): one bounded retry, then TruncatedError.
    trunc = _response(_message(content="{partial"), finish_reason="length", usage=_usage(10, 8192))
    p = _provider(trunc)  # the fake repeats the last response
    with pytest.raises(TruncatedError, match="truncated"):
        p.extract("SYS", "x", PathologySchema)
    # Exactly two calls — the original + a single doubled-headroom retry, never an unbounded loop.
    assert len(p._client.completions.calls) == 2
    assert p._client.completions.calls[0]["max_completion_tokens"] == 8192
    assert p._client.completions.calls[1]["max_completion_tokens"] == 16384


def test_extract_truncation_retry_can_recover() -> None:
    trunc = _response(_message(content="{partial"), finish_reason="length", usage=_usage(10, 100))
    good = _response(_message(content=_path_json()), finish_reason="stop", usage=_usage(1200, 180))
    p = _provider(trunc, good)
    parsed, usage = p.extract("SYS", "x", PathologySchema)
    assert isinstance(parsed, PathologySchema)
    # Usage accumulates across the truncated attempt and the recovery.
    assert usage.input_tokens == 1210 and usage.output_tokens == 280


def test_extract_bad_json_bounded_retry_recovers() -> None:
    bad = _response(_message(content="{not valid json"), usage=_usage(100, 5))
    good = _response(_message(content=_path_json()), usage=_usage(120, 180))
    p = _provider(bad, good)
    parsed, usage = p.extract("SYS", "x", PathologySchema)
    assert isinstance(parsed, PathologySchema)
    assert len(p._client.completions.calls) == 2
    assert usage.input_tokens == 220 and usage.output_tokens == 185
    # The retry fed a corrective instruction back to the model.
    retry_messages = p._client.completions.calls[1]["messages"]
    assert any("not valid" in m["content"] for m in retry_messages)


def test_extract_exhausts_retries_then_surfaces_provider_error() -> None:
    bad = _response(_message(content="still not json"))
    p = _provider(bad, max_retries=1)
    with pytest.raises(ProviderError, match="failed after 2 attempt"):
        p.extract("SYS", "x", PathologySchema)
    assert len(p._client.completions.calls) == 2  # 1 + 1 retry


def test_extract_handles_missing_usage() -> None:
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=_message(content=_path_json()), finish_reason="stop")],
        usage=None,
    )
    parsed, usage = _provider(resp).extract("SYS", "x", PathologySchema)
    assert isinstance(parsed, PathologySchema)
    assert usage.input_tokens == 0


# --- classify_doc_type: never silently guesses -------------------------------


def test_classify_returns_key_confidence_usage() -> None:
    resp = _response(_message(content=_classify_json("pathology", 0.95)), usage=_usage(40, 6))
    key, conf, usage = _provider(resp).classify_doc_type("PATHOLOGY REPORT ...")
    assert key == "pathology"
    assert conf == 0.95
    assert usage.input_tokens == 40 and usage.output_tokens == 6


def test_classify_low_confidence_collapses_to_unknown() -> None:
    resp = _response(_message(content=_classify_json("pathology", 0.2)))
    key, conf, _ = _provider(resp).classify_doc_type("ambiguous memo")
    assert key == "unknown"
    assert conf == 0.2


def test_classify_refusal_degrades_to_unknown_not_crash() -> None:
    resp = _response(_message(content=None, refusal="blocked"))
    key, conf, _ = _provider(resp).classify_doc_type("x")
    assert key == "unknown" and conf == 0.0


def test_classify_truncation_degrades_to_unknown() -> None:
    resp = _response(_message(content="{part"), finish_reason="length")
    key, conf, _ = _provider(resp).classify_doc_type("x")
    assert key == "unknown" and conf == 0.0


def test_classify_in_enum_but_no_schema_passes_through_for_router_to_block() -> None:
    # "discharge" is a valid enum key but has no schema in v1; the classifier returns it and the
    # router (not the provider) raises UnknownDocTypeError. The provider must not pre-empt that.
    resp = _response(_message(content=_classify_json("discharge", 0.9)))
    key, conf, _ = _provider(resp).classify_doc_type("discharge summary")
    assert key == "discharge" and conf == 0.9
