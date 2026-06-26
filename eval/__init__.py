"""ChartExtract eval harness (Split 05) — the headline artifact.

Imports the installed ``chartextract`` engine directly (no server, no network on the default
path) and drives the full ``load -> route -> extract -> ground -> assemble`` pipeline over a
**frozen gold set** of synthetic clinical documents, then scores the result **per field**:
precision / recall / F1, macro-F1, **hallucination-rate** (the number to drive to zero), and
routing accuracy — reported **distributionally** (mean +/- spread over N repeats).

Two registers, kept honest (§9):

- **Default (stub, no key, deterministic):** each gold doc is replayed through a per-doc *oracle*
  :class:`chartextract.StubProvider` built from its gold labels, so the real grounding/flag code
  runs and the leaderboard is byte-reproducible — this is the screenshot ("macro-F1 0.94,
  0 hallucinated values across the frozen set").
- **Live (``--provider``, opt-in):** the same gold docs run against the live GPT-5.5 provider for
  the real quality numbers; auto-skipped without a key.

The harness depends only on ``core`` — it never re-implements the engine. See :mod:`eval.run`.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
