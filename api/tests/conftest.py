"""Shared test setup for the API layer.

Two jobs: (1) load a repo-root ``.env`` so the ``@api`` (live) tests can find a key — the Tier-1
(no-key) tests never need it; (2) provide a ``client`` fixture wired to a fresh app with **no live
key in the environment**, so the whole Tier-1 suite runs deterministically on the stub. Keys are
never printed or committed (``.env`` is gitignored). Mirrors ``core/tests/conftest.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_LIVE_KEY_VARS = ("AZURE_OPENAI_API_KEY", "OPENAI_API_KEY")


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_here = Path(__file__).resolve()
for candidate in (_here.parents[1] / ".env", _here.parents[2] / ".env"):
    _load_env_file(candidate)


def live_key_present() -> bool:
    return any(os.environ.get(v) for v in _LIVE_KEY_VARS)


@pytest.fixture
def stub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the stub path: clear every live-key env var for this test (no network)."""
    for var in (*_LIVE_KEY_VARS, "AZURE_OPENAI_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def client(stub_env: None) -> TestClient:
    """A ``TestClient`` over a fresh app with no live key → the offline stub provider."""
    from chartextract_api.app import create_app

    return TestClient(create_app())
