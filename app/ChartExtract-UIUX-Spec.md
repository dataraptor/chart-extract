# ChartExtract — UI/UX Design Specification

> Source of truth for the high-fidelity demo mockups. Target medium: a single-page, web-native demo (the aspirational version of the spec's Streamlit `app.py`). Audience: technical buyers and hiring managers evaluating a $100/hr AI-architect portfolio. Authored from `11-chartextract.md` (v2, LOCKED 2026-06-26).

---

## Step 0 — Grounding in the repo (restated before any design)

- **What it does / who it's for.** ChartExtract turns one messy clinical document (pathology report, intake form, discharge summary) into **strict, schema-validated JSON where every field carries the verbatim source span it came from**. It refuses to invent: a value it can't ground is returned `null` and flagged, never guessed. It ships with a field-level eval harness scoring precision/recall/F1 + hallucination-rate against a frozen gold set. Personas: **Ops/clinical analyst** (primary — uploads docs, reads structured output); **Engineer/buyer** (meta-user — wants proof the fields are real and the tool knows what it doesn't know, lives in the eval report + span view); **demo audience** (wants one unforgettable visual).

- **THE MONEY DEMO (design everything around this).** Upload a synthetic pathology report → the filled schema appears → **hover a field and its exact source span lights up in the rendered document.** One field the document doesn't contain returns **`null`, flagged `not_found`** — not hallucinated. A second empty field returns **`null`, flagged `not_assessed`, citing the document's own "Margins not assessed" sentence.** Then the **eval leaderboard**: field-level P/R/F1 on the frozen gold set with **0 hallucinated values.** The pitch is the combination — *cited, honest about gaps (and which kind of gap), and measured.*

- **Real data objects the UI must render (actual field names — not invented).**
  - `GroundedField`: `name`, `value` (typed | null), `source_span` (verbatim), `char_start`/`char_end` (int | null, computed in code), `match_quality` (`exact`|`whitespace`|`prefix`|`none`), `confidence` (STRUCTURAL, not the raw model number), `flag` (`None`|`not_found`|`not_assessed`|`not_grounded`|`needs_review`|`ambiguous_span`).
  - `ExtractionResult`: `doc_type`, `fields[]`, `n_fields`, `n_grounded`, `n_null`, `n_needs_review`, `prompt_version`, `schema_version`, `model`, `cost_usd`, `latency_s`.
  - `PathologySchema` fields (the headline doc): `specimen`, `diagnosis`, `grade`, `tumor_size_cm` (float), `er_status`/`her2_status` (enum positive|negative|unknown), `margin_status`, `lymph_nodes_positive` (int). Intake/discharge schemas add **`ListField`** collections (`medications`, `allergies`, `problem_list`) where **each item carries its own span** — flattened in the UI as `name[i]`.
  - Eval: per-field **precision / recall / F1**, **macro-F1**, **hallucination-rate** (predicted-non-null where gold is null), **routing accuracy**, reported distributionally (mean ± spread over N runs); Opus 4.8 headline row + Sonnet 4.6 cost row.

- **The actual flow, with the states the spec calls out.** Pick a sample / upload (text-layer PDF or text) → **doc-type routing** (Haiku classifier auto-sets a dropdown the human can override; on classifier low-confidence it returns `unknown` and the UI *asks*, never silently guesses) → **extract** (Opus 4.8, structured output, streaming) → **ground in code** (locate each span → offsets + `match_quality`; the model never returns offsets) → **assemble result**. States the spec demands: streaming/loading; populated; the three empties (`not_found` / `not_assessed` / `not_grounded`); `needs_review` and `ambiguous_span` (kept but uncertain); **no-text-layer doc → highlight disabled with an explicit banner** (vision fallback, offsets unavailable); `refusal` stop_reason and `max_tokens` truncation surfaced, not crashed; doc-type misroute (most fields `not_found`) as a visible, correctable signal.

- **Spec-vs-design conflicts flagged.** (1) The schema in §6 omits `pr_status`, but the §5 worked example and prose reference "PR positive (40%)". **Decision: render `pr_status` as a `Field[str]` enum mirroring `er_status`** — the worked example is the canonical demo content; noted so engineering can reconcile. (2) Spec UI is two-pane Streamlit; the brief asks for the aspirational web-native version — **I keep the document-left / schema-right spine (it is the right IA for hover-to-highlight) and elevate everything else.** (3) Spec lists the demo as "one screen"; I treat the eval leaderboard as a **peer panel within that one screen** (a switchable third region), not a second page — the money demo needs extraction *and* leaderboard legible in one continuous scroll/view.

---

## 1. Design thesis

**ChartExtract should feel like a forensic instrument, not a chatbot.** The single idea the UI is built around: **every claim is wired back to its evidence, and every gap is named.** The interface is a two-sided ledger — the *document* on one side, the *extracted record* on the other — joined by a single physical gesture (hover a field, the source lights up in the text). Trust is not asserted in copy; it is demonstrated by the literal, animated line of sight between a value and the sentence that proves it. Where evidence is missing, the UI says *which kind of missing* in a calm, color-coded, clinical register. The feeling: a senior engineer's tool — quiet, precise, fast, and constitutionally unwilling to overstate what it knows.

---

## 2. Design principles (specific to ChartExtract)

1. **Evidence is the interface.** No value renders without a visible path to its source. Hovering, focusing, or selecting a field always reveals its span (or explicitly states why there is none). The highlight is the product; everything else is chrome around it.
2. **Name the gap, don't hide it.** Empty is not one state — it is three (`not_found` silent, `not_assessed` cited, `not_grounded` caught). The UI gives each its own color, icon, and one-line explanation. Collapsing them would throw away the most credible part of the story, so the design refuses to.
3. **Honest about cost and certainty, always on screen.** `$/run`, latency, model name, prompt/schema version, and a persistent "demo on synthetic data — not a medical device / not a real service" disclaimer are part of the standing furniture, not buried in a footer modal.
4. **The machine proposes, code disposes — and the UI shows the seam.** Structural confidence (not the model's self-reported number) drives accept vs review. The interface visibly distinguishes "the model said" from "the system verified," because that seam *is* the engineering value being sold.
5. **80/20 by design.** The screen's job is to auto-accept the 80% it's sure of and hand the human exactly the 20% that needs eyes — with the span already pulled up and the *reason* named. Review-worthy fields are visually surfaced, never lost in a flat list.
6. **Fluid, content-driven calm.** Layout breathes as fields stream in; motion is continuous and physical (spans slide into view, panels resize fluidly), never decorative. Density scales with viewport via `clamp()`, not hard breakpoints — the tool feels native at any width.

---

## 3. Visual language / design tokens (described, not coded)

### Color system

Cool-neutral, near-monochrome base so the **semantic flag palette is the only saturated color on screen** — color *means* something here, it is never decoration.

**Neutrals (dark-first; this is a developer tool)**
- `bg` (app background): `#0B0E14` — near-black, faint blue cast.
- `surface` (panels/cards): `#11151D`.
- `surface-raised` (popovers, the schema rows on hover): `#171C26`.
- `border` (hairlines): `#222936`; `border-strong` (focused field): `#33405A`.
- `text-primary`: `#E6EAF2`; `text-secondary`: `#9AA4B6`; `text-muted`: `#5E6675`.
- **Light mode** (offer as a toggle — buyers screenshot in both): `bg #F7F8FA`, `surface #FFFFFF`, `border #E4E7EC`, `text-primary #11151D`, `text-secondary #4B5566`. All semantic colors below are tuned to hold **WCAG AA (≥4.5:1)** on both `surface` values; the dark-mode hexes below are the canonical set, with light-mode equivalents one step darker in lightness.

**Primary / brand accent** (interactive, non-semantic — buttons, active tab, focus ring)
- `primary`: `#5B8DEF` (a precise, un-flashy blue — distinct in hue from the semantic blue used for `not_assessed`, see note). `primary-hover`: `#6F9CF2`. Focus ring: `primary` at 60% + 2px offset.
- ⚠ **Hue separation:** brand blue and `not_assessed` blue must read differently. **Decision: brand = blue-violet `#5B8DEF`; `not_assessed` = cyan-teal `#3BA7C2`.** Different enough at a glance; both AA.

**Semantic flag palette (the heart of the product — exact hexes, mapped to §8 taxonomy)**
| Flag | Role | Dark hex | Meaning the color must convey |
|---|---|---|---|
| `None` (accepted) | **verdict-green** | `#3FB67E` | grounded, high structural confidence — trust it |
| `needs_review` | **amber** | `#E2A33C` | grounded but uncertain — eyes needed |
| `ambiguous_span` | **amber (hatched)** | `#E2A33C` + diagonal hatch | grounded, span matched >1 place |
| `not_assessed` | **cyan-teal** | `#3BA7C2` | document *states* it wasn't determined — cited absence |
| `not_found` | **neutral-grey** | `#6B7484` | document is silent — honest blank |
| `not_grounded` | **red** | `#E5615E` | model proposed, code couldn't locate it → forced null (a caught error) |

- **Highlight wash** (the span lit in the document): the field's own flag color at **18% alpha fill + 100% left-edge bar (3px)**. Accepted fields wash green; a `not_assessed` field washes cyan over the cited "not assessed" sentence; `not_found` has nothing to wash (handled in §6).
- **Cost-saving green vs verdict-green:** the leaderboard's "0 hallucinated" and the Sonnet cost-delta both want green. **Decision: reuse `#3FB67E` for both** (it reads as "good outcome" consistently); the cost number is differentiated by a `↓` glyph and `$` unit, not a second green.
- **Confidence ramp** (the structural-confidence meter): a 0→1 ramp from `#6B7484` (low) → `#E2A33C` (mid, ~τ=0.6) → `#3FB67E` (high), with the **τ threshold marked** as a tick so "below the line = review" is literal.

### Typography

- **Font intent.** Two families, no more. **UI / prose:** a neutral, engineered grotesque — *Inter Tight* or *Söhne*; pick one with true tabular figures (counts, $, latency, offsets must align). **Document body + all spans/offsets/JSON:** a monospace — *Berkeley Mono* / *JetBrains Mono* — because the rendered clinical source and the verbatim spans should read as *evidence/code*, reinforcing "this is the literal text, character-for-character." The mono in the source pane is the single strongest signal that spans are exact.
- **Fluid type scale** (`clamp(min, preferred-vw, max)`, ~1.2 ratio):
  - Display (leaderboard headline F1): `clamp(28px, 2.4vw, 40px)`, tabular, weight 600.
  - H1 / region title: `clamp(18px, 1.4vw, 24px)`, weight 600.
  - H2 / field group label: `clamp(13px, 1vw, 15px)`, weight 600, letter-spacing +2%, uppercase, `text-secondary`.
  - Body / field value: `clamp(14px, 1vw, 16px)`.
  - Mono source / span / JSON: `clamp(13px, 0.95vw, 15px)`, line-height 1.7 (room for highlight washes).
  - Caption / cost / version / disclaimer: `clamp(11px, 0.8vw, 12.5px)`, `text-muted`.

### Spacing, radius, elevation, border

- **Fluid spacing scale** (a single `--space` unit `clamp(6px, 0.6vw, 9px)`; steps are multiples): `xs .5×`, `sm 1×`, `md 2×`, `lg 3×`, `xl 5×`, `2xl 8×`. Gutters between the two panes use `lg→xl` and grow with viewport so the layout *breathes*.
- **Radius:** `4px` controls/chips, `8px` panels/cards, `12px` modals/popovers. Spans highlighted in text get `2px` (tight, code-like).
- **Elevation:** flat by default (borders do the separating). Only two raised levels: popovers/tooltips (`0 4px 16px rgba(0,0,0,.45)` dark) and the field row on hover (a `1px border-strong` + `surface-raised` fill, *no* shadow — keeps it crisp).
- **Border system:** hairline `1px border` everywhere; state is shown by **left-edge accent bars** (3px, flag-colored) on field rows rather than full outlines — this is the connective tissue to the highlight wash, which uses the same left bar in the document.

### Motion language

Continuous, physical, purposeful — every animation explains a state change.
- **Durations:** micro (hover, focus) `120ms`; standard (panel resize, field stream-in) `220ms`; emphasis (the highlight scroll-and-glow, leaderboard count-up) `420ms`. Stagger streamed fields by `40ms` each.
- **Easing:** `cubic-bezier(.22,.61,.36,1)` (ease-out-quint feel) for entrances/resizes; `cubic-bezier(.4,0,.2,1)` for hovers. No bounce — this is a clinical instrument.
- **What animates and why:**
  - *Hover-to-highlight (the money gesture):* on field hover, the document pane smoothly scrolls the span into view (if off-screen) and the wash fades+expands from the span's left edge over `420ms`; a faint connector pulse runs field→span. Reverse on hover-out.
  - *Streaming extraction:* field rows fade-up and the right panel grows fluidly as each `GroundedField` arrives — the layout literally breathes as content lands.
  - *Confidence meter:* fills from 0 to its value over `420ms` so the eye catches where it lands relative to τ.
  - *Flag transitions:* if a value flips to `not_grounded` mid-stream (code rejected it), the row crossfades from a tentative grey to red with a 1px shake-free settle — honest, not alarmist.
  - *Leaderboard:* numbers count up; the hallucination-rate "0" lands last with a brief green ring — the climax of the measured-honesty story.
- **Reduced motion:** `prefers-reduced-motion` → all of the above become instant opacity swaps; the highlight still appears (just no scroll-glide or glow), the count-up shows final numbers immediately.

---

## 4. Information architecture

One screen, three regions on a persistent **command bar**. The extraction workspace and the eval leaderboard are **peer views toggled in the same canvas** (not separate pages) so the demo flows extraction → proof in one continuous motion.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  COMMAND BAR  ChartExtract · [Sample ▾ | Upload]  [Schema: pathology ▾]    │
│               [● Extraction]  [○ Eval Leaderboard]      ⓘ demo·synthetic   │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│   ┌── DOCUMENT PANE (left) ──────┐   ┌── EXTRACTION PANEL (right) ──────┐  │
│   │  rendered source, mono,       │   │  filled schema, field rows,     │  │
│   │  spans wash on hover          │◄─►│  flag bars, confidence meters   │  │
│   │                               │   │                                 │  │
│   └───────────────────────────────┘   └─────────────────────────────────┘  │
│                                                                            │
├──────────────────────────────────────────────────────────────────────────┤
│  RESULT FOOTER  n_grounded 6 · null 2 · review 1 │ Opus 4.8 │ $0.021 │ 3.4s│
└──────────────────────────────────────────────────────────────────────────┘
```

- **Command bar (top, sticky):** source selector (sample picker / upload), schema dropdown (auto-set by router, override-able, shows routing confidence), view toggle (Extraction ↔ Eval Leaderboard), and the standing disclaimer chip.
- **Extraction view = two linked panes** (Document ⟷ Extraction Panel). They are a single bound unit: hovering in one drives the other.
- **Eval Leaderboard view** replaces the two panes with the metrics dashboard, keeping command bar + footer.
- **Result footer (bottom, sticky):** the `ExtractionResult` counts + cost + latency + versions — the honesty meter, always visible.
- **Relationship:** Document and Extraction Panel share one coordinate system (the canonical text + char offsets). The footer aggregates the panel. The leaderboard is the same product viewed at the population level instead of the single-document level.

---

## 5. Screen / region-by-region spec

### 5.1 Command bar

- **Purpose & data.** Choose input and schema; switch views; keep provenance/disclaimer present. Shows `doc_type` (routed schema key), routing confidence (from the Haiku classifier), and `model`.
- **Layout.**
```
[≡ ChartExtract]   [▾ Sample: path_report.txt] [⤒ Upload]   [Schema: pathology ▾ ·auto 0.92]   [● Extraction | ○ Eval]   [ⓘ synthetic demo · not a medical device]
```
- **States.**
  - *Empty (no doc):* sample dropdown open by default, "Pick a sample or drop a PDF/txt" ghost text; Upload zone is a dashed drop target.
  - *Routing auto:* schema chip shows `pathology · auto 0.92` (the classifier's confidence inline).
  - *Routing low-confidence / `unknown`:* schema chip turns amber, reads `unknown — choose a schema`, dropdown auto-opens, extraction is **blocked until chosen** (never silently defaults). This is the §17 "UI never silently guesses the schema" rule made visible.
  - *Override:* once a human picks, chip shows `pathology · manual` with a subtle undo to revert to auto.
- **Interactions & fluid transitions.** Selecting a sample triggers the streaming extraction (5.3). Changing the schema dropdown re-runs extraction with a fluid crossfade of the right panel. The view toggle slides the canvas between Extraction and Leaderboard with a `220ms` horizontal wipe.

### 5.2 Document pane (left)

- **Purpose & data.** Render the **canonical text** (the single source of truth for offsets) in mono, and host the **span highlights** keyed to `char_start`/`char_end`. This pane *is* the evidence.
- **Layout (ASCII).**
```
┌ DOCUMENT · path_report.txt · text-layer ✓ ────────────┐
│ SPECIMEN: Left breast core biopsy.                     │
│ DIAGNOSIS: ▌Invasive ductal carcinoma, grade 2.        │  ← ▌ = left bar + wash
│ Tumor size 1.4 cm. ER positive (90%), PR positive      │     when the linked
│ (40%), HER2 negative.                                   │     field is hovered
│ Margins not assessed on this specimen.   ← cyan wash    │
│                                                         │
│ [no mention of lymph nodes anywhere]                    │
└─────────────────────────────────────────────────────────┘
```
- **States.**
  - *Empty:* placeholder mono block, "Document renders here once extraction runs."
  - *Loading:* the text streams/fades in as `load()` returns canonical text; a thin top progress hairline.
  - *Populated, idle:* clean mono text, no washes.
  - *Populated, field hovered:* the linked span gets the flag-colored wash + 3px left bar; if off-screen, the pane glides it into view (`420ms`). Multiple spans can be pinned (see 5.3 click-to-pin).
  - *`ambiguous_span`:* the first match is washed amber **with a dotted underline** and a small "1 of 2 matches" tag — silent wrong-highlight is the failure this prevents.
  - *No-text-layer doc (vision fallback):* a full-width banner across the top of the pane: **"No text layer detected — highlighting disabled. Extracted via vision fallback; offsets unavailable."** Text still renders (best-effort), but hover does nothing and field rows show a "highlight n/a" affordance instead of a pointer. This is the §4 load-bearing caveat made honest.
  - *Refusal / error:* if `stop_reason == refusal` on the doc, the pane shows a calm inline notice ("This document tripped a safety classifier and was skipped — try another sample"), not a crash.
- **Interactions & transitions.** Hover field → wash + glide (220–420ms). Click span → it stays pinned and the matching field row highlights reciprocally (bidirectional). Selecting text in the document does nothing destructive (read-only evidence).

### 5.3 Extraction panel (right)

- **Purpose & data.** The filled schema as a list of `GroundedField` rows; the structured heart of the output. Each row shows `name`, `value`, the flag (color bar + chip), structural `confidence` (meter with τ tick), `match_quality`, and the `source_span` snippet.
- **Layout (ASCII) — one field row anatomy.**
```
┌ EXTRACTION · PathologySchema · 9 fields ─────────── [⌄ JSON] ┐
│▌specimen            Left breast core biopsy        ●accepted │
│   span "Left breast core biopsy"  exact   conf ▓▓▓▓▓▓▓░ 0.94 │
│▌diagnosis           Invasive ductal carcinoma      ●accepted │
│▌grade               2                               ●accepted │
│▌tumor_size_cm       1.4 cm                          ●accepted │
│▌er_status           positive                        ●accepted │
│▌pr_status           positive                        ●accepted │
│▌her2_status         negative                        ●accepted │
│▌margin_status       —  null                ◆not_assessed     │
│   cites "Margins not assessed on this specimen."             │
│▌lymph_nodes_positive —  null               ○not_found        │
│   document is silent — no value emitted (by design)          │
└──────────────────────────────────────────────────────────────┘
```
- **States (per row).**
  - *Empty (pre-run):* skeleton rows with the schema's field names ghosted — so the viewer sees the *contract* before values land.
  - *Streaming:* rows fade-up one by one (40ms stagger) as fields arrive; value text has a brief shimmer until grounded; the panel grows fluidly.
  - *Accepted (`None`):* green left bar, value in `text-primary`, confidence meter above τ, `match_quality` shown (`exact`/`whitespace`).
  - *`needs_review`:* amber bar, value present but dimmed slightly, confidence meter below τ (τ tick visible), a "review" pill; row is sortable to the top via a "Show review queue" toggle.
  - *`ambiguous_span`:* amber hatched bar, "matched 2 places" note, links to the first match in the doc.
  - *`not_assessed` (cyan):* value `null` shown as an em-dash, the **cited statement inline** under the row; hovering still washes the cited sentence cyan in the document.
  - *`not_found` (grey):* value `null` em-dash, "document is silent — no value emitted (by design)"; hover does nothing in the doc (nothing to cite) and the row says so.
  - *`not_grounded` (red):* value `null`, red bar, "model proposed a value; span couldn't be located → rejected" — explicitly framed as the **safety net working**, with a small "what the model said" disclosure to show the rejected value (the seam from principle 4).
  - *`max_tokens` truncation:* if the record came back partial, a banner: "Output truncated — re-running with more headroom" and the panel re-streams rather than scoring a partial record.
- **`ListField` rendering (intake/discharge):** a collapsible group header `medications · 3 of 5 grounded · 2 review`, then per-item rows `medications[0] … medications[1] …`, each independently flagged and hoverable — proves per-item grounding isn't flattened.
- **JSON disclosure:** a `[⌄ JSON]` toggle reveals the raw `ExtractionResult` (syntax-highlighted mono) for the engineer persona — `char_start/char_end`, `match_quality`, `prompt_version`/`schema_version` all visible. This is where the buyer verifies the offsets are real.
- **Interactions & transitions.** Hover row → drives doc wash (5.2). Click row → pins it (both row and span stay lit; multiple pins allowed for comparison). "Show review queue" reorders fluidly to float amber/red/ambiguous to the top (FLIP animation, 220ms). Confidence meters animate to value on stream-in.

### 5.4 Result footer (sticky)

- **Purpose & data.** The standing honesty meter: `n_grounded`, `n_null`, `n_needs_review`, `model`, `cost_usd`, `latency_s`, `prompt_version`/`schema_version`.
- **Layout.**
```
6 grounded · 2 null (1 not_found · 1 not_assessed) · 1 review   |   Opus 4.8   |   $0.021/run   |   3.4s   |   prompt v3 · schema v2
```
- **States.** Loading → counts tick up live as fields ground; cost/latency fill on completion. Error → still shows model + version so the failure is attributable.
- **Interactions.** Clicking the counts scrolls/filters the panel to that subset (e.g. click "1 review" → review queue). The `$0.021` has a tooltip breaking down input/output/cache tokens (ties to §10 caching honesty).

### 5.5 Eval leaderboard view

- **Purpose & data.** The headline artifact: per-field **precision/recall/F1**, **macro-F1**, **hallucination-rate**, **routing accuracy**, over the frozen gold set, distributionally (mean ± spread, N runs), with the **statistics-honesty caption** (small gold set → wide intervals).
- **Layout (ASCII).**
```
┌ EVAL · frozen gold set · 19 docs · N=5 runs ─────────────────────────┐
│                                                                       │
│   MACRO-F1   0.94          HALLUCINATION-RATE   0  ◎ (green ring)     │
│   ───────────────          ─────────────────────────                 │
│                                                                       │
│   Field                Prec    Recall   F1     ░ distribution ░       │
│   specimen             0.98    0.97     0.97   ▓▓▓▓▓▓▓▓▓·             │
│   diagnosis            0.95    0.93     0.94   ▓▓▓▓▓▓▓▓·              │
│   tumor_size_cm        0.96    0.96     0.96   ▓▓▓▓▓▓▓▓▓·             │
│   margin_status        1.00    1.00     1.00   ▓▓▓▓▓▓▓▓▓▓ (not_assess)│
│   lymph_nodes_positive 1.00    1.00     1.00   ▓▓▓▓▓▓▓▓▓▓ (not_found) │
│   …                                                                   │
│                                                                       │
│   Routing accuracy  0.95   │   Model: Opus 4.8                        │
│   ── cost comparison ──                                               │
│   Opus 4.8    F1 0.94   $0.021/doc                                    │
│   Sonnet 4.6  F1 0.90   $0.011/doc  ↓48% cost                        │
│                                                                       │
│   ⓘ 19 synthetic docs — report F1 with wide intervals; not real PHI. │
└───────────────────────────────────────────────────────────────────────┘
```
- **States.** Empty (no run yet): "Run the frozen eval" CTA. Running: per-field bars fill, count-up. Populated: the **hallucination-rate "0" lands last with a green ring** (the climax). Error/partial run: shows completed docs + a "k of n scored" note, never a fake total.
- **Interactions & transitions.** Numbers count up on enter; clicking a field row could (stretch) drill into the per-doc breakdown. The Opus/Sonnet rows let the buyer see the **honest cost/accuracy trade**.

---

## 6. The money-demo moment (frame-by-frame choreography)

The climax is the **hover-to-highlight on a real value, immediately followed by the two honest nulls, then the leaderboard.** Choreographed as a continuous beat:

1. **Beat 0 — setup (0.0s).** Command bar shows `Sample: path_report.txt`, schema auto-routed `pathology · auto 0.92`. Document pane already renders the mono source. Right panel shows ghosted schema field names (the contract before the values).
2. **Beat 1 — stream-in (0.0–3.4s).** Fields land top-to-bottom, 40ms stagger, each fading up with its confidence meter filling and green bars appearing: `specimen`, `diagnosis`, `grade`, `tumor_size_cm`, `er_status`, `pr_status`, `her2_status`. The panel grows fluidly; footer counts tick up. This establishes the happy path *fast*.
3. **Beat 2 — THE GESTURE (the visual that sells it).** Cursor (or auto-demo) hovers `tumor_size_cm = 1.4 cm`. Over `420ms`: the document pane glides "Tumor size 1.4 cm" into center, a **green wash expands from its left edge**, and a faint connector pulses from the field row to the span. The viewer *sees* the value wired to the exact text. Hold. This is the unforgettable frame.
4. **Beat 3 — the first honest null (`not_assessed`).** Hover `margin_status`. Value is an em-dash, cyan bar. The document glides to "Margins not assessed on this specimen." and washes it **cyan** — the tool is *citing the absence*. Inline caption: "the document states this wasn't determined." This is the senior distinction made visceral.
5. **Beat 4 — the second honest null (`not_found`).** Hover `lymph_nodes_positive`. Value em-dash, grey bar. The document pane **does not wash anything** and a calm note appears: "no mention in the document — returned null, not guessed." The contrast with Beat 3 is the whole pitch: *two kinds of empty, named.*
6. **Beat 5 — (optional) the safety net (`not_grounded`).** A toggle ("show a caught hallucination") swaps in a variant where the model proposed a value with an unlocatable span → red row, "model proposed; span couldn't be located → rejected." Reinforces that grounding is enforced in code, not promised.
7. **Beat 6 — the leaderboard climax.** View toggle wipes to Eval. Per-field F1 bars fill, macro-F1 counts to **0.94**, and the **hallucination-rate counts to 0 and lands with a green ring.** Caption: "0 hallucinated values across the frozen set." The combination — cited, honest, measured — is now proven, not claimed.

Motion discipline throughout: one thing moves at a time, ease-out, no bounce; reduced-motion shows the same washes and final numbers instantly.

---

## 7. Component inventory

- **AppShell / CommandBar** — variants: idle, routing-auto, routing-low-confidence (amber, blocks), override. Contains SourceSelector, SchemaDropdown (with inline confidence), ViewToggle, DisclaimerChip.
- **SourceSelector** — sample dropdown + upload drop-zone; states: empty, dragover, uploading, loaded, unsupported-file.
- **SchemaDropdown** — auto / manual / unknown(amber, required); shows `doc_type` + routing confidence.
- **DocumentPane** — states: empty, streaming, idle, hover-active, ambiguous-marked, no-text-layer-banner, refusal-notice.
- **SpanHighlight** — the wash + left bar; variants by flag color; sub-states: single, pinned, ambiguous (dotted + "1 of N"), off-screen-glide.
- **FieldRow** — the core repeated component. Variants by flag: accepted(green) / needs_review(amber) / ambiguous_span(amber-hatched) / not_assessed(cyan) / not_found(grey) / not_grounded(red). Sub-parts: name, value, FlagChip, ConfidenceMeter, MatchQualityTag, SpanSnippet, "what the model said" disclosure (not_grounded only). States: skeleton, streaming-shimmer, idle, hover, pinned.
- **FlagChip** — icon + label per taxonomy; tooltip with the one-line meaning.
- **ConfidenceMeter** — 0–1 ramp with τ tick; structural (not model) value; animates to position.
- **ListFieldGroup** — collapsible header ("3 of 5 grounded · 2 review") + per-item FieldRows (`name[i]`).
- **JSONInspector** — collapsible syntax-highlighted `ExtractionResult`; the offsets/match_quality verifier.
- **ResultFooter** — counts + model + cost + latency + versions; clickable to filter.
- **EvalLeaderboard** — MetricHeadline (macro-F1, hallucination-rate-with-ring), FieldMetricRow (P/R/F1 + distribution bar), RoutingAccuracy, CostComparisonRow (Opus vs Sonnet), StatsHonestyCaption.
- **Banner / Notice** — variants: no-text-layer (warning), truncation (info, auto-retry), refusal (neutral skip), error (recoverable). All "surfaced not crashed."
- **DisclaimerChip** — persistent "synthetic demo · not a medical device · not a real service."
- **ThemeToggle** — dark/light (both AA).

---

## 8. Responsive & fluid behavior (wide → narrow)

- **Fluidity model:** the whole layout scales with `clamp()` on type, spacing, and gutters — there is no single "desktop" size; it breathes continuously. Breakpoints are used only to *re-stack*, not to retune every value.
- **Wide (≥1280px):** Document pane and Extraction panel side-by-side, ~`52% / 48%` with a draggable, fluid divider; gutters grow with viewport. Footer single-line.
- **Medium (~900–1280px):** panes stay side-by-side but gutters compress; confidence meters collapse to a compact dot+number; JSON inspector defaults closed.
- **Narrow / stacked (<900px):** panes stack — Extraction panel on top (the answer), Document below (the evidence). Hover becomes **tap-to-link**: tapping a field smooth-scrolls to its span and washes it; a floating "back to fields" pill returns. Footer wraps to two lines; leaderboard table becomes stacked metric cards.
- **The hover gesture degrades gracefully:** pointer → hover; touch → tap-to-pin-and-scroll; keyboard → focus drives the same wash (see §9). The bidirectional link is preserved at every size.
- **Streaming reflow:** as fields arrive, the panel height grows fluidly with a content-driven transition; the divider and footer reposition without jank.

---

## 9. Accessibility & empty/error/edge handling summary

- **Contrast:** all text and semantic colors meet **WCAG AA (≥4.5:1)** on both dark and light surfaces; flag colors are never the *only* signal — each pairs with an icon + text label (color-blind safe; `ambiguous_span` adds a hatch pattern, `not_grounded` adds a distinct icon).
- **Keyboard paths:** full tab order — command bar → field rows → JSON → footer → view toggle. Arrow keys move between FieldRows; focusing a row triggers the same span wash + doc glide as hover; `Enter` pins; `Esc` clears pins. The leaderboard is fully tabbable. No keyboard trap in the upload zone.
- **Focus:** visible 2px `primary` focus ring with offset on every interactive element; focus is never lost on stream-in (rows announce via `aria-live="polite"` as they ground).
- **Screen readers:** each FieldRow announces `name, value or "null", flag meaning, confidence, match quality` ("tumor size, 1.4 centimeters, accepted, confidence 0.94, exact match"). Nulls announce the *reason* ("margin status, null, not assessed — document states it was not determined"). The highlight has an accessible-name link to its span.
- **Motion-reduced fallback:** `prefers-reduced-motion` removes glides/glows/count-ups; washes and final numbers appear instantly; nothing essential is conveyed by motion alone.
- **Empty states:** pre-run schema ghosting (shows the contract); empty leaderboard CTA; empty document placeholder.
- **Error/edge (all surfaced, none crash):** no-text-layer → highlight-disabled banner; `max_tokens` truncation → auto-retry notice; `refusal` → calm skip notice; doc-type misroute → most fields grey `not_found` + "looks misrouted, change schema?" hint; unsupported upload → inline "text-layer PDF or .txt only (OCR out of scope)."
- **Honesty furniture:** persistent synthetic-demo disclaimer; cost/latency/version always visible; structural-vs-model confidence labeled so certainty is never overstated.

---

## 10. Mockup shot list (frames for Claude Design to render)

1. **`01-extraction-hero-hover.png`** — The money frame. Pathology doc left (mono, "Tumor size 1.4 cm" washed **green**), Extraction panel right with all rows populated, `tumor_size_cm` row hovered, connector pulse, footer counts + $0.021 + 3.4s. Dark mode. *This is the portfolio screenshot.*
2. **`02-two-honest-nulls.png`** — Split focus on `margin_status` (cyan `not_assessed`, "Margins not assessed" washed cyan in doc) and `lymph_nodes_positive` (grey `not_found`, nothing washed). The named-gaps story in one image.
3. **`03-not-grounded-caught.png`** — The safety net: a red `not_grounded` row with the "what the model said" disclosure open, doc showing no matching span. Reads as "model tried, code caught it."
4. **`04-eval-leaderboard.png`** — Full leaderboard: macro-F1 0.94, **hallucination-rate 0 with green ring**, per-field P/R/F1 distribution bars, routing accuracy 0.95, Opus-vs-Sonnet cost row, stats-honesty caption.
5. **`05-streaming-state.png`** — Mid-extraction: 4 rows landed (green, confidence meters filling), 3 still skeleton/shimmer, panel mid-growth — captures the "layout breathes as content streams" fluidity.
6. **`06-listfield-intake.png`** — Intake schema with a `ListField`: `medications · 3 of 5 grounded · 2 review` collapsible group, per-item rows with mixed flags — proves per-item grounding + routing beyond pathology.
7. **`07-no-text-layer-banner.png`** — The honest degraded state: vision-fallback banner across the document pane, field rows showing "highlight n/a," everything else intact. Honesty-as-a-feature frame.
8. **`08-narrow-stacked.png`** — Mobile/narrow: Extraction panel stacked above Document, a field tapped → its span scrolled-to and washed, "back to fields" pill. Shows fluid responsive behavior. (Optionally render light mode here to show both themes.)
