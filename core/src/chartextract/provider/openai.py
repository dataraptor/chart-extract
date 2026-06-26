"""Live ``OpenAIProvider`` for the provider seam — Azure OpenAI (or api.openai.com) GPT-5.5.

Conformance notes (the live LLM facts this module commits to — verified against the GPT-5.x
structured-outputs contract, 2026-06-27):

- **Model / deployment:** ``gpt-5.5``. On Azure this string doubles as the *deployment name*; the
  client is an :class:`openai.AzureOpenAI` keyed by ``AZURE_OPENAI_ENDPOINT`` +
  ``AZURE_OPENAI_API_KEY`` (api-version from ``OPENAI_API_VERSION``), else a standard
  :class:`openai.OpenAI` on ``OPENAI_API_KEY``.
- **Structured output:** strict ``response_format={"type":"json_schema","json_schema":{name,schema,
  strict:true}}`` over :func:`chartextract.schemas.strict_json_schema` — every key required,
  ``additionalProperties:false``, nullable fields are required-but-may-be-null. ``message.content``
  is parsed with ``schema_model.model_validate_json``. This is the OpenAI analogue of Anthropic's
  ``messages.parse(output_format=...)``; the rest of the engine is unchanged.
- **stop / finish handling is checked BEFORE reading content** (the §15/Appendix-A rule):
  a ``refusal`` (or ``finish_reason == "content_filter"``) raises :class:`RefusalError`; a
  ``finish_reason == "length"`` truncation raises :class:`TruncatedError` *after one bounded retry
  with doubled token headroom* (spans roughly double the output size, §15) — never an unbounded
  loop, never scoring a partial record.
- **No sampling params.** ``temperature`` / ``top_p`` / ``top_k`` / ``seed`` / ``budget_tokens``
  are never sent — GPT-5.x reasoning models reject non-default sampling, and determinism is
  best-effort regardless. The construction path is this class alone, so a param can't leak.
- **No citations feature** is enabled (grounding stays in code, Split 02).
- **Usage:** ``prompt_tokens`` → ``input_tokens``, ``completion_tokens`` → ``output_tokens``; the
  cache-read bucket is left ``0`` (OpenAI's ``prompt_tokens`` already includes any cached prefix and
  there is no separate read surcharge — honest, not faked).

**Deviation from the Split 04 brief (recorded in ``00-PROGRESS.md``):** the brief names an Anthropic
``AnthropicProvider``; the only credential available in this repo is an Azure **GPT-5.5** key (the
template ships an ``openai.py`` for exactly this), so the realized live provider is GPT-5.5. It
satisfies the same :class:`~chartextract.provider.base.ProviderClient` Protocol verbatim, so the
pipeline / router / CLI are untouched and the stub still covers Tier-1 CI.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from ..prompts import CLASSIFIER_SYSTEM, classifier_user_content
from ..schemas import strict_json_schema
from .base import (
    MissingAPIKeyError,
    ProviderClient,
    ProviderError,
    RefusalError,
    TruncatedError,
    Usage,
)

#: Pinned model id (verified 2026-06-27). On Azure this is also the deployment name.
DEFAULT_MODEL = "gpt-5.5"
OPENAI_MODELS = frozenset({"gpt-5.5"})

#: Default Azure API version if the environment does not pin one.
_DEFAULT_AZURE_API_VERSION = "2025-01-01-preview"

#: A classifier answer below this confidence is treated as ``unknown`` — the router then blocks and
#: the UI asks for a schema rather than the engine silently guessing a type (§6).
_CLASSIFY_MIN_CONFIDENCE = 0.5


class _DocTypeClassification(BaseModel):
    """Tiny structured-output target for the doc-type classifier (one cheap call → one enum)."""

    model_config = ConfigDict(extra="forbid")

    doc_type: Literal["pathology", "intake", "discharge", "unknown"]
    confidence: float


class OpenAIProvider:
    """``ProviderClient`` backed by the official ``openai`` SDK (OpenAI or Azure OpenAI).

    Pass ``client`` to inject a fake/mock — Tier-1 tests drive the no-key normalization paths this
    way. Otherwise the client is built from the environment (Azure when ``AZURE_OPENAI_ENDPOINT``
    is set, else standard OpenAI); a missing key raises :class:`MissingAPIKeyError` naming the env
    var (catchable, never a stack-trace crash).
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        api_key: str | None = None,
        max_completion_tokens: int = 8192,
        max_retries: int = 2,
        client: Any | None = None,
    ) -> None:
        if model not in OPENAI_MODELS:
            raise ValueError(
                f"unknown OpenAI model {model!r}; pin one of {sorted(OPENAI_MODELS)} "
                "(its pricing must also be pinned in cost.py)"
            )
        self.provider = "openai"
        self.model = model
        self._max_completion_tokens = max_completion_tokens
        self._max_retries = max_retries

        if client is not None:
            self._client = client
        else:
            self._client = _build_client(api_key)

    # -- the ProviderClient seam ----------------------------------------------

    def extract(
        self, system: str, document_text: str, schema_model: type[BaseModel]
    ) -> tuple[BaseModel, Usage]:
        """One structured-output extraction → (validated schema instance, accumulated usage).

        ``system`` is :data:`~chartextract.prompts.EXTRACTION_SYSTEM`; ``document_text`` is the
        already-built ``DOCUMENT:\\n<text>`` user turn. Refusals raise :class:`RefusalError`; a
        truncated response raises :class:`TruncatedError` only after one bounded retry with doubled
        headroom; a schema-invalid response is bounded-retried then surfaced as
        :class:`ProviderError`.
        """
        response_format = _strict_response_format(schema_model)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": document_text},
        ]

        parsed, usage, truncated = self._structured_call(
            messages, response_format, schema_model, self._max_completion_tokens
        )
        if truncated:
            # §15: spans roughly double the output size — one retry with doubled headroom, then
            # give up cleanly (never score a partial JSON record, never loop).
            parsed, usage2, truncated = self._structured_call(
                messages, response_format, schema_model, self._max_completion_tokens * 2
            )
            usage = usage + usage2
            if truncated:
                raise TruncatedError(
                    "response truncated (finish_reason=length) even after one retry with "
                    f"{self._max_completion_tokens * 2} max_completion_tokens; "
                    "the JSON is incomplete and was not scored"
                )
        assert parsed is not None  # a non-truncated call returns a parsed model or raises
        return parsed, usage

    def classify_doc_type(self, text: str) -> tuple[str, float, Usage]:
        """One cheap structured call → ``(key, confidence, usage)``.

        A refusal, truncation, parse failure, off-set answer, or low confidence all collapse to
        ``("unknown", conf, usage)`` so the router blocks and the UI asks — the classifier never
        silently guesses a schema.
        """
        response_format = _strict_response_format(_DocTypeClassification)
        messages = [
            {"role": "system", "content": CLASSIFIER_SYSTEM},
            {"role": "user", "content": classifier_user_content(text)},
        ]
        try:
            parsed, usage, truncated = self._structured_call(
                messages, response_format, _DocTypeClassification, self._max_completion_tokens
            )
        except ProviderError as exc:
            # Refusal / parse-exhaustion on the *classifier* must not crash a run: degrade to
            # unknown so the caller falls back to an explicit schema choice.
            return "unknown", 0.0, getattr(exc, "usage", Usage())
        if truncated or parsed is None:
            return "unknown", 0.0, usage
        assert isinstance(parsed, _DocTypeClassification)
        if parsed.confidence < _CLASSIFY_MIN_CONFIDENCE:
            return "unknown", parsed.confidence, usage
        return parsed.doc_type, parsed.confidence, usage

    # -- the one place the wire format is read --------------------------------

    def _structured_call(
        self,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any],
        schema_model: type[BaseModel],
        max_completion_tokens: int,
    ) -> tuple[BaseModel | None, Usage, bool]:
        """Run a strict structured-output call with a bounded parse-retry loop.

        Returns ``(parsed, usage, truncated)``: ``parsed`` is the validated model (``None`` only
        when ``truncated`` is ``True``); ``usage`` accumulates every attempt. Raises
        :class:`RefusalError` on a model refusal and :class:`ProviderError` when the response cannot
        be parsed after ``max_retries`` corrective retries. ``truncated`` signals a
        ``finish_reason == "length"`` cutoff — the caller decides whether to retry with more
        headroom (the §15 policy lives in :meth:`extract`, not here).
        """
        msgs = list(messages)
        total = Usage()
        last_error = "unknown error"
        for attempt in range(self._max_retries + 1):
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=msgs,
                response_format=response_format,
                max_completion_tokens=max_completion_tokens,
            )
            total = total + _usage(resp)
            choice = resp.choices[0]
            message = choice.message

            # Check stop/refusal BEFORE reading content (§15 / Appendix A).
            refusal = getattr(message, "refusal", None)
            if refusal or choice.finish_reason == "content_filter":
                exc = RefusalError(
                    f"model refused to answer (refusal): {refusal or 'content_filter'}"
                )
                exc.usage = total  # type: ignore[attr-defined]
                raise exc
            if choice.finish_reason == "length":
                return None, total, True

            content = getattr(message, "content", None)
            if content:
                try:
                    return schema_model.model_validate_json(content), total, False
                except ValidationError as exc:
                    last_error = f"schema validation failed: {exc.errors(include_url=False)}"
            else:
                last_error = f"empty content (finish_reason={choice.finish_reason!r})"

            if attempt < self._max_retries:
                # Feed the failure back and ask for a corrected, schema-valid JSON object.
                msgs = msgs + [
                    {"role": "assistant", "content": content or ""},
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response was not valid ({last_error}). "
                            "Return ONLY a JSON object matching the required schema."
                        ),
                    },
                ]
        exc = ProviderError(
            f"structured output failed after {self._max_retries + 1} attempt(s): {last_error}"
        )
        exc.usage = total  # type: ignore[attr-defined]
        raise exc


