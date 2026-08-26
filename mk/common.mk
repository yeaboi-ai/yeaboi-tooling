# mk/common.mk — the targets every yeaboi repo shares.
#
# Included through the six-line bootstrap in each repo's Makefile, which clones
# this repo to `.tooling/` at the sha in `.tooling-rev`. See bootstrap/README.md.
#
# What lives here is repo-agnostic by construction: worktree lifecycle, the
# tooling pin itself, and contract vendoring. Everything a toolchain decides —
# `lint`, `test`, `test-fast`, `test-scoped`, `ship-gate` — stays in the repo's
# own Makefile, and `make tooling-check` asserts it defined them.

TOOLING ?= .tooling
TOOLING_REPO ?= https://github.com/yeaboi-ai/yeaboi-tooling.git

# Editor CLI used by `make wt-open`. Override for VS Code forks
# (e.g. `CODE=cursor make wt-open NAME=my-feature`).
CODE ?= code

# The workspace script runs on whatever python3 the machine already has — it
# imports nothing outside the standard library and nothing added after 3.9.
PYTHON ?= python3
WORKSPACE := $(PYTHON) $(TOOLING)/scripts/workspace.py

# `demo` is part of the required contract below, so it arrives with the rest of
# the shared targets rather than needing a second include in every repo. A repo
# only supplies its own demo_spec.py.
include $(TOOLING)/mk/demo.mk

# Feature clips — the per-PR counterpart to `demo`. Deliberately not in
# TOOLING_REQUIRED_TARGETS: mk/clip.mk defines the targets unconditionally, so
# every repo has them the moment it bumps the pin, and requiring a name that
# always exists only adds a way to be red.
include $(TOOLING)/mk/clip.mk

# The targets the devkit plugin's commands and hooks invoke on any repo. A repo
# that does not define one of these is missing half the workflow, silently.
# `demo` is here because every repo's README opens with a GIF of its own
# surface, and a GIF nobody can re-record goes stale the first time the UI moves.
TOOLING_REQUIRED_TARGETS ?= lint test test-fast test-scoped ship-gate demo

.PHONY: wt-new wt-open wt-headless wt-issue wt-list wt-rm wt-rm-all \
        wt-set wt-sets wt-set-rm workspace-setup workspace-status workspace-env \
        tooling-sync tooling-bump tooling-check contracts-sync contracts-check

# --- worktrees ---------------------------------------------------------------

# Guard NAME= for every wt-* target without duplicating the message.
define need-name
	@test -n "$(NAME)" || { echo "usage: make $@ NAME=<slug>  (e.g. NAME=standup-fix)"; exit 1; }
endef

# The scripts live in the `.tooling` clone, which is its own git repository, so
# they take the project from the environment rather than from their own path.
WT_ENV := WT_REPO_DIR="$(CURDIR)" CODE="$(CODE)"

wt-new: ## Create worktree .claude/worktrees/NAME off latest origin/main (branch + provision) + open in VS Code with claude auto-running
	$(need-name)
	$(WT_ENV) bash $(TOOLING)/scripts/wt.sh "$(NAME)" open

wt-open: ## Open worktree in a NEW VS Code window with claude auto-running (creates it off latest origin/main first if needed)
	$(need-name)
	$(WT_ENV) bash $(TOOLING)/scripts/wt.sh "$(NAME)" open

wt-headless: ## Create worktree off latest origin/main WITHOUT VS Code auto-launch (driven by background agents instead)
	$(need-name)
	$(WT_ENV) bash $(TOOLING)/scripts/wt.sh "$(NAME)" headless

wt-issue: ## Create worktree from the branch of GitHub issue N (linked branch / closing PR); HEADLESS=1 to skip VS Code
	@test -n "$(ISSUE)" || { echo "usage: make wt-issue ISSUE=<number> [HEADLESS=1]"; exit 1; }
	$(WT_ENV) bash $(TOOLING)/scripts/wt-issue.sh "$(ISSUE)" $(if $(filter-out 0,$(HEADLESS)),headless,open)

wt-list: ## List worktrees (branch, clean/dirty, path)
	@bash $(TOOLING)/scripts/wt-list.sh

wt-rm: ## Remove worktree dir + branch
	$(need-name)
	$(WT_ENV) bash $(TOOLING)/scripts/wt.sh "$(NAME)" rm

wt-rm-all: ## Remove ALL worktrees under .claude/worktrees/ (prompts to confirm)
	@read -r -p "Remove ALL .claude/worktrees/* worktrees and their branches? [y/N] " ans; \
	  if [ "$$ans" = "y" ] || [ "$$ans" = "Y" ]; then \
	    for w in $$(git worktree list --porcelain | awk '/^worktree /{print $$2}' | grep "/.claude/worktrees/" || true); do \
	      name="$${w#*/.claude/worktrees/}"; echo "[wt-rm-all] removing $$name"; $(WT_ENV) bash $(TOOLING)/scripts/wt.sh "$$name" rm || true; \
	    done; \
	    git worktree prune; echo "[wt-rm-all] done."; \
	  else echo "[wt-rm-all] aborted"; fi

# --- the workspace -----------------------------------------------------------
#
# Five repos make one product, so some work is one feature in three of them.
# These targets treat the sibling checkouts as one thing: `workspace.toml` in
# the tooling repo names them, and everything below reads that.
#
# The root is the parent of the MAIN checkout you run from — not of $(CURDIR),
# which inside a worktree is `.claude/worktrees/<name>`. Override with
# YEABOI_WORKSPACE when the repos live somewhere else.

