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

# --- this worktree's port block ----------------------------------------------
# wt.sh writes .worktree.env into every worktree it cuts (scripts/wt_slots.py).
# Its lines are `export NAME=value`, which GNU make reads as an export directive
# and sh reads as an export — so the list of what gets exported lives in the
# generated file, not here, and `npm run dev` can source the same file.
#
# `-include` (leading dash) so the main checkout, which has no such file, parses
# in silence and keeps every downstream default. $(CURDIR) rather than a bare
# name so `make -C <repo>` reads that repo's block, not the caller's.
#
# Precedence: a command-line override still wins, so `make dev-board RETRO_PORT=5999`
# does what it says.
-include $(CURDIR)/.worktree.env

# This worktree's name, for anything that must not collide with a sibling.
WT_SELF = $(if $(YEABOI_WT_NAME),$(YEABOI_WT_NAME),$(notdir $(CURDIR)))

# Editor CLI used by every target that opens a window. Override for VS Code
# forks (e.g. `CODE=cursor make wt-new NAME=my-feature`).
CODE ?= code

# Which repos the workspace-wide wt-* targets touch. Empty means every repo in
# workspace.toml — the common case, and the reason `make wt-new NAME=x` needs no
# second argument. Narrow with REPOS="yeaboi frontend".
REPOS ?=

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

.PHONY: wt-repair stash stash-list unstash \
	wt-new wt-rm wt-set wt-set-rm wt-sets \
        wt-one wt-one-rm wt-open wt-headless wt-issue wt-list wt-rm-all \
        workspace-setup workspace-status workspace-env \
        tooling-sync tooling-bump tooling-check contracts-sync contracts-check

# --- worktrees ---------------------------------------------------------------
#
# Two altitudes, and which one a target is at is the whole design:
#
#   wt-new / wt-rm  act on the WHOLE workspace. One feature is one branch of the
#                   same name in every repo, opened as ONE multi-root VS Code
#                   window with one claude session that can see all of them.
#                   REPOS="yeaboi frontend" narrows them to a few.
#
#   wt-one / wt-open / wt-headless / wt-issue / wt-one-rm / wt-rm-all
#                   act on THIS repo only. wt-headless in particular must never
#                   widen: the plugin's unattended fan-out (/babysit-prs,
#                   /migrate) cuts one worktree per PR with it, and five per PR
#                   would be five branches nobody asked for.

# Guard NAME= for every wt-* target without duplicating the message.
define need-name
	@test -n "$(NAME)" || { echo "usage: make $@ NAME=<slug>  (e.g. NAME=standup-fix)"; exit 1; }
endef

# REUSE=1 is the opt-in that lets wt.sh continue an EXISTING branch (a teammate's,
# an issue's) instead of refusing it. Without it a cut always means a new branch
# off origin/main — which is what keeps one feature name on one base everywhere.
WT_REUSE = $(if $(filter-out 0,$(REUSE)),1,)

# The scripts live in the `.tooling` clone, which is its own git repository, so
# they take the project from the environment rather than from their own path.
WT_ENV = WT_REPO_DIR="$(CURDIR)" CODE="$(CODE)" WT_REUSE_BRANCH="$(WT_REUSE)"

# An unset REPOS must reach workspace.py as an ABSENT flag, not an empty string:
# absent is what means "every repo in workspace.toml".
WT_REPOS = $(if $(strip $(REPOS)),--repos "$(strip $(REPOS))",)
WT_HEADLESS = $(if $(filter-out 0,$(HEADLESS)),--headless,)
WT_REUSE_FLAG = $(if $(WT_REUSE),--reuse,)

# --- the workspace-wide pair (what you type) ---------------------------------

wt-new: ## Cut NAME off latest origin/main in EVERY repo (re-run to rebase them onto it) + one VS Code window; REPOS="…" narrows, HEADLESS=1 skips the editor, REUSE=1 continues existing branches
	$(need-name)
	@CODE="$(CODE)" $(WORKSPACE) wt-set "$(NAME)" $(WT_REPOS) $(WT_HEADLESS) $(WT_REUSE_FLAG)

