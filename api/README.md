# ChartExtract API

A **thin** FastAPI adapter over the [`chartextract`](../core) engine. It holds no extraction logic:
every route imports `chartextract.extract` (and, for the leaderboard, the [`eval`](../eval) harness)
and serializes the result. The success body of `POST /api/extract` is literally
`ExtractionResult.model_dump()` — the identical shape the UI's JSON inspector renders.

## Install & run

```bash
pip install -e "core/[dev]"          # the engine
pip install -e "eval/"               # for /api/eval (optional)
pip install -e "api/[dev]"           # this adapter
chartextract-api                     # http://127.0.0.1:8000  (serves app/ same-origin)
```

Open <http://127.0.0.1:8000/> — the `app/ChartExtract.dc.html` UI is served from the same origin,
so no CORS is needed. With `AZURE_OPENAI_API_KEY` set the server runs the live GPT-5.5 provider;
otherwise it runs the deterministic stub (canned data, `$0`), reported honestly on `/health`.

`--dev` enables a permissive localhost CORS allowlist for serving the UI from a separate port.

## HTTP contract

| Method | Path            | Body / params                                              | Returns |
|--------|-----------------|------------------------------------------------------------|---------|
| GET    | `/health`       | —                                                          | `{status, provider, model}` |
| GET    | `/api/samples`  | —                                                          | `[{id, name, doc_type_hint, text}]` (text is the canonical offset source) |
| POST   | `/api/extract`  | JSON `{sample_id?, text?, schema?, provider?}` or multipart `{file, schema?, provider?}` | `ExtractionResult` (200) |
| GET    | `/api/eval`     | —                                                          | UIUX §5.5 leaderboard summary |

Exactly one of `sample_id` / `text` / uploaded `file` is required. `schema` (`pathology`|`intake`)
overrides routing; omit it to route via the classifier. `provider` is `stub` or `openai`.

## Error envelope

Every typed core failure becomes a structured JSON body — never a 500 traceback:

```json
{ "error": { "type": "<code>", "message": "<human>", "hint": "<what to do>" } }
```

| Core error | HTTP | `type` |
|---|---|---|
| `MissingAPIKeyError` | 503 | `missing_api_key` |
| `RefusalError` | 422 | `refusal` |
| `TruncatedError` | 422 | `truncated` |
| `UnknownDocTypeError` | 409 | `unknown_doc_type` |
| unsupported upload | 415 | `unsupported_file` |
| malformed body | 422 | `bad_request` |
| anything else | 500 | `internal` |

## Tests

```bash
cd api && python -m pytest -q          # Tier-1, no key, on the stub
```
