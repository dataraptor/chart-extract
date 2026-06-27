"""Split 01 — the canonical loader: offset invariant, normalization, no-text-layer flagging."""

from __future__ import annotations

from pathlib import Path

import pytest

from chartextract import LoadedDoc, from_text, load

# --- loading the shipped example --------------------------------------------


def test_load_path_report_example(path_report_path: Path) -> None:
    doc = load(path_report_path)
    assert isinstance(doc, LoadedDoc)
    assert doc.has_text_layer is True
    assert doc.n_chars == len(doc.text)
    assert doc.source_name == "path_report.txt"
    assert "Margins not assessed on this specimen." in doc.text
    assert "lymph" not in doc.text.lower()


def test_load_intake_example_has_no_pcp(intake_form_path: Path) -> None:
    doc = load(intake_form_path)
    assert doc.has_text_layer is True
    # The intake doc proves the list-schema not_found case: no PCP line.
    assert "PCP" not in doc.text and "primary care" not in doc.text.lower()


# --- inline-string dispatch + offset invariant ------------------------------


def test_inline_string_unchanged_after_normalization() -> None:
    body = "LINE ONE\nLINE TWO\nfield: value here"
    doc = load(body)
    assert doc.text == body  # byte-for-byte (already \n)
    assert doc.n_chars == len(body)
    assert doc.has_text_layer is True
    assert doc.source_name == "inline"


def test_string_path_to_existing_file_loads_from_disk(path_report_path: Path) -> None:
    # A str naming an existing file is loaded from disk, not treated as inline text.
    doc = load(str(path_report_path))
    assert doc.source_name == "path_report.txt"
    assert "SURGICAL PATHOLOGY REPORT" in doc.text


def test_inline_source_name_override() -> None:
    doc = load("a\nb", source_name="memo")
    assert doc.source_name == "memo"


def test_crlf_normalizes_to_lf() -> None:
    doc = load("a\r\nb\r\nc")
    assert doc.text == "a\nb\nc"
    assert doc.n_chars == len(doc.text) == 5


def test_lone_cr_normalizes_to_lf() -> None:
    doc = load("a\rb\rc")
    assert doc.text == "a\nb\nc"


def test_short_nonfile_string_is_treated_as_missing_path() -> None:
    # A short single-line string that isn't a file must NOT be silently read as a body.
    with pytest.raises(FileNotFoundError):
        load("nonexistent_report.txt")


def test_long_single_line_string_is_inline() -> None:
    body = "x" * 250  # no newline, but long → inline text
    doc = load(body)
    assert doc.text == body
    assert doc.has_text_layer is True


# --- from_text(): force inline, bypassing the path heuristic ----------------


def test_from_text_treats_short_single_line_as_body() -> None:
    # A short single-line string that load() would read as a (missing) path is unambiguously a
    # document body when the caller already knows it's inline.
    doc = from_text("chest pain")
    assert isinstance(doc, LoadedDoc)
    assert doc.text == "chest pain"
    assert doc.has_text_layer is True
    assert doc.source_name == "inline"
    assert doc.n_chars == len("chest pain")


def test_from_text_normalizes_newlines() -> None:
    doc = from_text("a\r\nb", source_name="memo")
    assert doc.text == "a\nb"
    assert doc.source_name == "memo"


def test_load_passes_through_a_loaded_doc() -> None:
    # load() is idempotent on a LoadedDoc, so a pre-loaded inline body can flow straight into
    # extract() without re-running the path heuristic.
    doc = from_text("chest pain")
    assert load(doc) is doc


# --- offset invariant + idempotence -----------------------------------------


def test_offset_invariant_substring_meaningful() -> None:
    body = "DIAGNOSIS:\nTumor size 1.4 cm. ER positive (90%)."
    doc = load(body)
    start = doc.text.index("1.4 cm")
    end = start + len("1.4 cm")
    assert doc.text[start:end] == "1.4 cm"
    assert doc.n_chars == len(doc.text)


def test_idempotence(path_report_path: Path) -> None:
    once = load(path_report_path).text
    twice = load(once).text
    assert twice == once


# --- no-text-layer PDF is flagged, never crashed ----------------------------


def test_empty_pdf_flagged_not_crashed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_path = tmp_path / "scanned.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy")  # exists so is_file() passes

    class _BlankPage:
        def extract_text(self) -> str:
            return "   \n  "

    class _FakeReader:
        def __init__(self, _path: str) -> None:
            self.pages = [_BlankPage(), _BlankPage()]

    import pypdf

    monkeypatch.setattr(pypdf, "PdfReader", _FakeReader)

    doc = load(pdf_path)
    assert doc.has_text_layer is False
    assert doc.n_chars == len(doc.text)  # invariant holds even when empty


def test_pdf_with_text_layer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy")

    class _Page:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _FakeReader:
        def __init__(self, _path: str) -> None:
            self.pages = [_Page("PAGE ONE"), _Page("PAGE TWO")]

    import pypdf

    monkeypatch.setattr(pypdf, "PdfReader", _FakeReader)

    doc = load(pdf_path)
    assert doc.has_text_layer is True
    assert doc.text == "PAGE ONE\nPAGE TWO"
    assert doc.source_name == "report.pdf"


def test_missing_pdf_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load(tmp_path / "does_not_exist.pdf")
