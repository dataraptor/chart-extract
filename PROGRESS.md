# ChartExtract — E2E Test & Evaluation Progress Log

This file tracks an ongoing end-to-end test/evaluation effort across multiple
sessions. The goal: find and fix bugs, edge cases, dead UI, integrity gaps, and
spec-misalignment until the system is production-ready.

**Interpreter on this box:** `C:\ProgramData\miniconda3\python.exe` (Python 3.13).
Packages are installed editable into the user site (`%APPDATA%\Python\Python313\site-packages`).
`python`/`py` are NOT on PATH (only the Windows Store stub) — always invoke the full path.
**Node.js is NOT installed** on this box, so the JS unit tests (`app/tests/*.test.js`)
and the Playwright e2e/a11y/responsive suites cannot be executed here — frontend
changes are verified by reading + grep against the test specs instead. Installing
Node would let a future session actually run `cd app && npm run test:unit` / `npm run e2e`.

**How to run the Python suites** (each package is scoped via `cd`; the `tmp/template-repo`
dir is an unrelated vendored repo that breaks root-level collection — never run
`pytest` from the repo root without a path):

```
cd core && python -m pytest -q -m "not api"     # 160 tests
cd api  && python -m pytest -q -m "not api"     #  60 tests (was 58; +2 temp-leak tests)
cd eval && python -m pytest -q -m "not api"     #  68 tests
python -m pytest tests -q -m "not api"          #  28 tests (root orchestration)
```

Lint: `cd <pkg> && python -m ruff check . && python -m ruff format --check .`
PHI guard: `python scripts/check_phi.py`. Demo: `python demo.py --stub`.

---

## Session log

### Session 1 — 2026-06-27 (baseline + full audit + first fix pass)

**Baseline:** All Tier-1 suites green — core 160, api 58, eval 68, root 28 = **314 passing**.
`@pytest.mark.api` (live-key) tests correctly auto-deselect with no key. Demo (`demo.py --stub`)
runs clean: 7 grounded / 2 honest nulls / hallucination-rate 0. PHI guard clean. Ruff clean.

**Method:** Read every core module directly; dispatched 4 parallel deep-audit agents
(API, eval, frontend, core-providers/CLI/batch). Ran the stub demo end-to-end.

#### Fixes applied this session (all verified: Python suites + ruff green)

1. **[HIGH] Frontend eval leaderboard showed fabricated numbers contradicting `/api/eval`.**
   The HTML hardcoded the cost rows (`Opus $0.021`, `Sonnet $0.011 ↓48%`), `N=5 runs`, and the
   honesty caption — while `/api/eval` actually returns `$0.0105 / $0.0063 / ↓40%`, `N=1`, and a
   precise caption. `map.js toEvalView` even computed a `cost[]` array (with measured-vs-estimate
   `basis`) that the markup never bound → dead code + dishonest UI, defeating the "measured cost"
   pitch. **Fix:** `map.js` now also surfaces `nRuns`, `caption`, a friendly cost-row `label`, and a
   pre-rendered `deltaText`; the HTML binds the cost rows via `<sc-for list="{{ evalCost }}">` and
   binds `N={{ evalRuns }}` + `{{ evalCaption }}`. The offline scripted-fallback `ev` carries
   matching values so offline appearance is unchanged. Files: `app/map.js`, `app/ChartExtract.dc.html`.
   (e2e `money-demo.spec` only asserts halluc/macro-f1/routing/eval-row — none touched.)

2. **[HIGH] API upload leaked a temp file on every request (disk-fill DoS).**
   `routes._parse_multipart` wrote each upload to `NamedTemporaryFile(delete=False)` and never
   unlinked it — success or failure. **Fix:** `post_extract` unlinks the temp `Path` in a `finally`
   (uploads are the only case `doc_source` is a `Path`). Added 2 regression tests
   (`test_successful_upload_leaves_no_temp_file`, `test_failed_upload_leaves_no_temp_file`) that
   redirect `tempfile.tempdir` to an empty dir and assert nothing leaks. File: `api/.../routes.py`,
   `api/tests/test_upload.py`. (api suite 58 → 60.)

3. **[MEDIUM] Misroute "change schema?" nudge always re-ran intake.**
   `goIntake` hardcoded `chooseSchema('intake')`, so on an already-intake view it pointed the wrong
   way. **Fix:** now picks the *other* schema (`S.sample==='intake' ? 'pathology' : 'intake'`);
   button title generalized. File: `app/ChartExtract.dc.html`.

4. **[HIGH] Classifier system prompt contradicted its own structured-output contract.**
   `CLASSIFIER_SYSTEM` told the model to "output only the single key — no punctuation", but the live
   provider forces a strict `{doc_type, confidence}` JSON schema and the router *thresholds on that
   confidence*. The model was never told the `confidence` field existed → degraded routing signal.
   **Fix:** rewrote the prompt to describe the JSON object + the confidence field and the
   block-on-uncertainty contract. Only the 4 enum keys are pinned by tests; PROMPT_VERSION left at
   v3 (extraction prompt — what the version tracks — is unchanged). File: `core/.../prompts.py`.

#### Verified-good (audited, no action needed)

- Core grounding/confidence/flag procedure (`grounding.py`, `confidence.py`) — byte-for-byte port of
  the JS reference; null-discipline, ambiguity, not_assessed-vs-not_found all correct.
- Loader offset invariants (`load.py`), router never-guess contract (`router.py`), pipeline assembly
  (`pipeline.py`), cost arithmetic + unknown-model KeyError (`cost.py`), schema strict-mode shaping.
