"""The HTTP contract: ``/health``, ``/api/samples``, ``/api/extract``, ``/api/eval`` (R2/R3).

Every route is **adapter-thin**: it resolves inputs, calls :func:`chartextract.extract` (or the
eval harness), and serializes the result. No grounding, flag, or scoring logic lives here. The
success body of ``/api/extract`` is literally ``ExtractionResult.model_dump()`` — the identical
shape the UI's JSON inspector renders — so nothing is recomputed in the adapter or the frontend.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from chartextract import extract

from . import deps
from .errors import APIError
from .schemas import EvalSummary, ExtractRequest, HealthResponse, SampleItem

#: Upload file extensions the engine can load (text-layer only — OCR is out of scope, §4).
_ALLOWED_UPLOAD_SUFFIXES = (".txt", ".pdf")


def register_routes(app: FastAPI) -> None:
    @app.get("/health", response_model=HealthResponse)
    def get_health() -> HealthResponse:
        provider, model = deps.active_provider_health()
        return HealthResponse(provider=provider, model=model)

    @app.get("/api/samples", response_model=list[SampleItem])
    def get_samples() -> list[SampleItem]:
        return deps.load_samples()

    @app.post("/api/extract")
    async def post_extract(request: Request) -> JSONResponse:
        """Run the engine over a sample / inline text / uploaded file. Returns the core
        :class:`~chartextract.ExtractionResult` serialized as-is (200)."""
        sample_id, text, schema, provider, doc_source, source_name = await _parse_extract_request(
            request
        )
        # Build the provider from the resolved text so the offline stub can pick the right canned
        # output; the live provider ignores it. A missing key surfaces as the 503 envelope.
        guess_text = (
            text if text is not None else (doc_source if isinstance(doc_source, str) else "")
        )
        provider_obj = deps.get_provider(provider, text=guess_text, schema=schema)
        result = extract(doc_source, schema=schema, provider=provider_obj, source_name=source_name)
        # `highlight_available` is already a field on ExtractionResult — it round-trips here so the
        # Split 09 banner can read it (the no-text-layer signal from Split 03).
        return JSONResponse(content=result.model_dump())

    @app.get("/api/eval", response_model=EvalSummary)
    def get_eval() -> EvalSummary:
        return deps.build_eval_summary()


# ---------------------------------------------------------------------------
# Request parsing — JSON body or multipart upload, one endpoint.
# ---------------------------------------------------------------------------


async def _parse_extract_request(
    request: Request,
) -> tuple[str | None, str | None, str | None, str | None, str | Path, str | None]:
    """Resolve a request into ``(sample_id, text, schema, provider, doc_source, source_name)``.

    Exactly one of ``sample_id`` / ``text`` / uploaded ``file`` must be provided. ``doc_source`` is
    what gets handed to :func:`chartextract.extract` — the canonical text (sample/inline) or a temp
    file path (upload). Raises :class:`APIError` (→ envelope) for any malformed input.
    """
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        return await _parse_multipart(request)
    return await _parse_json(request)


async def _parse_json(
    request: Request,
) -> tuple[str | None, str | None, str | None, str | None, str | Path, str | None]:
    raw = await request.body()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise APIError(422, "bad_request", f"malformed JSON body: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise APIError(422, "bad_request", "request body must be a JSON object")
    try:
        req = ExtractRequest.model_validate(payload)
    except ValidationError as exc:
        raise APIError(422, "bad_request", _summarize(exc)) from exc

    _require_exactly_one(sample_id=req.sample_id, text=req.text, file=None)
    if req.sample_id is not None:
        doc_text = deps.sample_text(req.sample_id)
        return req.sample_id, None, req.schema_override, req.provider, doc_text, req.sample_id
    # inline text
    return None, req.text, req.schema_override, req.provider, req.text or "", "inline"


async def _parse_multipart(
    request: Request,
) -> tuple[str | None, str | None, str | None, str | None, str | Path, str | None]:
    form = await request.form()
    upload = form.get("file")
    sample_id = _form_str(form.get("sample_id"))
    text = _form_str(form.get("text"))
    schema = _validate_schema(_form_str(form.get("schema")))
    provider = _form_str(form.get("provider"))

    has_file = upload is not None and getattr(upload, "filename", None)
    _require_exactly_one(sample_id=sample_id, text=text, file=has_file or None)

    if has_file:
        filename = upload.filename or "upload"
        suffix = Path(filename).suffix.lower()
        if suffix not in _ALLOWED_UPLOAD_SUFFIXES:
            raise APIError(
                415,
                "unsupported_file",
                f"unsupported file type {suffix or '(none)'!r}",
                hint="text-layer PDF or .txt only (OCR is out of scope)",
            )
        data = await upload.read()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(data)
            tmp.flush()
        finally:
            tmp.close()
        return None, None, schema, provider, Path(tmp.name), filename
    if sample_id is not None:
        return sample_id, None, schema, provider, deps.sample_text(sample_id), sample_id
    return None, text, schema, provider, text or "", "inline"


def _require_exactly_one(*, sample_id: object, text: object, file: object) -> None:
    provided = [name for name, v in (("sample_id", sample_id), ("text", text), ("file", file)) if v]
    if len(provided) != 1:
        raise APIError(
            422,
            "bad_request",
            "provide exactly one of sample_id, text, or an uploaded file "
            f"(got: {provided or 'none'})",
        )


def _validate_schema(value: str | None) -> str | None:
    if value is None or value in ("pathology", "intake"):
        return value
    raise APIError(422, "bad_request", f"unknown schema {value!r} (use 'pathology' or 'intake')")


def _form_str(value: object) -> str | None:
    """A non-empty form string, else ``None`` (an empty field is treated as absent)."""
    if isinstance(value, str) and value.strip():
        return value
    return None


def _summarize(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", ()))
        parts.append(f"{loc or 'body'}: {err.get('msg', 'invalid')}")
    return "invalid request: " + "; ".join(parts) if parts else "invalid request body"
