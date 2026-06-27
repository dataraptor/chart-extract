"""ChartExtract — a grounded, eval-proven clinical-document field-extraction engine.

Public surface grows split by split. Split 01 establishes the **data contract** (`Field`,
`ListField`, the extraction schemas, `GroundedField`, `ExtractionResult`) and the **canonical
loader** (`load`, `LoadedDoc`) — the single source of truth for character offsets. Split 02 adds
the **grounding + flag engine** (`ground`, `ground_fields`, `structural_confidence`,
`assign_flag`) — the pure-code heart where *the model proposes and code disposes*. No model and no
network are involved at this layer.

Split 03 wires it all into the end-to-end **pipeline** (`extract`) over a **provider seam**
(`ProviderClient` + the no-network `StubProvider`) with **routing** (`route`), **prompts**
(`PROMPT_VERSION`), and **cost** (`Usage`, `price`) — runnable entirely offline.

Split 04 adds the **live** backend (`OpenAIProvider` — Azure OpenAI GPT-5.5) selected by
`default_provider()` when a key is configured; the same `extract()` now runs live or on the stub.

Split 11 makes the cost story real: prompt-prefix caching is surfaced (`cache_read_tokens` on
`ExtractionResult`, priced via `price`), the eval sweep can run through the **Batch API** (50%
cheaper, `BatchRequest` + `collate_results`, keyed by `custom_id`), and pricing is reconciled
against the `claude-api` reference (`PRICING`, `MIN_CACHEABLE_PREFIX_TOKENS`).
"""

from __future__ import annotations

from .batch import (
    BatchRequest,
    MissingBatchResultError,
    collate_results,
    run_openai_batch,
)
from .confidence import (
    AMBIG_MAX_NONSPACE,
    MATCH_WEIGHT,
    TAU,
    assign_flag,
    nonspace_len,
    structural_confidence,
)
from .cost import (
    BATCH_DISCOUNT,
    MIN_CACHEABLE_PREFIX_TOKENS,
    PRICING,
    Usage,
    price,
    price_batch,
)
from .grounding import SpanMatch, ground, ground_fields
from .load import LoadedDoc, from_text, load
from .pipeline import extract
from .prompts import PROMPT_VERSION
from .provider import default_provider, live_key_present
from .provider.base import (
    MissingAPIKeyError,
    ProviderClient,
    ProviderError,
    RefusalError,
    TruncatedError,
)
from .provider.stub import StubProvider, stub_for_intake, stub_for_path_report
from .router import UnknownDocTypeError, route
from .schemas import (
    SCHEMA_VERSION,
    SCHEMAS,
    ExtractionResult,
    Field,
    GroundedField,
    IntakeSchema,
    ListField,
    PathologySchema,
    field_names,
    strict_json_schema,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Field",
    "ListField",
    "PathologySchema",
    "IntakeSchema",
    "GroundedField",
    "ExtractionResult",
    "LoadedDoc",
    "load",
    "from_text",
    "SCHEMAS",
    "SCHEMA_VERSION",
    "field_names",
    "strict_json_schema",
    # Split 02 — grounding + flag engine.
    "SpanMatch",
    "ground",
    "ground_fields",
    "structural_confidence",
    "assign_flag",
    "nonspace_len",
    "TAU",
    "MATCH_WEIGHT",
    "AMBIG_MAX_NONSPACE",
    # Split 03 — pipeline, provider seam, routing, prompts, cost.
    "extract",
    "route",
    "UnknownDocTypeError",
    "PROMPT_VERSION",
    "Usage",
    "price",
    "price_batch",
    "PRICING",
    "BATCH_DISCOUNT",
    "MIN_CACHEABLE_PREFIX_TOKENS",
    "ProviderClient",
    "ProviderError",
    "MissingAPIKeyError",
    "RefusalError",
    "TruncatedError",
    "StubProvider",
    "stub_for_path_report",
    "stub_for_intake",
    # Split 04 — live provider (Azure OpenAI GPT-5.5).
    "default_provider",
    "live_key_present",
    # Split 11 — batch API (50% cheaper, unordered → key by custom_id).
    "BatchRequest",
    "collate_results",
    "MissingBatchResultError",
    "run_openai_batch",
]
