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

## Running live (optional)

By default the CLI runs fully offline on a deterministic stub — no key, no network, `$0`:

```bash
chartextract extract examples/path_report.txt
```

The **live** backend is Azure OpenAI **GPT-5.5** (`provider/openai.py`). Copy
[`.env.example`](.env.example) to `.env`, set `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_KEY`
(or `OPENAI_API_KEY` for api.openai.com), export them, and the CLI auto-selects the live provider
(use `--stub` to force offline). **Live calls are opt-in and cost money.** The `@pytest.mark.api`
conformance tests need a key and auto-skip without one, so the free Tier-1 suite always passes.

## Run the real UI

The web UI in [`app/`](app/) is wired to the live engine. Install and serve the API (it serves the
UI at the same origin, so there's no CORS to configure):

```bash
make install-api      # pip install -e "core/[providers]" and "api/[eval]"
chartextract-api      # serves the UI + API at http://localhost:8000/
```

Open <http://localhost:8000/>. With no key it runs the deterministic **stub** (every value real,
`$0`); with a key set it runs **live GPT-5.5**. The page fetches `/api/samples`, `/api/extract`,
and `/api/eval` — the document text, field values, spans, offsets, flags, confidence, counts, cost,
and the eval leaderboard all come from the engine. Append `?stub=1` (or open `app/ChartExtract.dc.html`
with no server) to fall back to the inline canned data for a no-backend preview. Full demo
orchestration (a one-command launch + Docker) lands later; this is enough to see it live.
