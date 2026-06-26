"""The FastAPI app factory: routes, the error-envelope handlers, optional dev CORS, and the
same-origin static mount of the existing ``app/`` UI (R5).

An **adapter, not a brain.** ``create_app`` only wires: it registers the routes (``routes.py``),
the exception handlers (``errors.py``), and mounts the prototype so ``GET /`` serves
``ChartExtract.dc.html`` and ``support.js``/``api.js``/``map.js`` load from the **same origin** —
no CORS needed in production. Permissive CORS is added **only** behind an explicit env flag, for a
designer serving the ``.dc.html`` from a separate dev port.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import chartextract

from .errors import register_exception_handlers
from .routes import register_routes

#: The UI entry document mounted at ``/``.
_INDEX_FILENAME = "ChartExtract.dc.html"


def _app_dir() -> Path | None:
    """The static frontend directory to serve (repo-root ``app/`` by default).

    Resolved from the installed ``chartextract`` package (``core/src/chartextract`` →
    ``parents[3]`` is the repo root); overridable via ``CHARTEXTRACT_APP_DIR`` for non-editable
    deployments. ``None`` when the directory is absent (the API then degrades ``/`` to a JSON
    service pointer).
    """
    override = os.environ.get("CHARTEXTRACT_APP_DIR")
    base = Path(override) if override else Path(chartextract.__file__).resolve().parents[3] / "app"
    return base if base.is_dir() else None


def _cors_origins() -> list[str] | None:
    """Dev-only CORS allowlist. Off by default (same-origin needs none); enabled by setting
    ``CHARTEXTRACT_CORS_ORIGINS`` (comma-separated) or ``CHARTEXTRACT_CORS_DEV=1`` (localhost)."""
    raw = os.environ.get("CHARTEXTRACT_CORS_ORIGINS")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    if os.environ.get("CHARTEXTRACT_CORS_DEV", "").strip().lower() in ("1", "true", "yes", "on"):
        return ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000"]
    return None


def create_app() -> FastAPI:
    """Construct the app: handlers, routes, optional CORS, and the static mount."""
    app = FastAPI(
        title="ChartExtract API",
        version="0.1.0",
        description="Thin HTTP adapter over the grounded chartextract engine.",
    )

    origins = _cors_origins()
    if origins is not None:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)
    register_routes(app)
    _mount_static(app)
    return app


def _mount_static(app: FastAPI) -> None:
    """Serve the ``app/`` UI at ``/`` (same origin). Registered AFTER the API routes so ``/health``
    and ``/api/*`` win; the mount only catches the static assets."""
    app_dir = _app_dir()

    if app_dir is None:

        @app.get("/", include_in_schema=False, response_model=None)
        async def _root_no_app() -> JSONResponse:
            return JSONResponse({"service": "chartextract-api", "docs": "/docs"})

        return

    index = app_dir / _INDEX_FILENAME

    @app.get("/", include_in_schema=False, response_model=None)
    async def _root() -> FileResponse | JSONResponse:
        if index.is_file():
            return FileResponse(str(index), media_type="text/html")
        return JSONResponse({"service": "chartextract-api", "docs": "/docs"})

    # Mount last, at /, so the prototype's relative `./support.js` etc. resolve same-origin. The
    # explicit routes above are matched first; this only serves files under app_dir.
    app.mount("/", StaticFiles(directory=str(app_dir), html=True), name="app")


#: The module-level app used by ``uvicorn chartextract_api.app:app``.
app = create_app()
