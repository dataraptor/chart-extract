"""Tier-1 tests for ``demo.py`` — the one-command money demo (Split 10).

All deterministic and key-free: the offline ``--stub`` path runs the real pipeline + eval on canned
data (no network), and the ``--live`` fallback is exercised with the key gate monkeypatched off so it
never touches a provider. The subprocess cases run the script exactly as a user would.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "demo.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``demo.py`` as a subprocess from the repo root, capturing text output."""
    return subprocess.run(
        [sys.executable, str(DEMO), *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def test_stub_demo_exits_zero_and_tells_the_story() -> None:
    proc = _run("--stub")
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    # The field table header.
    assert "field" in out and "match_quality" in out
    # Both honest nulls, each with its DISTINCT flag.
    assert "margin_status" in out and "not_assessed" in out
    assert "lymph_nodes_positive" in out and "not_found" in out
    # The cited absence shows its verbatim sentence.
    assert 'cited sentence: "Margins not assessed on this specimen"' in out
    # The headline: hallucination-rate zero.
    assert "HALLUCINATION-RATE  0.00" in out
    # Honesty furniture.
    assert "not real PHI" in out.replace("Not", "not")
    assert "Not a medical device" in out


def test_stub_demo_is_deterministic() -> None:
    first = _run("--stub")
    second = _run("--stub")
    assert first.returncode == 0 and second.returncode == 0
    assert first.stdout == second.stdout


def test_stub_demo_is_ascii_only() -> None:
    out = _run("--stub").stdout
    out.encode("ascii")  # raises UnicodeEncodeError if any non-ASCII glyph slipped in


def test_intake_sample_runs_and_shows_pcp_null() -> None:
    proc = _run("--stub", "--sample", "intake_form")
    assert proc.returncode == 0, proc.stderr
    assert "doc_type=intake" in proc.stdout
    assert "pcp" in proc.stdout and "not_found" in proc.stdout


def test_live_with_no_key_falls_back_cleanly(monkeypatch, capsys) -> None:
    """``--live`` with no key prints the fallback note, runs the stub, and exits 0 — no traceback."""
    import chartextract

    import demo

    # Force the key gate off regardless of any .env on disk, so no provider is constructed.
    monkeypatch.setattr(chartextract, "live_key_present", lambda: False)

    code = demo.main(["--live"])
    captured = capsys.readouterr()
    assert code == 0
    assert "falling back to the offline stub" in captured.err
    assert "OFFLINE STUB" in captured.out
    assert "HALLUCINATION-RATE  0.00" in captured.out


def test_stub_and_live_flags_are_mutually_exclusive() -> None:
    proc = _run("--stub", "--live")
    assert proc.returncode != 0  # argparse rejects the combination


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
