# ChartExtract — developer entrypoints. Targets are extended split by split.
# On Windows without `make`, run the underlying commands directly (see each recipe).
.PHONY: install install-api test test-api serve e2e e2e-install

# Install the engine editable, with dev tooling (pytest + ruff).
install:
	pip install -e "core/[dev]"

# Install the HTTP adapter (and the eval extra for /api/eval) editable.
install-api:
	pip install -e "eval/"
	pip install -e "api/[dev]"

# Run the engine's Tier-1 (no-key) test suite.
test:
	cd core && python -m pytest -q -m "not api"

# Run the HTTP adapter's Tier-1 (no-key) test suite.
test-api:
	cd api && python -m pytest -q -m "not api"

# Run the HTTP API (serves the app/ UI same-origin at http://127.0.0.1:8000).
serve:
	chartextract-api

# One-time: install the npm deps + the Chromium browser the e2e suite drives.
e2e-install:
	cd app && npm install && npm run e2e:install

# Cross-stack e2e + a11y + responsive suite (Playwright over api(stub) + app). Auto-skips cleanly
# if Chromium isn't installed, so this stays CI-safe. Boots the stub API itself (no key needed).
e2e:
	cd app && npm run e2e
