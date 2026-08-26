UV := $(or $(shell command -v uv 2>/dev/null),$(HOME)/.local/bin/uv)

# `test` and `ship-gate` order their prerequisites deliberately. `make -j` would
# run them concurrently, and two pytest processes in one worktree invent failures.
.NOTPARALLEL:

.DEFAULT_GOAL := help

# This repo IS the shared tooling, so it includes its own fragment in place
# rather than through a pinned `.tooling/` clone.
TOOLING := .
include mk/common.mk

.PHONY: help install lint format format-check shellcheck test test-fast test-scoped ship-gate

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install the test dependencies
	$(UV) sync

lint: shellcheck ## Lint the Python (ruff) and every shell script (shellcheck)
	$(UV) run ruff check scripts/ tests/

format: ## Format with ruff (writes)
	$(UV) run ruff format scripts/ tests/
	$(UV) run ruff check --fix scripts/ tests/

format-check: ## What CI's format job runs — asserts, never writes
	$(UV) run ruff format --check scripts/ tests/

shellcheck: ## Shellcheck every script (skipped with a note when it is not installed)
	@command -v shellcheck >/dev/null 2>&1 || { echo "[lint] skipped shellcheck — not on PATH (brew install shellcheck)"; exit 0; }
	@shellcheck scripts/*.sh bootstrap/*.sh plugins/*/scripts/*.sh

test-fast: ## The guards — the whole suite is the fast lane here
	$(UV) run pytest tests/ -q

test-scoped: test-fast ## Everything; this repo is small enough that scoping it would be theatre

test: test-fast ## Everything

ship-gate: lint format-check test tooling-check ## The full local gate /ship runs
	@echo "[ship-gate] ok"
