# ChartExtract

A grounded, eval-proven engine that extracts typed clinical fields from documents and **proves
every value against the source text** — each field carries a verbatim span, computed character
offsets, a structural confidence, and a flag (`needs_review`, `not_grounded`, `not_found`, …) so a
reviewer can trust or correct it. The model proposes `{value, source_span, confidence}`; offsets,
match quality, confidence, and flags are computed in code, never by the model. The build contract
lives in [`tmp/11-chartextract.md`](tmp/11-chartextract.md) and the UI/UX contract in
[`app/ChartExtract-UIUX-Spec.md`](app/ChartExtract-UIUX-Spec.md).

The Python engine lives in [`core/`](core/). Install it editable with `make install`
(`pip install -e "core/[dev]"`) and run the test suite with `make test`.
