"""``extract()`` — the end-to-end pipeline (spec §4/§5).

**This module owns the assembly:** ``load → route → parse → ground → assemble``. It wires the
canonical loader (Split 01), the router (this split), a :class:`ProviderClient` (the stub now, the
Anthropic backend in Split 04), and the grounding/flag engine (Split 02) into the one
:class:`ExtractionResult` every surface consumes — with derived counts, a priced ``cost_usd`` from
the provider's real :class:`Usage`, and the measured ``latency_s`` of the model call(s).

The pipeline is provider-agnostic: it depends only on the seam. Provider failures
(:class:`MissingAPIKeyError` / :class:`RefusalError` / :class:`TruncatedError`) propagate as typed
exceptions for the CLI/API to surface — ``extract`` never swallows them.
"""

from __future__ import annotations

import time
from pathlib import Path

from .cost import price
from .grounding import ground_fields
from .load import LoadedDoc, load
from .prompts import EXTRACTION_SYSTEM, PROMPT_VERSION, extraction_user_content
from .provider.base import ProviderClient
from .router import route
from .schemas import SCHEMA_VERSION, ExtractionResult, GroundedField

#: Flags that route a field to human review (spec §8). Both count toward ``n_needs_review``.
_REVIEW_FLAGS = frozenset({"needs_review", "ambiguous_span"})


def extract(
    doc: str | Path | LoadedDoc,
    *,
    schema: str | None = None,
    provider: ProviderClient,
    source_name: str | None = None,
) -> ExtractionResult:
    """Extract structured fields from ``doc`` into a grounded :class:`ExtractionResult`.

    Steps:

    1. **load** ``doc`` (a path, inline text, or a pre-built :class:`LoadedDoc`) into canonical
       text — the single offset source.
    2. **route** to a schema: ``schema`` override, else the provider's classifier. An unresolved
       type raises :class:`~chartextract.router.UnknownDocTypeError`.
    3. **extract** via the provider (timed) → a parsed schema instance + :class:`Usage`.
    4. **ground** every field against the canonical text → ``list[GroundedField]`` (offsets, §7
       match quality, §8 flag; values the model invented are nulled).
    5. **assemble** the result: derived counts, priced ``cost_usd``, measured ``latency_s``, and the
       prompt/schema/model provenance.

    When the document has no text layer (``has_text_layer is False``) the result's
    ``highlight_available`` is ``False`` and every field's offsets are ``None`` — honest, not faked.
    """
    loaded = load(doc, source_name=source_name)

    # routing_conf is recorded by the classifier path; the v1 result contract surfaces only the
    # chosen doc_type, so the confidence is intentionally not stored here.
    schema_model, doc_type, _routing_conf = route(loaded.text, schema, provider)

    start = time.perf_counter()
    parsed, usage = provider.extract(
        EXTRACTION_SYSTEM, extraction_user_content(loaded.text), schema_model
    )
    latency_s = time.perf_counter() - start

    fields: list[GroundedField] = ground_fields(parsed, loaded)

    # No text layer → offsets are meaningless; null them rather than fake a highlight (§4/§9).
    if not loaded.has_text_layer:
        for f in fields:
            f.char_start = None
            f.char_end = None

    n_grounded = sum(1 for f in fields if f.value is not None)
    n_null = sum(1 for f in fields if f.value is None)
    n_needs_review = sum(1 for f in fields if f.flag in _REVIEW_FLAGS)

    return ExtractionResult(
        doc_type=doc_type,
        fields=fields,
        n_fields=len(fields),
        n_grounded=n_grounded,
        n_null=n_null,
        n_needs_review=n_needs_review,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        model=provider.model,
        cost_usd=price(usage, provider.model),
        latency_s=latency_s,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens,
        highlight_available=loaded.has_text_layer,
    )
