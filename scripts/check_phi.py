#!/usr/bin/env python
"""PHI guard — fail if any bundled document carries an obvious real-identifier pattern (§2/§16).

ChartExtract ships **synthetic/public documents only**. This guard is a cheap tripwire against real
PHI sneaking into the bundled corpus (examples + the eval gold set). It looks for *high-signal*
identifier formats that a synthetic doc has no reason to contain — US SSNs, email addresses, and
US phone numbers. It deliberately does **not** flag the synthetic record numbers (MRNs) the mockup
docs use by design, nor synthetic patient names; those are intentional clinical *flavor*.

Run standalone (CI):  ``python scripts/check_phi.py``  → exit 0 clean, exit 1 with a report.
Used by ``tests/test_phi_guard.py`` as well.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: Directories whose ``*.txt`` documents must stay synthetic.
_DOC_DIRS = (
    _REPO_ROOT / "examples",
    _REPO_ROOT / "eval" / "gold" / "docs",
)

#: (label, compiled pattern) — obvious real-PHI formats. Kept tight to avoid false positives on
#: the synthetic docs (no bare-number/MRN rule, which would trip the intentional mockup data).
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("us_ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("us_phone", re.compile(r"\(\d{3}\)\s?\d{3}-\d{4}|\b\d{3}-\d{3}-\d{4}\b")),
)


def scan_docs() -> list[str]:
    """Return a list of human-readable findings (empty == clean)."""
    findings: list[str] = []
    for directory in _DOC_DIRS:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.txt")):
            text = path.read_text(encoding="utf-8")
            for label, pattern in _PATTERNS:
                for match in pattern.finditer(text):
                    rel = path.relative_to(_REPO_ROOT)
                    findings.append(f"{rel}: {label} -> {match.group(0)!r}")
    return findings


def main() -> int:
    findings = scan_docs()
    if findings:
        print("PHI GUARD FAILED — obvious real-identifier patterns in bundled docs:")
        for f in findings:
            print(f"  {f}")
        return 1
    print("PHI guard clean: no real-identifier patterns in bundled synthetic docs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