workspace-setup: ## Clone every yeaboi repo side by side and provision each (idempotent)
	@$(WORKSPACE) setup

workspace-status: ## One screen: branch, working state and both pins, across every repo
	@$(WORKSPACE) status

# Printed rather than exported: make cannot change the shell that called it.
workspace-env: ## The cross-repo dev exports — use as: eval "$$(make workspace-env)"
	@$(WORKSPACE) env

wt-set: ## Cut worktree NAME in each of REPOS="yeaboi frontend" (HEADLESS=1 to skip the editor)
	$(need-name)
	@test -n "$(REPOS)" || { echo 'usage: make wt-set NAME=<slug> REPOS="yeaboi frontend"'; exit 1; }
	@$(WORKSPACE) wt-set "$(NAME)" --repos "$(REPOS)" $(if $(filter-out 0,$(HEADLESS)),--headless,)

wt-sets: ## Which worktree names exist in which repos (a name in several is a set)
	@$(WORKSPACE) wt-sets

wt-set-rm: ## Remove worktree NAME from every repo in the workspace that has it
	$(need-name)
	@$(WORKSPACE) wt-set-rm "$(NAME)"

# --- the tooling pin ---------------------------------------------------------

# `TOOLING = .` means the tooling repo including its own fragment: there is no
# pin to sync, only the target contract to check.
ifneq ($(TOOLING),.)

tooling-sync: ## Re-clone .tooling/ at the sha in .tooling-rev (no network when already there)
	@bash scripts/tooling-sync.sh

tooling-bump: ## Move .tooling-rev to the tip of the tooling repo's main and re-sync
	@bash scripts/tooling-sync.sh --bump

TOOLING_PIN_CHECK = bash scripts/tooling-sync.sh --check
else
tooling-sync tooling-bump:
	@echo "[tooling] this IS the tooling repo — nothing to pin"
TOOLING_PIN_CHECK = true
endif

# Three things about the probe below, each of which cost a debugging session.
#
# It calls plain `make`, never the $$(MAKE) variable: a recipe line naming that
# variable is *executed* even under --dry-run, so probing `ship-gate` — which
# depends on this target — would recurse without bound.
#
# It reads only the FIRST line of the dry run. --dry-run prints the recipe it
# would run, so probing a target that reaches this one feeds this recipe's own
# text back in; anything the comparison looks for must not be able to appear in
# what a recipe prints. Explanations therefore live out here, not on `@#` lines
# inside the recipe, and the match is anchored to one line.
#
# And it looks at that line rather than at the exit code, because a name that
# appears in .PHONY and nowhere else is "up to date" the moment it is asked for:
# it exits 0 and says so, and the hooks would call it and silently skip. LC_ALL=C
# keeps make's sentence in English on a translated system.
tooling-check: ## Assert the pin is honoured and this repo defines the shared contract's targets
	@$(TOOLING_PIN_CHECK)
	@missing=""; for t in $(TOOLING_REQUIRED_TARGETS); do \
	   out="$$(MAKEFLAGS= MAKELEVEL= LC_ALL=C make -n "$$t" 2>/dev/null | head -1)" || { missing="$$missing $$t"; continue; }; \
	   case "$$out" in ""|*"othing to be done"*) missing="$$missing $$t";; esac; \
	 done; \
	 if [ -n "$$missing" ]; then \
	   echo "[tooling] this repo does not define:$$missing"; \
	   echo "[tooling] the devkit plugin's commands and hooks call these on every repo — add them or drop them from TOOLING_REQUIRED_TARGETS with a reason."; \
	   exit 1; \
	 fi
	@echo "[tooling] ok — pin honoured, $(words $(TOOLING_REQUIRED_TARGETS)) shared target(s) present"

# --- vendored contracts ------------------------------------------------------
#
# A repo downstream of a contract (the front end of the wire enums, the desktop
# app of app_http.md) vendors a snapshot rather than importing across repos, and
# pins the sha it took it from in `.contracts-rev`. `contracts-check` fails when
# upstream has moved, which is the whole point: drift becomes a red check
# instead of a bug in production.
#
# Repos set CONTRACTS_REPO and CONTRACTS_PATHS; repos with no upstream contract
# leave them empty and both targets no-op.
CONTRACTS_REPO ?=
CONTRACTS_PATHS ?=
CONTRACTS_DIR ?= contracts

contracts-sync: ## Re-vendor $(CONTRACTS_PATHS) from the tip of $(CONTRACTS_REPO) and record the sha
	@test -n "$(CONTRACTS_REPO)" || { echo "[contracts] no upstream contract for this repo — nothing to sync"; exit 0; }
	@bash $(TOOLING)/scripts/contracts.sh sync "$(CONTRACTS_REPO)" "$(CONTRACTS_DIR)" $(CONTRACTS_PATHS)

contracts-check: ## Fail if the vendored contracts differ from the pinned sha, or the pin is behind upstream
	@test -n "$(CONTRACTS_REPO)" || exit 0
	@bash $(TOOLING)/scripts/contracts.sh check "$(CONTRACTS_REPO)" "$(CONTRACTS_DIR)" $(CONTRACTS_PATHS)
