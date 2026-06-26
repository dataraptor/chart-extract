"""Provider backends behind one seam (:mod:`chartextract.provider.base`).

The Protocol and error types live in ``base``; :mod:`chartextract.provider.stub` is the
deterministic no-network backend that keeps the whole engine testable for free, and
:mod:`chartextract.provider.openai` is the live Azure-OpenAI GPT-5.5 backend (Split 04).
:func:`default_provider` is the one place that decides *live vs missing-key* from the environment.
"""

from __future__ import annotations

import os

from .base import (
    MissingAPIKeyError,
    ProviderClient,
    ProviderError,
    RefusalError,
    TruncatedError,
    Usage,
)

#: Env vars whose presence means a live key is configured (Azure first, then standard OpenAI).
_LIVE_KEY_VARS = ("AZURE_OPENAI_API_KEY", "OPENAI_API_KEY")


def live_key_present() -> bool:
    """True when a live-provider API key is configured in the environment."""
    return any(os.environ.get(v) for v in _LIVE_KEY_VARS)


def default_provider() -> ProviderClient:
    """Return the live :class:`~chartextract.provider.openai.OpenAIProvider`.

    Raises :class:`MissingAPIKeyError` (naming the env var) when no key is configured — the CLI/API
    turn that into a clean banner and may fall back to the stub for the bundled examples.
    """
    from .openai import OpenAIProvider

    return OpenAIProvider()


__all__ = [
    "ProviderClient",
    "ProviderError",
    "MissingAPIKeyError",
    "RefusalError",
    "TruncatedError",
    "Usage",
    "default_provider",
    "live_key_present",
]
