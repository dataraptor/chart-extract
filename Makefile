# ChartExtract — developer entrypoints. Targets are extended split by split.
# On Windows without `make`, run the underlying commands directly (see each recipe).
.PHONY: install test

# Install the engine editable, with dev tooling (pytest + ruff).
install:
	pip install -e "core/[dev]"

# Run the engine's Tier-1 (no-key) test suite.
test:
	cd core && python -m pytest -q -m "not api"
