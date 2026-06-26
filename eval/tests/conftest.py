"""Shared fixtures for the eval tests.

Puts the repo root on ``sys.path`` (so ``import eval.run`` resolves whether pytest is invoked from
the repo root or from ``eval/``) and exposes the loaded gold set.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.dataset import GOLD_DIR, load_gold  # noqa: E402 — after the sys.path fix


@pytest.fixture(scope="session")
def gold_records():
    return load_gold(GOLD_DIR)
