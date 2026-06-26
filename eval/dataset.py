"""Gold-dataset schema + loader (spec §9, Appendix B).

A gold record is one synthetic clinical document plus its hand-reviewed label map — the ground
truth the scorer in :mod:`eval.run` measures against. The shape is one JSON file per document
under ``eval/gold/`` with the document text under ``eval/gold/docs/``::

    {
      "id": "path_01_idc_grade2",
      "doc_type": "pathology",
      "split": "tuning",
      "doc": "path_01_idc_grade2.txt",
      "labels": {
        "specimen": "Left breast core biopsy",
        "tumor_size_cm": "1.4 cm",
        "er_status": {"value": "ER positive", "span": "ER positive (90%)"},
        "margin_status": {"empty": "not_assessed", "cite": "Margins not assessed"},
        "lymph_nodes_positive": {"empty": "not_found"}
      }
    }

**Each label value is one of three things** (validated at load, so a typo is a load-time error, not
a silently-wrong metric):

* a **present value** — a scalar / list the model should extract. May be a bare value, or
  ``{"value": ..., "span": "<verbatim doc text>"}`` to pin the source span the oracle replays.
* ``{"empty": "not_found"}`` — the field is never mentioned; the correct answer is ``null``.
* ``{"empty": "not_assessed", "cite": "<verbatim doc text>"}`` — the document states the field was
  not determined; the correct answer is ``null`` **with that statement cited**.

The two **empty kinds** are the point of the set (§8): the scorer rewards the ``not_found`` /
``not_assessed`` distinction and never counts a correct empty as a hallucination.

``doc_type`` ``discharge`` is **routing-only**: v1 ships no ``DischargeSchema`` (Split 01), so a
discharge record carries no field labels — it exists solely so routing accuracy can score that the
classifier maps it to ``discharge`` (which the router then surfaces as ``unknown`` — the correct,
tested behaviour). The gold set is **frozen**: changing it is a versioned event, not a tweak.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from chartextract import SCHEMAS, field_names

#: doc_types that carry an extraction schema (and therefore field labels).
SCHEMA_DOC_TYPES: tuple[str, ...] = tuple(SCHEMAS)
#: All gold doc_types: the schema-backed ones plus routing-only ``discharge``.
GOLD_DOC_TYPES: tuple[str, ...] = (*SCHEMA_DOC_TYPES, "discharge")
#: The two empty kinds a label may declare (the §8 distinction).
EMPTY_KINDS: tuple[str, ...] = ("not_found", "not_assessed")
#: Split names, in leaderboard report order. ``held_out`` is the frozen wide-interval slice.
SPLITS: tuple[str, ...] = ("tuning", "held_out")

#: The default gold root (this module lives in eval/).
GOLD_DIR = Path(__file__).resolve().parent / "gold"


class GoldRecord(BaseModel):
    """One labeled gold document. Validated against the engine's schemas at load time."""

    model_config = ConfigDict(extra="forbid")

    id: str
    doc_type: str
    doc: str
    split: str = "tuning"
    labels: dict[str, Any] = {}

    @model_validator(mode="after")
    def _validate(self) -> GoldRecord:
        if self.doc_type not in GOLD_DOC_TYPES:
            raise ValueError(
                f"{self.id}: unknown doc_type {self.doc_type!r}; known {GOLD_DOC_TYPES}"
            )
        if self.split not in SPLITS:
            raise ValueError(f"{self.id}: unknown split {self.split!r}; known {SPLITS}")

        schema = SCHEMAS.get(self.doc_type)
        if schema is None:  # discharge — routing only, must not carry field labels
            if self.labels:
                raise ValueError(
                    f"{self.id}: doc_type {self.doc_type!r} has no extraction schema; it is "
                    "routing-only and must not carry field labels"
                )
            return self

        allowed = set(field_names(schema))
        unknown = set(self.labels) - allowed
        if unknown:
            raise ValueError(
                f"{self.id}: unknown label field(s) {sorted(unknown)}; allowed {allowed}"
            )
        for name, label in self.labels.items():
            _validate_label(self.id, name, label)
        return self

    # -- label accessors (small, so the scorer/oracle never re-parse raw dicts) --

    def is_empty(self, field: str) -> bool:
        label = self.labels.get(field)
        return isinstance(label, dict) and "empty" in label

    def empty_kind(self, field: str) -> str | None:
        """``"not_found"``/``"not_assessed"`` if ``field`` is labeled empty, else ``None``."""
        label = self.labels.get(field)
        if isinstance(label, dict) and "empty" in label:
            return str(label["empty"])
        return None

    def gold_value(self, field: str) -> Any:
        """The expected present scalar value; ``None`` for an empty/absent/list label."""
        label = self.labels.get(field)
        if not isinstance(label, (str, int, float)) and not (
            isinstance(label, dict) and "value" in label
        ):
            return None
        if isinstance(label, dict):  # {"value": ..., "span": ...}
            return label.get("value")
        return label

    def list_items(self, field: str) -> list[tuple[Any, str]]:
        """``(value, span)`` pairs for a present list label; ``[]`` for an empty/absent one."""
        label = self.labels.get(field)
        if not isinstance(label, list):
            return []
        out: list[tuple[Any, str]] = []
        for item in label:
            if isinstance(item, dict):
                out.append((item.get("value"), str(item.get("span") or "")))
            else:
                out.append((item, str(item)))
        return out

    def oracle_span(self, field: str) -> str:
        """The span the oracle replays for ``field`` (explicit ``span``/``cite``, else "")."""
        label = self.labels.get(field)
        if isinstance(label, dict):
            return str(label.get("span") or label.get("cite") or "")
        return ""


