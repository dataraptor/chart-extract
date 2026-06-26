"""``/api/samples`` — each ``text`` must be byte-identical to ``load(examples/<f>).text`` (E4).

This is the offset-source invariant: the UI's character highlights index into exactly this string,
so the API must serve the canonical loader output, never a hand-edited copy.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import chartextract
from chartextract import load

_EXAMPLES = Path(chartextract.__file__).resolve().parents[3] / "examples"


def test_samples_both_present_and_canonical(client: TestClient) -> None:
    resp = client.get("/api/samples")
    assert resp.status_code == 200
    items = resp.json()
    by_id = {s["id"]: s for s in items}
    assert set(by_id) == {"path_report", "intake_form"}

    assert by_id["path_report"]["doc_type_hint"] == "pathology"
    assert by_id["intake_form"]["doc_type_hint"] == "intake"

    # The offset-source invariant: text == load(examples/<f>).text, byte for byte.
    assert by_id["path_report"]["text"] == load(_EXAMPLES / "path_report.txt").text
    assert by_id["intake_form"]["text"] == load(_EXAMPLES / "intake_form.txt").text
    # And the canonical lengths the worked example pins (Split 01/02 carry-forward).
    assert len(by_id["path_report"]["text"]) == 413
    assert len(by_id["intake_form"]["text"]) == 386
