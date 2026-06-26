"""``chartextract-api`` — run the HTTP service (uvicorn), serving the ``app/`` UI same-origin.

A thin launcher: ``chartextract-api [--host H] [--port P] [--reload] [--dev]``. ``--dev`` enables
the permissive CORS allowlist (for a designer serving the ``.dc.html`` from a separate port);
otherwise everything is same-origin and no CORS is needed.
"""

from __future__ import annotations

import argparse
import os


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chartextract-api", description="Run the ChartExtract HTTP API (uvicorn)."
    )
    p.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="bind port (default 8000)")
    p.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    p.add_argument(
        "--dev", action="store_true", help="enable permissive localhost CORS (separate UI port)"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.dev:
        os.environ.setdefault("CHARTEXTRACT_CORS_DEV", "1")

    import uvicorn

    uvicorn.run("chartextract_api.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":  # pragma: no cover - thin entrypoint
    raise SystemExit(main())