def _validate_label(rec_id: str, field: str, label: Any) -> None:
    """Structural validation of one label value (the three allowed shapes)."""
    if not isinstance(label, dict):
        if isinstance(label, (str, int, float, list)):
            return  # a bare present value
        raise ValueError(f"{rec_id}.{field}: unsupported label type {type(label).__name__}")
    if "empty" in label:
        if label["empty"] not in EMPTY_KINDS:
            raise ValueError(
                f"{rec_id}.{field}: empty kind {label['empty']!r} not in {EMPTY_KINDS}"
            )
        if label["empty"] == "not_assessed" and not label.get("cite"):
            raise ValueError(
                f"{rec_id}.{field}: a not_assessed label must carry the cited statement ('cite')"
            )
        extra = set(label) - {"empty", "cite"}
        if extra:
            raise ValueError(f"{rec_id}.{field}: unexpected empty-label key(s) {sorted(extra)}")
    elif "value" in label:
        extra = set(label) - {"value", "span"}
        if extra:
            raise ValueError(f"{rec_id}.{field}: unexpected value-label key(s) {sorted(extra)}")
    else:
        raise ValueError(f"{rec_id}.{field}: label dict must have 'value' or 'empty'")


def load_doc_text(record: GoldRecord, *, root: Path | str = GOLD_DIR) -> str:
    """Read ``record``'s text from ``root/docs/<doc>`` (UTF-8, ``\\n``-normalized)."""
    path = Path(root) / "docs" / record.doc
    if not path.is_file():
        raise FileNotFoundError(f"{record.id}: doc file not found: {path}")
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def load_gold(root: Path | str = GOLD_DIR) -> list[GoldRecord]:
    """Load every ``*.json`` gold record under ``root``, sorted by ``(split, id)``.

    Raises on a duplicate id (a copy-paste mistake that would double-count a document) or a record
    whose ``doc`` file is missing. The result is deterministically ordered for reproducible runs.
    """
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"gold root not found: {root}")

    records: list[GoldRecord] = []
    seen: dict[str, str] = {}
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        record = GoldRecord.model_validate(data)
        if record.id in seen:
            raise ValueError(
                f"duplicate gold id {record.id!r} (in {seen[record.id]} and {path.name})"
            )
        seen[record.id] = path.name
        if not (root / "docs" / record.doc).is_file():
            raise FileNotFoundError(f"{record.id}: doc file not found: docs/{record.doc}")
        records.append(record)

    if not records:
        raise ValueError(f"no gold records found under {root}")
    records.sort(key=lambda r: (SPLITS.index(r.split), r.id))
    return records
