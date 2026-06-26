"""Shared test fixtures for the ChartExtract engine.

The example documents live at the repo root (`examples/`), one level above `core/`. These
fixtures resolve that path so tests don't hardcode it, and expose the two canonical docs the UI
mockup also ships (so engine and UI render identical text).
"""

from __future__ import annotations

from pathlib import Path

import pytest

#: Repo-root examples directory (core/../examples).
EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES_DIR


@pytest.fixture
def path_report_path() -> Path:
    return EXAMPLES_DIR / "path_report.txt"


@pytest.fixture
def intake_form_path() -> Path:
    return EXAMPLES_DIR / "intake_form.txt"
