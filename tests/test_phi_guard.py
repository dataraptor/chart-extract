"""The PHI-guard tripwire: bundled docs must stay synthetic (spec §2 / §16).

Asserts the high-signal real-identifier scan (`scripts/check_phi.py`) is clean on every bundled
document, and that the scanner actually fires on a planted positive (so a clean result means
"checked", not "no-op").
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "check_phi.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("check_phi", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundled_docs_have_no_obvious_phi() -> None:
    guard = _load_guard()
    findings = guard.scan_docs()
    assert findings == [], f"PHI guard tripped on bundled docs: {findings}"


def test_guard_actually_detects_phi() -> None:
    # The scanner must catch a planted SSN/email/phone, so a clean run is meaningful.
    guard = _load_guard()
    planted = "Contact jane@example.com, SSN 123-45-6789, ph 555-123-4567"
    hits = [label for label, pat in guard._PATTERNS if re.search(pat, planted)]
    assert {"us_ssn", "email", "us_phone"} <= set(hits)


def test_main_exits_zero_clean(capsys) -> None:
    guard = _load_guard()
    assert guard.main() == 0
    assert "clean" in capsys.readouterr().out.lower()
