"""Canonical-text loader — the single source of truth for character offsets.

**This module owns one invariant:** the ``text`` returned by :func:`load` is the *exact* string
that both the model sees and the highlighter indexes into. It is normalized **once, here** (line
endings → ``\\n``) and never mutated afterward, so any ``char_start``/``char_end`` a later split
computes (Split 02) indexes this string verbatim. ``len(text) == n_chars`` always.

No model and no network are involved — this is pure text handling.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

#: A bare string with no newline and shorter than this is treated as a (file) path, not inline
#: text — so a mistyped path fails loudly instead of being silently loaded as a document body.
_INLINE_MIN_LEN = 200


class LoadedDoc(BaseModel):
    """A document reduced to its canonical text plus provenance.

    ``has_text_layer=False`` means no usable text could be extracted (e.g. a scanned PDF). The
    vision fallback and the no-text-layer banner are Split 04/09; this split only flags the
    absence honestly — it never raises for it.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    source_name: str
    has_text_layer: bool
    n_chars: int


def _normalize_newlines(text: str) -> str:
    """Normalize CRLF and lone CR to ``\\n`` — the ONLY normalization applied to canonical text.

    Done once so offsets are stable cross-platform. Order matters: collapse ``\\r\\n`` first, then
    any remaining lone ``\\r``.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _load_pdf(path: Path) -> tuple[str, bool]:
    """Extract a PDF's text layer (pages joined by ``\\n``).

    Returns ``(text, has_text_layer)``. Whitespace-only extraction → ``has_text_layer=False`` with
    a best-effort (possibly empty) text. Never raises for an absent text layer.
    """
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = _normalize_newlines("\n".join(pages))
    return text, bool(text.strip())


def _looks_like_inline_text(value: str) -> bool:
    """True if a raw string should be treated as a document body rather than a path.

    A string that is not an existing file is inline text when it contains a newline or is long;
    a short single-line non-file string is assumed to be a (mistyped) path and is *not* silently
    treated as text.
    """
    return "\n" in value or "\r" in value or len(value) >= _INLINE_MIN_LEN


def from_text(text: str, *, source_name: str = "inline") -> LoadedDoc:
    """Wrap a string as inline canonical text, **bypassing the path heuristic** in :func:`load`.

    Callers that already know their input is a document body — e.g. the HTTP adapter's inline
    ``text`` field, where a short single-line note like ``"chest pain"`` is unambiguously content,
    not a mistyped path — use this so :func:`load`'s file-vs-inline guess never misfires. The only
    normalization is the canonical newline pass; ``len(text) == n_chars`` still holds.
    """
    normalized = _normalize_newlines(text)
    return LoadedDoc(
        text=normalized,
        source_name=source_name,
        has_text_layer=True,
        n_chars=len(normalized),
    )


def load(path_or_text: str | Path | LoadedDoc, *, source_name: str | None = None) -> LoadedDoc:
    """Load a document into a :class:`LoadedDoc` with canonical text and offset invariants.

    Dispatch (explicit, never ambiguous):

    * an already-loaded :class:`LoadedDoc` → returned unchanged (idempotent pass-through, so a
      caller that pre-loaded inline text via :func:`from_text` can hand it straight to
      :func:`~chartextract.extract`);
    * a :class:`~pathlib.Path`, or a ``str`` naming an existing file → loaded from disk;
    * a ``.pdf`` file → text layer extracted via ``pypdf`` (``has_text_layer=False`` if empty);
    * any other file → read as UTF-8 text;
    * a ``str`` that is not an existing file → treated as **inline text** iff it contains a
      newline or is long (see :data:`_INLINE_MIN_LEN`); otherwise it is assumed to be a missing
      path and raises ``FileNotFoundError`` (a real path is never silently read as a body).

    Line endings are normalized to ``\\n`` exactly once; the returned ``text`` is never mutated
    afterward, so ``len(text) == n_chars`` and ``text[a:b]`` is meaningful for any later offsets.
    """
    if isinstance(path_or_text, LoadedDoc):
        return path_or_text
    if isinstance(path_or_text, Path):
        return _load_path(path_or_text, source_name)

    candidate = Path(path_or_text)
    # `Path.is_file` can raise on a string that's too long to be a valid OS path — that string is
    # unambiguously inline text, so treat the error as "not a file".
    try:
        is_file = candidate.is_file()
    except (OSError, ValueError):
        is_file = False

    if is_file:
        return _load_path(candidate, source_name)

    if _looks_like_inline_text(path_or_text):
        text = _normalize_newlines(path_or_text)
        return LoadedDoc(
            text=text,
            source_name=source_name or "inline",
            has_text_layer=True,
            n_chars=len(text),
        )

    raise FileNotFoundError(
        f"{path_or_text!r} is neither an existing file nor recognizable inline text "
        "(a short single-line string is treated as a path). "
        "Pass inline text containing a newline, or a valid file path."
    )


def _load_path(path: Path, source_name: str | None) -> LoadedDoc:
    """Load from a filesystem path (PDF text-layer or UTF-8 text)."""
    if not path.is_file():
        raise FileNotFoundError(f"no such file: {path}")

    name = source_name or path.name
    if path.suffix.lower() == ".pdf":
        text, has_text_layer = _load_pdf(path)
    else:
        text = _normalize_newlines(path.read_text(encoding="utf-8"))
        has_text_layer = True

    return LoadedDoc(
        text=text,
        source_name=name,
        has_text_layer=has_text_layer,
        n_chars=len(text),
    )