- Provider seam: refusal/truncation ordering, cache-token split (no double-count), provider
  selection (Azure-first key detection), CLI exit codes (2/3, no traceback), batch collation
  re-keying by custom_id. (Per core-audit agent — all confirmed correct.)
- Eval metric machinery: hallucination = non-null pred vs null gold (per-item for lists), correct
  empties = TN, not_assessed rewarded; deterministic stub; batch re-key by custom_id; gold-set
  span-verbatim integrity; no real-PHI. (Per eval-audit agent — headline metrics correct.)
- API security: path-traversal allowlist for samples, traceback-free error envelopes, binary/.txt
  rejection, dev hooks inert without env flags. (Per api-audit agent.)

---

## Open issues / carry-forward (prioritized for next sessions)

> None of these are regressions; they are gaps surfaced by the audit. Pick up here.

**Frontend (UI integrity / dead controls):**
- **[MED] "Show caught hallucination" toggle is reachable in LIVE mode** and silently replaces the
  real extraction with scripted JS data (`showCaught` → `scriptedGrounded()`), with no "illustration"
  indication. Options: gate to offline/stub only, or add an explicit "scripted illustration" badge.
  (`ChartExtract.dc.html` ~115-117, 783; grounded()/text()/docBody fall back when showCaught.)
- **[MED] No visible focus ring on the command-bar buttons** (setPath/setIntake, Extraction/Eval,
  JSON, caught, rerun, Upload) — UIUX spec §9 requires a 2px focus ring on every interactive
  element. Only field rows / ListField toggles have `style-focus`. (Verify against
  `app/tests/a11y/keyboard.spec.ts` once Node is available — don't change blind.)
- **[LOW] Upload control is a dead no-op in offline/stub mode** (`onUpload` early-returns when
  `mode!=='live'`) yet always renders active. Disable/dim it offline, or show a notice.
- **[LOW] "routed auto 0.92" is a hardcoded routing confidence** masquerading as live
  (`ChartExtract.dc.html:109`). The result contract doesn't surface routing_conf — would need
  `ExtractionResult` to carry it (pipeline already computes `_routing_conf` and discards it).
- **[MED/spec] Sample picker is a 2-way Pathology/Intake toggle**, not the spec's "Sample ▾ dropdown".
  `api.js samples()` fetches the sample list but only `text` for the 2 fixed ids is consumed
  (`name`/`doc_type_hint` unused; a 3rd sample would be invisible). Decide: dropdown vs intentional cut.

**Eval harness:**
- **[MED] `held_out` split is promised but never reported.** 5 gold docs are `split:"held_out"`,
  `SPLITS`/`gold/README.md` advertise a "frozen wide-interval slice", but `aggregate()`/
  `render_leaderboard()` pool both splits. Either add a per-split breakdown or drop the claim +
  unused plumbing. (Feature-shaped — confirm intent before building.)
- **[MED] Routing accuracy denominator is `--repeats`-inflated** and an errored row (pred=None)
  silently lowers it even when routing wasn't the failure. Dedupe to one row per id; exclude
  pre-classification errors. (`eval/run.py` ~583-584.)
- **[MED] `empty_kind_accuracy` never populated for list fields** — `_score_list` doesn't set
  `empty_kind_correct`, so list-typed empties are excluded from the not_found-vs-not_assessed metric
  the spec markets. (`eval/run.py` ~175-191.)

**Core / API (robustness, not user-visible now):**
- **[MED] Batch path lacks the refusal/truncation/parse-retry safety net** the sync path guarantees
  (`batch.py run_openai_batch` reads `choices[0].message.content` + `model_validate_json` directly;
  a refused/truncated line raises raw `KeyError`/`ValidationError` and aborts the whole batch).
- **[LOW] CLI loads the document twice** (`cli._cmd_extract` calls `load()` then `extract()` re-loads)
  — pass the `LoadedDoc` through (idempotent). PDF text-extraction runs twice.
- **[LOW] cache_read tokens billed at full input rate** — documented as a conservative upper bound,
  but for GPT-5.5 (real cached-input discount) it ~2× over-prices cache hits on the sweep. Consider
  a per-model `cache_read` multiplier. Stub has cache_read=0 so offline cost is unaffected.
- **[LOW] Oversized streamed multipart** is buffered (to a SpooledTemporaryFile, so memory IS bounded)
  before the post-read 5 MB cap rejects it. Could pass `request.form(max_part_size=...)` (verify the
  installed Starlette accepts the kwarg first).
- **[NIT] Docstring drift Anthropic→OpenAI**: `provider/base.py`, `pipeline.py` still describe
  `stop_reason=="max_tokens"/"refusal"` (Anthropic) though the realized backend is OpenAI
  (`finish_reason`/`message.refusal`). Cosmetic.
- **[NIT] simulate unknown-type raises 400 not 422** (`simulate.py`) — inconsistent with the rest of
  the adapter's 422 bad_request convention. Dev-only path.
- **[NIT] `/api/eval` `type:"internal"` with 503** when eval extra missing — conflates with the 500
  bucket; use a distinct type. (`deps.py`.)

## Areas already audited (don't re-audit unless code changed)

- core: grounding, confidence, load, router, pipeline, schemas, cost, prompts, provider/{base,stub,
  openai}, cli, batch — **all read this session.**
- api: app, routes, errors, schemas, deps, simulate, cli — **audited (agent + direct read of routes).**
- eval: run, dataset, normalize, gold set — **audited (agent).**
- app: ChartExtract.dc.html, map.js, api.js — **audited (agent + direct read).** support.js NOT yet
  read in depth. e2e/a11y specs read by name only (can't run — no Node).
