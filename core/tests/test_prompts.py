"""Split 03 — prompts behind a version (prompts.py)."""

from __future__ import annotations

from chartextract import PROMPT_VERSION
from chartextract.prompts import (
    CLASSIFIER_SYSTEM,
    EXTRACTION_SYSTEM,
    classifier_user_content,
    extraction_user_content,
)


def test_prompt_version_pinned():
    assert PROMPT_VERSION == "v3"


def test_user_content_puts_doc_in_user_turn_not_system():
    # The document is the cacheable user prefix; never interpolated into the system prompt (§10).
    assert extraction_user_content("HELLO") == "DOCUMENT:\nHELLO"
    assert classifier_user_content("HELLO") == "DOCUMENT:\nHELLO"
    assert "HELLO" not in EXTRACTION_SYSTEM


def test_extraction_system_states_the_null_discipline():
    assert "value = null" in EXTRACTION_SYSTEM
    assert "not assessed" in EXTRACTION_SYSTEM


def test_classifier_system_lists_the_enum_keys():
    for key in ("pathology", "intake", "discharge", "unknown"):
        assert key in CLASSIFIER_SYSTEM
