"""Split 01 — the CLI is a usage stub that resolves and exits 0 (real impl in Split 03)."""

from __future__ import annotations

import pytest

from chartextract import __version__
from chartextract.cli import main


def test_main_prints_usage_exit_0(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "usage:" in out
    assert "Split 03" in out


def test_main_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert __version__ in capsys.readouterr().out
