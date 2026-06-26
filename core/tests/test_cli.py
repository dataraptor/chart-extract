"""Split 03 — the CLI (`chartextract extract <doc>`), offline via the stub."""

from __future__ import annotations

import json

import pytest

from chartextract import __version__
from chartextract.cli import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:  # argparse --version exits 0
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_extract_path_report_prints_two_distinct_nulls(
    capsys: pytest.CaptureFixture[str], path_report_path
) -> None:
    rc = main(["extract", str(path_report_path)])
    assert rc == 0
    out = capsys.readouterr().out
    # the two distinct null flags both appear
    assert "not_assessed" in out
    assert "not_found" in out
    # footer caption present
    assert "grounded" in out and "needs-review" in out


def test_extract_json_is_valid(capsys: pytest.CaptureFixture[str], path_report_path) -> None:
    rc = main(["extract", str(path_report_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["doc_type"] == "pathology"
    assert payload["n_fields"] == 9
    assert payload["prompt_version"] == "v3"


def test_extract_intake_with_schema(capsys: pytest.CaptureFixture[str], intake_form_path) -> None:
    rc = main(["extract", str(intake_form_path), "--schema", "intake"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "medications[0]" in out
    assert "pcp" in out


def test_unknown_route_exits_nonzero_with_hint(
    capsys: pytest.CaptureFixture[str], tmp_path
) -> None:
    # A doc whose header matches no known type → offline guess "unknown" → exit non-zero.
    doc = tmp_path / "mystery.txt"
    doc.write_text("RANDOM MEMO\nnothing classifiable here at all\n", encoding="utf-8")
    rc = main(["extract", str(doc)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "schema" in err.lower()


def test_bad_schema_override_exits_nonzero(
    capsys: pytest.CaptureFixture[str], path_report_path
) -> None:
    rc = main(["extract", str(path_report_path), "--schema", "discharge"])
    assert rc == 2
    assert "schema" in capsys.readouterr().err.lower()
