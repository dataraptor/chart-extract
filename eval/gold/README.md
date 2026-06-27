# Gold dataset (frozen) - ChartExtract eval

17 **synthetic** clinical documents (10 pathology, 5 intake, 2 discharge), each authored by hand.
**No real PHI: every value is invented.** This set is **frozen**: changing a document or a label is
a versioned event (bump `NORMALIZE_VERSION` in `eval/normalize.py` when the comparison rules change),
not a casual tweak. It is the population the leaderboard reports over.

## Why these documents

The headline claim, *"high macro-F1 with **0 hallucinated values** across the frozen set,"* is only
credible if the set deliberately stresses the parts of the contract that competitors get wrong. So
every record is chosen to exercise one of these, and the set as a whole carries **all three kinds of
empty**:

1. **absent** → gold `null`, expected flag `not_found`. The field is never mentioned (e.g.
   `lymph_nodes_positive` in `path_00`, the whole tail of `path_09_sparse`).
2. **explicitly-not-assessed** → gold `null` *with a cited statement*, expected flag `not_assessed`.
   The document says the field was not determined (e.g. `margin_status` cites *"Margins not assessed
   on this specimen"* in `path_00`; `her2_status` is *pending* in `path_02_lobular`). This is the
   clinically important distinction the eval **rewards** rather than punishes: a `not_assessed` match
   is **correct and never counted as a hallucination**.
3. **present-but-easy-to-hallucinate** → a real value the model is tempted to round or infer, chiefly
   tumour sizes written in **millimetres** (`22 mm`, `8 mm`, `17 mm`) that must normalize to
   centimetres (`2.2`, `0.8`, `1.7`); this checks the numeric normalizer and the no-inference rule.
   Enum synonyms (`ER+`, `HER2+`, `equivocal`) exercise the enum normalizer the same way.

At least one intake document carries a multi-value **`ListField`** label so the per-item grounding
path is scored: `intake_03_polypharmacy` has five medications and three allergies, and the canonical
`intake_00_form` has three medications and one allergy.

The two **discharge** documents are **routing-only**: v1 ships no `DischargeSchema`, so they carry no
field labels. They exist solely so routing accuracy can score that the classifier maps them to
`discharge` (which the router then correctly surfaces as `unknown`, never silently defaulting to a
breast-pathology schema).

## Label schema

One JSON file per document beside this README; the document text lives under `docs/`. The loader
(`eval/dataset.py`) validates every record against the engine's own schemas, so a typo is a
load-time error, not a silently-wrong metric.

```jsonc
{
  "id": "path_00_worked_example",
  "doc_type": "pathology",          // pathology | intake | discharge
  "doc": "path_00_worked_example.txt",
  "labels": {
    // a present value: bare, or {value, span} to pin the source span the oracle replays:
    "specimen": "Left breast core biopsy",
    "er_status": { "value": "ER+", "span": "ER positive (90%)" },
    // the field is never mentioned → null, expect not_found:
    "lymph_nodes_positive": { "empty": "not_found" },
    // the document states it was not assessed → null, expect not_assessed WITH the cited line:
    "margin_status": { "empty": "not_assessed", "cite": "Margins not assessed on this specimen" }
  }
}
```

* A **list** label is a JSON array of items (each a bare string or `{value, span}`).
* `value` is the form the **scorer** compares (synonyms and units allowed, since the normalizer
  canonicalizes it); `span` or `cite` is the verbatim document text the deterministic **oracle**
  replays so the real grounding code runs. The generator asserts every `span` or `cite` is a
  verbatim substring of its doc.

## Statistics honesty

17 synthetic documents is a *small* set: report F1 with **wide intervals** and never over-claim from
a handful of documents. The leaderboard prints this caption on every run.
