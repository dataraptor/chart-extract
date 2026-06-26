"""Regenerate the `app/tests/fixtures/` JSON for the `map.test.js` suite (Split 07).

These are the *real* Split 06 stub responses — the byte-for-byte shapes the live API returns — so
the JS mapper is tested against the actual contract, never a hand-written approximation. Run from
the repo root with the project's interpreter (see 00-PROGRESS.md Split 01 tooling note):

    python app/tests/_gen_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "api" / "src"))

from chartextract import extract, load, stub_for_intake, stub_for_path_report  # noqa: E402
from chartextract_api import deps  # noqa: E402

FX = Path(__file__).resolve().parent / "fixtures"


def _write(name: str, obj: object) -> None:
    (FX / name).write_text(json.dumps(obj, indent=2), encoding="utf-8")
    print(f"wrote {name}")


def main() -> None:
    FX.mkdir(parents=True, exist_ok=True)

    path_text = load(_REPO_ROOT / "examples" / "path_report.txt").text
    intake_text = load(_REPO_ROOT / "examples" / "intake_form.txt").text

    _write(
        "extract_path.json",
        extract(
            path_text,
            schema="pathology",
            provider=stub_for_path_report(),
            source_name="path_report",
        ).model_dump(),
    )
    _write(
        "extract_path_caught.json",
        extract(
            path_text,
            schema="pathology",
            provider=stub_for_path_report(caught=True),
            source_name="path_report",
        ).model_dump(),
    )
    _write(
        "extract_intake.json",
        extract(
            intake_text,
            schema="intake",
            provider=stub_for_intake(),
            source_name="intake_form",
        ).model_dump(),
    )
    _write(
        "samples.json",
        [
            {
                "id": "path_report",
                "name": "path_report.txt",
                "doc_type_hint": "pathology",
                "text": path_text,
            },
            {
                "id": "intake_form",
                "name": "intake_form.txt",
                "doc_type_hint": "intake",
                "text": intake_text,
            },
        ],
    )
    _write("eval.json", deps.build_eval_summary().model_dump())


if __name__ == "__main__":
    main()
