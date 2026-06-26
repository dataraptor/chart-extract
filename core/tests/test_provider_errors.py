"""Split 03 — the provider error taxonomy is typed and surfaced, never a bare crash (§4/§6)."""

from __future__ import annotations

from chartextract import (
    MissingAPIKeyError,
    ProviderError,
    RefusalError,
    TruncatedError,
)


def test_all_provider_errors_subclass_provider_error():
    # One catchable base so a caller can `except ProviderError` for the whole family.
    for err in (MissingAPIKeyError, RefusalError, TruncatedError):
        assert issubclass(err, ProviderError)
    assert issubclass(ProviderError, RuntimeError)


def test_errors_carry_a_message():
    for err in (MissingAPIKeyError, RefusalError, TruncatedError):
        assert str(err("boom")) == "boom"


def test_distinct_types_so_callers_can_branch():
    # missing-key (exit 3) vs refusal/truncation (exit 2) must be distinguishable.
    assert MissingAPIKeyError is not RefusalError is not TruncatedError
    # A refusal is NOT a missing-key, but IS catchable as the common ProviderError base.
    refusal = RefusalError("model refused")
    assert not isinstance(refusal, MissingAPIKeyError)
    assert isinstance(refusal, ProviderError)
