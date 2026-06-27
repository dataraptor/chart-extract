# Changelog

All notable changes to ChartExtract are recorded here. This project adheres to
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-06-27

The first complete, shippable release: a grounded clinical-document field-extraction engine, a thin
HTTP API, the live web UI, an eval harness, and the production hardening that makes it trustworthy
to run.

### Engine (`core` / `chartextract`)

- **Grounded extraction.** The model returns only `{value, source_span, confidence}`; every char
  offset, match-quality, and flag is computed in **code** (never by the model), so a field is
  emitted only when its source span is located in the canonical text.
- **Flag taxonomy.** `accepted`, `needs_review`, `ambiguous_span`, `not_assessed`, `not_found`,
  `not_grounded`. A value that can't be grounded is **nulled and flagged, never invented**; the
  rejected proposal is retained on `model_value`.
- **Canonical loader.** One offset source (`load()`); text-layer PDF or `.txt`; a missing text layer
  is flagged honestly (highlight disabled, never faked).
- **Provider seam.** A deterministic offline `StubProvider` (Tier-1, no key) and a live
  **Azure OpenAI GPT-5.5** provider behind the same protocol; `stop_reason` is checked before
  content (refusal and truncation surface as typed errors, never an index-error crash).
- **Cost, caching, and batch.** Per-model pricing, token-bucket usage, automatic cache accounting,
  and a 50%-cheaper Batch API path (opt-in).

### API (`api` / `chartextract-api`)

- Thin FastAPI adapter: `/health`, `/api/samples`, `/api/extract` (JSON or multipart), `/api/eval`.
- A single structured **error envelope** for every failure, so no stack trace ever leaves the
  server.
- Serves the `app/` UI same-origin (no CORS in production).

### UI (`app`)

- The DC web UI wired to the live API: offsets, flags, and confidence are consumed verbatim from the
  engine; honest edge states (no-text-layer, refusal, truncation, ambiguous, unknown-routing,
  upload, ListField, offline). Full Playwright e2e, axe a11y, and responsive coverage.

### Eval (`eval` / `chartextract-eval`)

- 17 synthetic gold docs, type-aware normalizers, a pure scorer, and a deterministic leaderboard:
  **hallucination-rate 0** across the frozen set (macro-F1 1.00 on the stub oracle).

### Hardening

- Input validation on `/api/extract`: upload size cap (5 MB), inline-text cap, content-type
  allowlist (text-layer PDF or `.txt` only, OCR is a non-goal), binary-as-text rejection, and a
  `sample_id` allowlist (no path traversal). Every bad input returns an envelope, not a crash.
- Dev-only hooks (`?simulate`, dev CORS) are **inert in production** unless an explicit dev env flag
  is set.
- PHI tripwire (`scripts/check_phi.py`) over all bundled docs; synthetic and public docs only.
- Packaging: sdist + wheel per package, complete metadata, console entry points (`chartextract`,
  `chartextract-api`).
- CI: keyless lint + Tier-1 tests + ≥85% coverage gate + PHI guard + package build + Playwright
  e2e; a separate secret-gated workflow for the live `@api` tests (never gates merge).

### Security

- No secret in the repo or image. Keys come only from env; `.env` is git-ignored; Docker passes the
  key at runtime, never baked. Dependency closure audited clean.
