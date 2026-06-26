"""Gold loader + validator tests — a label typo must be a load-time error, not a silent metric."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from eval.dataset import GoldRecord, load_doc_text, load_gold


def _rec(**over):
    base = dict(id="x", doc_type="pathology", doc="x.txt", labels={"grade": "2"})
    base.update(over)
    return GoldRecord.model_validate(base)


def test_valid_record_accessors():
    r = _rec(
        labels={
            "grade": "2",
            "er_status": {"value": "ER+", "span": "ER positive"},
            "margin_status": {"empty": "not_assessed", "cite": "not assessed"},
            "lymph_nodes_positive": {"empty": "not_found"},
        }
    )
    assert r.gold_value("grade") == "2"
    assert r.gold_value("er_status") == "ER+"
    assert r.is_empty("margin_status") and r.empty_kind("margin_status") == "not_assessed"
    assert r.empty_kind("grade") is None
    assert r.oracle_span("er_status") == "ER positive"
    assert r.oracle_span("margin_status") == "not assessed"
    assert r.list_items("grade") == []  # not a list label


def test_intake_list_accessors():
    r = GoldRecord.model_validate(
        {
            "id": "i",
            "doc_type": "intake",
            "doc": "i.txt",
            "labels": {"medications": ["a", {"value": "b", "span": "b span"}]},
        }
    )
    assert r.list_items("medications") == [("a", "a"), ("b", "b span")]
    assert (
        r.gold_value("medications") is None
    )  # list labels are read via list_items, not gold_value


@pytest.mark.parametrize(
    "over",
    [
        dict(doc_type="mystery"),  # unknown doc_type
        dict(split="prod"),  # unknown split
        dict(labels={"not_a_field": "x"}),  # stray label key
        dict(labels={"grade": {"empty": "maybe"}}),  # bad empty kind
        dict(labels={"grade": {"empty": "not_assessed"}}),  # not_assessed without cite
        dict(labels={"grade": {"value": "2", "bogus": 1}}),  # stray value-label key
        dict(labels={"grade": {"nothing": 1}}),  # neither value nor empty
        dict(doc_type="discharge", labels={"grade": "2"}),  # discharge must carry no labels
    ],
)
def test_invalid_records_rejected(over):
    with pytest.raises((ValidationError, ValueError)):
        _rec(**over)


def test_load_gold_missing_root(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_gold(tmp_path / "nope")


def test_load_gold_empty_root(tmp_path):
    with pytest.raises(ValueError, match="no gold records"):
        load_gold(tmp_path)


def test_load_gold_missing_doc_file(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "rec.json").write_text(
        json.dumps({"id": "rec", "doc_type": "pathology", "doc": "missing.txt", "labels": {}}),
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError):
        load_gold(tmp_path)


def test_load_gold_duplicate_id(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "d.txt").write_text("hello", encoding="utf-8")
    for name in ("a.json", "b.json"):
        (tmp_path / name).write_text(
            json.dumps({"id": "dup", "doc_type": "discharge", "doc": "d.txt"}), encoding="utf-8"
        )
    with pytest.raises(ValueError, match="duplicate gold id"):
        load_gold(tmp_path)


def test_load_doc_text_missing(tmp_path):
    rec = GoldRecord(id="x", doc_type="discharge", doc="ghost.txt")
    with pytest.raises(FileNotFoundError):
        load_doc_text(rec, root=tmp_path)
