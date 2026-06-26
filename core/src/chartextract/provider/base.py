"""The provider seam — one interface, one normalized output shape (spec §4/§6).

**This module owns the swap-point.** Everything downstream — :mod:`chartextract.router`,
:mod:`chartextract.pipeline`, the CLI, and later the API and eval harness — depends only on the
:class:`ProviderClient` Protocol, so changing ``--provider`` swaps one constructor and nothing
else. The concrete backends (:mod:`chartextract.provider.stub` now, ``anthropic`` in Split 04)
normalize their wire format into the types defined here.

Provider-layer failures are **typed and surfaced, never crashes** (the spec's recurring rule):
a missing key, a model refusal, and a truncated response are each a distinct exception the caller
can turn into a clean message or error envelope.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from ..cost import Usage  # re-exported: the canonical, cost-aware token-bucket model.

__all__ = [
    "Usage",
    "ProviderClient",
    "ProviderError",
    "MissingAPIKeyError",
    "RefusalError",
    "TruncatedError",
]


class ProviderError(RuntimeError):
    """Base class for catchable provider-layer failures (surfaced, never a bare crash)."""


class MissingAPIKeyError(ProviderError):
    """Raised when a live provider is constructed/used without an API key (§4)."""


class RefusalError(ProviderError):
    """Raised when the model declines to answer (``stop_reason == "refusal"``, §6).

    The pipeline lets this propagate; the CLI/API turn it into a clean message, never an
    ``IndexError`` from blindly indexing ``content[0]``.
    """


class TruncatedError(ProviderError):
    """Raised when the response was cut off (``stop_reason == "max_tokens"``, §6)."""


@runtime_checkable
class ProviderClient(Protocol):
    """The one interface every backend satisfies. Carries ``provider`` + ``model`` for cost keying.

    ``extract`` returns a parsed schema instance **plus** normalized :class:`Usage` so the caller
    can price it; ``classify_doc_type`` returns ``(key, confidence, usage)`` for the cheap
    doc-type call. The model never returns offsets — those are computed in code (§7).
    """

    provider: str
    model: str

    def extract(
        self, system: str, document_text: str, schema_model: type[BaseModel]
    ) -> tuple[BaseModel, Usage]:
        """Run one structured-output extraction; return the parsed instance + token usage.

        The concrete backend checks ``stop_reason`` first and raises :class:`RefusalError` /
        :class:`TruncatedError` as appropriate — it never returns an off-schema record.
        """
        ...

    def classify_doc_type(self, text: str) -> tuple[str, float, Usage]:
        """Classify the document type; return ``(key, confidence, usage)``.

        ``key`` is one of ``pathology | intake | discharge | unknown``; the router maps it (or a
        non-schema key) to a schema or surfaces :class:`~chartextract.router.UnknownDocTypeError`.
        """
        ...
