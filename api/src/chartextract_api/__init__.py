"""ChartExtract HTTP API — a thin FastAPI adapter over the ``chartextract`` engine (Split 06).

This package owns **no extraction logic**. Every route imports :func:`chartextract.extract` (and,
for the leaderboard, the ``eval`` harness) and serializes the result — the success body of
``/api/extract`` is literally ``ExtractionResult.model_dump()``, the same shape the UI's JSON
inspector already renders. The two real responsibilities are (1) turning every *typed* core error
into a clean JSON :class:`~chartextract_api.schemas.ErrorEnvelope` — never a 500 traceback — and
(2) serving the existing ``app/`` UI as static files from the **same origin**, so the frontend
(Split 07) talks to one host with no CORS friction and the whole stack runs offline on the stub.
"""

from __future__ import annotations

from .app import app, create_app

__version__ = "0.1.0"

__all__ = ["app", "create_app", "__version__"]
