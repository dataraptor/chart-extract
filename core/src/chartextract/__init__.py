"""ChartExtract — a grounded, eval-proven clinical-document field-extraction engine.

Public surface grows split by split. Split 01 establishes the **data contract** (`Field`,
`ListField`, the extraction schemas, `GroundedField`, `ExtractionResult`) and the **canonical
loader** (`load`, `LoadedDoc`) — the single source of truth for character offsets. Split 02 adds
the **grounding + flag engine** (`ground`, `ground_fields`, `structural_confidence`,
`assign_flag`) — the pure-code heart where *the model proposes and code disposes*. No model and no
network are involved at this layer.

`extract()` — the end-to-end pipeline — is added in Split 03.
"""

from __future__ import annotations

from .confidence import (
    AMBIG_MAX_NONSPACE,
    MATCH_WEIGHT,
    TAU,
    assign_flag,
    nonspace_len,
    structural_confidence,
)
from .grounding import SpanMatch, ground, ground_fields
from .load import LoadedDoc, load
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
)

# extract() is added in Split 03 (load → route → parse → ground → assemble).

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
    "SCHEMAS",
    "SCHEMA_VERSION",
    "field_names",
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
]
