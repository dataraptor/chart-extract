# ChartExtract - developer + demo entrypoints. Thin wrappers only (no logic lives here).
# On Windows without `make`, run the underlying command in each recipe directly.
# Python is `python` here; on this box the interpreter is C:/ProgramData/miniconda3/python.exe.
.PHONY: install install-api test test-api lint cov demo demo-stub serve eval \
        e2e e2e-install docker-build docker-up clean

# --- Install ----------------------------------------------------------------

# Install the whole stack editable: engine (+ provider SDKs), eval, API, with dev tooling.
install:
	pip install -e "core/[providers,dev]"
	pip install -e "eval/"
	pip install -e "api/[dev]"

# Install just the HTTP adapter (and the eval extra for /api/eval) editable.
install-api:
	pip install -e "eval/"
	pip install -e "api/[dev]"

# --- Test / quality ---------------------------------------------------------

# Engine Tier-1 (no-key) test suite.
test:
	cd core && python -m pytest -q -m "not api"

# HTTP adapter Tier-1 (no-key) test suite.
test-api:
	cd api && python -m pytest -q -m "not api"

# Lint + format check across every Python package (no writes).
lint:
	cd core && python -m ruff check . && python -m ruff format --check .
	cd eval && python -m ruff check . && python -m ruff format --check .
	cd api  && python -m ruff check . && python -m ruff format --check .

# Coverage gate on the engine's Tier-1 suite (the per-package threshold lives in pyproject).
cov:
	cd core && python -m pytest -q -m "not api" --cov=chartextract --cov-report=term-missing

# --- Demo / run -------------------------------------------------------------

# The one-command money demo: live with a key in .env, else cleanly offline.
demo:
	python demo.py

# The offline money demo: deterministic canned data, no key, no network.
demo-stub:
	python demo.py --stub

# Run the HTTP API (serves the app/ UI same-origin at http://127.0.0.1:8000/).
serve:
	chartextract-api

# Print the offline eval leaderboard (deterministic; no key).
eval:
	python -m eval.run --provider stub --no-write

# --- E2E (Playwright over api(stub) + app) ----------------------------------

# One-time: install the npm deps + the Chromium browser the e2e suite drives.
e2e-install:
	cd app && npm install && npm run e2e:install

# Cross-stack e2e + a11y + responsive suite. Auto-skips cleanly if Chromium isn't installed.
e2e:
	cd app && npm run e2e

# --- Docker -----------------------------------------------------------------

# Build the single demo image (engine + API + static UI). No secret is baked in.
docker-build:
	docker build -f api/Dockerfile -t chartextract:latest .

# Bring up the stack (open http://localhost:8000/). Live if .env has a key, stub otherwise.
docker-up:
	docker compose up --build

# --- Housekeeping -----------------------------------------------------------

clean:
	rm -rf .ruff_cache .pytest_cache **/__pycache__ **/*.egg-info .coverage
