# mk/node.mk — the shared-target contract for a Node/TypeScript repo.
#
# Include it after mk/common.mk in a repo whose toolchain is npm. It maps the
# targets the devkit plugin calls (`lint`, `test`, `test-fast`, `test-scoped`,
# `ship-gate`) onto npm scripts, so the same /ship and the same Stop hook drive
# a Vite front end and an Electron app without knowing anything about either.
#
# The repo's package.json must define: lint, format, format:check, typecheck,
# test, build. `make tooling-check` catches a missing target; npm itself
# reports a missing script.
#
# `test-scoped` defaults to the whole unit lane. A repo with a scope selector
# overrides it AFTER this include.

NPM ?= npm

.PHONY: install lint format format-check typecheck test test-fast test-scoped build ship-gate

install: ## Install dependencies from the committed lockfile
	$(NPM) ci

lint: ## Lint
	$(NPM) run lint

format: ## Format (writes)
	$(NPM) run format

format-check: ## Format check (asserts, never writes)
	$(NPM) run format:check

typecheck: ## Type-check without emitting
	$(NPM) run typecheck

test-fast: ## Unit tests — the tight edit-test loop
	$(NPM) test

test-scoped: test-fast ## Only what the working tree touches (defaults to the whole unit lane)

test: typecheck test-fast ## Type-check + unit tests

build: ## Production build
	$(NPM) run build

ship-gate: lint format-check test build ## The full local gate /ship runs
	@echo "[ship-gate] ok"
