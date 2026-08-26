# mk/demo.mk — the shared `demo` target contract.
#
# Every repo's README opens with a GIF of its own surface, and every one of
# those GIFs is reproducible: `make demo` re-records it from a spec committed
# in the repo it shows. Include this after mk/common.mk.
#
# A repo describes its demo in `demo_spec.py` at its root — which backend to
# use, what to drive, and what a sane result looks like. Two backends:
#
#   kind = "tty"    a pty session -> asciinema cast -> agg      (needs agg)
#   kind = "page"   Playwright frames -> ffmpeg                 (needs ffmpeg)
#
# Both write into the yeaboi-site checkout, which is where the site serves
# them from and where every README points. Neither runs in CI: the output is
# committed and guarded, so the two-checkout requirement is paid by whoever
# changes the product, never by a PR.
#
# Playwright lives in `.tooling/recorder/` and installs itself on first use,
# so no consuming repo gains a devDependency for it.

# A Node repo's Makefile never defines UV, and the recorder is Python either
# way — `--no-project` keeps it out of whatever venv (or none) the repo has.
UV ?= $(or $(shell command -v uv 2>/dev/null),$(HOME)/.local/bin/uv)

DEMO_SPEC ?= demo_spec.py
RECORDER := $(UV) run --no-project --with pillow python $(TOOLING)/recorder/record.py --spec $(DEMO_SPEC)

# Only claim the target names when this repo actually uses the shared recorder.
# The yeaboi repo has its own `demo`, driving a TUI-specific recorder that
# predates this one; without the guard, including this fragment overrode it and
# make printed "overriding commands for target `demo'" on every invocation.
# `demo` stays in TOOLING_REQUIRED_TARGETS either way — what the contract asks
# is that a repo can re-record its GIF, not that it does so from here.
ifneq ($(wildcard $(DEMO_SPEC)),)

.PHONY: demo demo-render demo-check

demo: ## Re-record this repo's README demo into the yeaboi-site checkout
	$(RECORDER)

demo-render: ## Re-render the demo GIF from the committed cast (terminal demos only)
	$(RECORDER) --render-only

demo-check: ## Verify the committed demo GIF without re-recording it
	$(RECORDER) --check-only

endif