wt-rm: ## Remove worktree NAME from every repo that has it, and its .code-workspace (REPOS="…" narrows)
	$(need-name)
	@$(WORKSPACE) wt-set-rm "$(NAME)" $(WT_REPOS)

# Kept because they read better when you are deliberately naming a few repos,
# and because everything written before wt-new widened says it this way.
wt-set: wt-new ## Alias for wt-new — the REPOS="…" spelling that predates it
wt-set-rm: wt-rm ## Alias for wt-rm

wt-sets: ## Which worktree names exist in which repos (a name in several is a set)
	@$(WORKSPACE) wt-sets

# --- the single-repo set (what scripts and agents call) ----------------------

wt-one: ## Create worktree in THIS repo only, off latest origin/main (REUSE=1 continues an existing branch, rebased), + open VS Code with claude auto-running
	$(need-name)
	$(WT_ENV) bash $(TOOLING)/scripts/wt.sh "$(NAME)" open

wt-open: ## Open THIS repo's worktree in a NEW VS Code window (creates it off latest origin/main first if needed)
	$(need-name)
	$(WT_ENV) bash $(TOOLING)/scripts/wt.sh "$(NAME)" open

wt-headless: ## Create worktree in THIS repo only WITHOUT VS Code auto-launch (driven by background agents instead; REUSE=1 continues an existing branch)
	$(need-name)
	$(WT_ENV) bash $(TOOLING)/scripts/wt.sh "$(NAME)" headless

wt-issue: ## Create worktree in THIS repo from the branch of GitHub issue N; HEADLESS=1 to skip VS Code
	@test -n "$(ISSUE)" || { echo "usage: make wt-issue ISSUE=<number> [HEADLESS=1]"; exit 1; }
	$(WT_ENV) bash $(TOOLING)/scripts/wt-issue.sh "$(ISSUE)" $(if $(filter-out 0,$(HEADLESS)),headless,open)

wt-repair: ## Give an EXISTING worktree its own ports + YEABOI_HOME (for trees cut before slots)
	$(need-name)
	$(WT_ENV) bash $(TOOLING)/scripts/wt.sh "$(NAME)" repair

wt-list: ## List THIS repo's worktrees (branch, clean/dirty, path)
	@bash $(TOOLING)/scripts/wt-list.sh

wt-one-rm: ## Remove THIS repo's worktree NAME (dir + branch)
	$(need-name)
	$(WT_ENV) bash $(TOOLING)/scripts/wt.sh "$(NAME)" rm

# --- the shared stash stack --------------------------------------------------
# Every worktree shares one .git, so they share one stash stack: a bare
# `git stash pop` in one session can restore — and then drop — work another
# session pushed. These tag each entry with the worktree that made it, never
# pop, and only ever touch this worktree's own entries.

STASH_TAG = wt:$(WT_SELF)

stash: ## Set this worktree's changes aside (tagged, on the stack every worktree shares)
	@git stash push -u -m "$(STASH_TAG): $$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
	  && echo "[stash] saved as '$(STASH_TAG)'. Restore with: make unstash"

stash-list: ## List only THIS worktree's stash entries
	@git stash list --format='%gd  %gs' | grep -F "$(STASH_TAG):" \
	  || echo "[stash] nothing stashed by '$(WT_SELF)'"

unstash: ## Restore this worktree's most recent stash entry (apply + drop, never pop)
	@sha=$$(git stash list --format='%H %gs' | grep -F "$(STASH_TAG):" | head -1 | cut -d' ' -f1); \
	  if [ -z "$$sha" ]; then echo "[stash] nothing stashed by '$(WT_SELF)'"; exit 1; fi; \
	  git stash apply "$$sha" || exit 1; \
	  ref=$$(git stash list --format='%gd %H' | grep " $$sha" | head -1 | cut -d' ' -f1); \
	  if [ -n "$$ref" ]; then git stash drop "$$ref" >/dev/null; fi; \
	  echo "[stash] restored and dropped '$(STASH_TAG)'"

wt-rm-all: ## Remove ALL worktrees under THIS repo's .claude/worktrees/ (prompts to confirm)
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

# wt-new / wt-rm / wt-sets are the other half of this — they reach the sibling
# checkouts through the same script, and live up in the worktree section because
# that is where you look for them.

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
