"""Document-type routing — pick the extraction schema (spec §6).

**This module owns one rule: never silently guess the schema.** An explicit ``override`` (the demo
dropdown / CLI ``--schema``) wins and skips the classifier entirely; otherwise the provider's cheap
classifier proposes a type. Either path raises :class:`UnknownDocTypeError` when the type is not a
known schema — an ``"unknown"`` classification, a roadmap-only type (``"discharge"`` has no schema
in v1), or a bad ``--schema`` value — so the caller (UI/CLI) asks the human to pick rather than
defaulting to pathology. No model logic here beyond delegating the one classify call to the
provider seam.
"""

from __future__ import annotations

from pydantic import BaseModel

from .provider.base import ProviderClient
from .schemas import SCHEMAS


class UnknownDocTypeError(RuntimeError):
    """The document type could not be resolved to a known schema — the caller must pick (§6).

    Carries ``key`` (the offending type, or ``None`` when the classifier returned ``"unknown"``)
    so the UI/CLI can phrase a helpful "pass --schema" message.
    """

    def __init__(self, key: str | None) -> None:
        self.key = key
        known = ", ".join(sorted(SCHEMAS))
        if key is None or key == "unknown":
            msg = f"could not classify the document type - pass an explicit schema ({known})"
        else:
            msg = f"no schema for document type {key!r} - pass an explicit schema ({known})"
        super().__init__(msg)


def route(
    text: str, override: str | None, provider: ProviderClient
) -> tuple[type[BaseModel], str, float]:
    """Resolve ``(schema_model, doc_type_key, routing_confidence)``.

    * ``override`` set → use it (routing confidence ``1.0``); the classifier is **not** called. A
      bad override raises :class:`UnknownDocTypeError`, not a raw ``KeyError``.
    * otherwise → ask ``provider.classify_doc_type``; an ``"unknown"`` or non-schema key raises
      :class:`UnknownDocTypeError`. Never defaults to a schema.
    """
    if override is not None:
        if override not in SCHEMAS:
            raise UnknownDocTypeError(override)
        return SCHEMAS[override], override, 1.0

    key, conf = provider.classify_doc_type(text)[:2]
    if key not in SCHEMAS:  # "unknown", or an in-enum-but-no-schema type like "discharge"
        raise UnknownDocTypeError(key)
    return SCHEMAS[key], key, conf
