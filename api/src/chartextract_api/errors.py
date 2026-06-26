"""The error envelope and exception handlers — the honesty contract (§15 / UIUX §9).

**No endpoint may leak a stack trace.** Every typed core failure (and every uncaught one) becomes
the single structured shape::

    { "error": { "type": "<machine_code>", "message": "<human>", "hint"?: "<what to do>" } }

so the UI (Split 09) can map ``type`` to a calm, recoverable notice. Full detail is logged
server-side; only the clean message is returned to the client.

Mapping (core exception → HTTP + ``type``):

==========================  ====  ==================  =====================================
Core exception              HTTP  ``type``            UI consumes it as
==========================  ====  ==================  =====================================
``MissingAPIKeyError``      503   ``missing_api_key`` "running offline / set a key"
``RefusalError``            422   ``refusal``         "document tripped a safety classifier"
``TruncatedError``          422   ``truncated``       "output truncated — re-run w/ headroom"
``UnknownDocTypeError``     409   ``unknown_doc_type``amber "choose a schema" (blocks)
``APIError(415,...)``       415   ``unsupported_file``"text-layer PDF or .txt only"
``RequestValidationError``  422   ``bad_request``     generic recoverable notice
anything else               500   ``internal``        generic; never a traceback
==========================  ====  ==================  =====================================
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from chartextract.provider.base import (
    MissingAPIKeyError,
    RefusalError,
    TruncatedError,
)
from chartextract.router import UnknownDocTypeError

from .schemas import ErrorEnvelope

logger = logging.getLogger("chartextract_api")


class APIError(Exception):
    """An expected, client-facing failure rendered as the structured envelope.

    Used for failures that originate in the adapter itself (a malformed body, an unsupported
    upload) rather than from a typed core exception.
    """

    def __init__(self, status_code: int, type: str, message: str, *, hint: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.type = type
        self.message = message
        self.hint = hint


def envelope(status_code: int, type: str, message: str, *, hint: str | None = None) -> JSONResponse:
    """Build the canonical error response. ``hint`` is omitted when ``None`` (no empty keys)."""
    body = ErrorEnvelope.model_validate({"error": {"type": type, "message": message, "hint": hint}})
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


def register_exception_handlers(app: FastAPI) -> None:
    """Install one handler per typed failure — every path returns :func:`envelope` (R5)."""

    @app.exception_handler(APIError)
    async def _api_error(_: Request, exc: APIError) -> JSONResponse:
        return envelope(exc.status_code, exc.type, exc.message, hint=exc.hint)

    @app.exception_handler(MissingAPIKeyError)
    async def _missing_key(_: Request, exc: MissingAPIKeyError) -> JSONResponse:
        return envelope(
            503,
            "missing_api_key",
            str(exc),
            hint="running offline; set AZURE_OPENAI_API_KEY (or OPENAI_API_KEY) for live runs",
        )

    @app.exception_handler(RefusalError)
    async def _refusal(_: Request, exc: RefusalError) -> JSONResponse:
        return envelope(
            422,
            "refusal",
            str(exc),
            hint="the document tripped a safety classifier and was skipped",
        )

    @app.exception_handler(TruncatedError)
    async def _truncated(_: Request, exc: TruncatedError) -> JSONResponse:
        return envelope(
            422, "truncated", str(exc), hint="output was truncated — re-run with more headroom"
        )

    @app.exception_handler(UnknownDocTypeError)
    async def _unknown_doc(_: Request, exc: UnknownDocTypeError) -> JSONResponse:
        return envelope(
            409, "unknown_doc_type", str(exc), hint="choose a schema (pathology or intake)"
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return envelope(422, "bad_request", _summarize_validation(exc))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Last line of defence: log the trace server-side, return a neutral envelope (§15).
        logger.exception("unhandled error in chartextract API")
        return envelope(500, "internal", "an internal error occurred")


def _summarize_validation(exc: RequestValidationError) -> str:
    """A short, traceback-free summary of a request-validation failure."""
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
        parts.append(f"{loc or 'body'}: {err.get('msg', 'invalid')}")
    return "invalid request: " + "; ".join(parts) if parts else "invalid request body"
