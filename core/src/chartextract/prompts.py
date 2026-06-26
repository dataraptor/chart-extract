"""Canonical prompts behind a ``PROMPT_VERSION`` (spec §6, §10).

**This module owns the model-facing instructions.** The system prompts are reproduced **verbatim**
from §6 and are the *stable* cacheable prefix (§10) — the document text goes in the user turn
(``DOCUMENT:\\n<text>``), never in the system prompt, so the cache prefix never changes per
document. ``PROMPT_VERSION`` is recorded on every result so an extraction is attributable to a
prompt revision; bump it on any prompt change.
"""

from __future__ import annotations

#: Recorded on every ExtractionResult and eval run. Bump on any prompt change.
PROMPT_VERSION = "v3"

#: The §6 extraction system prompt, verbatim (the rules block is load-bearing — it is what makes
#: the model emit a unique, verbatim span and a null+empty-span when the document is silent).
EXTRACTION_SYSTEM = """\
You extract structured fields from a clinical document into a fixed schema.

Rules:
- For each field, return the value AND a source_span: the exact, verbatim text
  from the DOCUMENT that establishes the value (copy it character-for-character).
- Make the source_span long enough to be UNIQUE in the document — include the
  field's label or surrounding context (e.g. "ER positive (90%)", not "positive").
- If the document does not mention a field at all, return value = null and an empty
  source_span. NEVER guess, infer, or fill a plausible value. A missing value is
  the correct answer when the document is silent.
- If the document explicitly states the value was NOT determined ("not assessed",
  "pending", "N/A", "deferred"), return value = null but set source_span to that
  exact statement — the absence is itself something the document establishes.
- Do not summarize or paraphrase the evidence in source_span — copy it exactly so
  it can be located in the original text.
- confidence: 0.0–1.0, how certain you are the value is correct AND grounded.
- Extract only what the DOCUMENT says — never outside/world knowledge."""

#: The doc-type classifier system prompt (one cheap Haiku call → one enum key).
CLASSIFIER_SYSTEM = """\
You classify a clinical document into exactly one type. Reply with one lowercase key only:
- pathology  : a surgical/anatomic pathology or biopsy report
- intake     : a patient intake/registration form (demographics, meds, allergies)
- discharge  : a hospital discharge summary
- unknown    : none of the above, or you are not confident

Output only the single key — no punctuation, no explanation."""


def extraction_user_content(text: str) -> str:
    """Build the extraction user turn: ``DOCUMENT:\\n<text>`` — the cacheable prefix (§10)."""
    return f"DOCUMENT:\n{text}"


def classifier_user_content(text: str) -> str:
    """Build the classifier user turn: ``DOCUMENT:\\n<text>``."""
    return f"DOCUMENT:\n{text}"