# Static check: the live provider satisfies the Protocol (caught at import, not only at runtime).
_PROTOCOL_CHECK: type[ProviderClient] = OpenAIProvider


# --- client construction (Azure or standard OpenAI) --------------------------


def _build_client(api_key: str | None) -> Any:
    """Build an Azure or standard OpenAI client from the environment.

    Azure is selected when ``AZURE_OPENAI_ENDPOINT`` is set (this repo's GPT-5.5 deployment);
    otherwise a standard ``OpenAI`` client. Imported locally so ``import chartextract`` stays light
    when no live provider is used.
    """
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if azure_endpoint:
        key = api_key or os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise MissingAPIKeyError(
                "AZURE_OPENAI_API_KEY is not set (AZURE_OPENAI_ENDPOINT is). Export it (or pass "
                "api_key=...) to use the Azure OpenAI provider."
            )
        from openai import AzureOpenAI

        return AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=key,
            api_version=os.environ.get("OPENAI_API_VERSION", _DEFAULT_AZURE_API_VERSION),
        )

    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise MissingAPIKeyError(
            "OPENAI_API_KEY is not set. Export it (or pass api_key=...) to use the OpenAI "
            "provider (or set AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY for Azure)."
        )
    from openai import OpenAI

    return OpenAI(api_key=key)


# --- normalization helpers ----------------------------------------------------


def _strict_response_format(schema_model: type[BaseModel]) -> dict[str, Any]:
    """Build the strict ``json_schema`` response_format for ``schema_model``."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_model.__name__,
            "schema": strict_json_schema(schema_model),
            "strict": True,
        },
    }


def _usage(resp: Any) -> Usage:
    """Map OpenAI usage onto the normalized buckets (cache-read stays 0 — see ``cost.py``)."""
    u = getattr(resp, "usage", None)
    if u is None:
        return Usage()
    return Usage(
        input_tokens=getattr(u, "prompt_tokens", 0) or 0,
        output_tokens=getattr(u, "completion_tokens", 0) or 0,
        cache_read_input_tokens=0,
    )
