# ChartExtract - single-process demo image (engine + HTTP adapter + static UI mount).
#
# Build from the REPO ROOT so core/, eval/, app/ are all in context:
#   docker build -f api/Dockerfile -t chartextract .
#   docker run --rm -p 8000:8000 chartextract                      # offline stub, no key
#   docker run --rm -p 8000:8000 --env-file .env chartextract      # live (key from .env)
# Then open http://localhost:8000/  -- /api/* and the UI are same-origin (no CORS).
#
# Note: the UI loads its React/DC runtime from app/support.js (served locally); the container
# itself only serves static files + the API. No secret is baked into the image - keys arrive at
# runtime via --env-file / -e, and with no key the app runs the deterministic stub.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Install the engine (with provider SDKs), then the eval extra, then the API - all editable so
# package data (examples, the frozen leaderboard) resolves from the repo layout at /srv.
COPY core/ ./core/
RUN pip install -e "./core/[providers]"

COPY eval/ ./eval/
RUN pip install -e ./eval/

COPY api/ ./api/
RUN pip install -e ./api/

# The bundled examples and frozen eval artifact the adapter reads (resolved from the repo root).
COPY examples/ ./examples/
COPY docs/ ./docs/

# The frontend the API mounts at / (point the resolver at it explicitly).
COPY app/ ./app/
ENV CHARTEXTRACT_APP_DIR=/srv/app

# Run as a non-root user.
RUN useradd --create-home --uid 10001 chartextract \
    && chown -R chartextract:chartextract /srv
USER chartextract

EXPOSE 8000

# Liveness: /health answers with no key, in both stub and live mode.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "chartextract_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
