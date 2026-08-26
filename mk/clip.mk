# mk/clip.mk — feature clips: a short recording of the one thing a PR changes.
#
# `demo` answers "what does this product look like" and lives at the repo root.
# A clip answers the question a reviewer actually has — "show me the thing this
# PR changes" — and lives in `.demo/clips/<slug>.py`, committed with the change.
#
# Same engine, same step vocabulary, same spec keys as `demo_spec.py`. Two
# differences, both in how it is driven:
#
#   --clip   relaxes the verify floor. A demo tours a surface and runs 6s+; a
#            clip shows one thing and can be over in three.
#   --root   anchors the spec's relative paths at the repo root. A demo spec
#            sits at the root already, a clip sits two directories down, and
#            `"cwd": "."` has to mean the same thing in both.
#
# Unlike mk/demo.mk these recipes are NOT guarded on a spec existing. That
# guard is there because the yeaboi repo keeps its own `demo` target; `clip`
# collides with nothing, so every repo gets it — including the one where most
# features land.
#
# `clip-replay` is the half that runs in CI. mk/demo.mk says recording never
# runs on a PR, and that bargain holds for *rendering*: it needs agg or ffmpeg
# and a second checkout to write into. Replay needs neither — it drives the
# steps and asserts they resolve — so the reasoning does not carry over.

UV ?= $(or $(shell command -v uv 2>/dev/null),$(HOME)/.local/bin/uv)

CLIP_DIR ?= .demo/clips
CLIP_OUT ?= .demo/out
CLIP_SPECS := $(wildcard $(CLIP_DIR)/*.py)
CLIPPER := $(UV) run --no-project --with pillow python $(TOOLING)/recorder/record.py --root .

.PHONY: clip clip-replay clip-list

clip: ## Record one feature clip: make clip SPEC=.demo/clips/<slug>.py
	@test -n "$(SPEC)" || { \
	   echo "[clip] SPEC= is required — e.g. make clip SPEC=$(CLIP_DIR)/my-feature.py"; \
	   echo "[clip] $(words $(CLIP_SPECS)) spec(s) committed; \`make clip-list\` shows them."; \
	   exit 2; }
	@test -f "$(SPEC)" || { echo "[clip] no such spec: $(SPEC)"; exit 2; }
	@mkdir -p $(CLIP_OUT)
	$(CLIPPER) --clip --spec $(SPEC) --gif $(CLIP_OUT)/$(basename $(notdir $(SPEC))).gif

clip-replay: ## Drive every committed clip spec and assert it resolves; render nothing
	@test -n "$(CLIP_SPECS)" || { echo "[clip] no clip specs in $(CLIP_DIR) — nothing to replay"; exit 0; }
	@for spec in $(CLIP_SPECS); do \
	   echo "[clip] replaying $$spec"; \
	   $(CLIPPER) --clip --replay --spec $$spec || exit 1; \
	 done
	@echo "[clip] ok — $(words $(CLIP_SPECS)) clip(s) replayed"

clip-list: ## List this repo's committed clip specs
	@test -n "$(CLIP_SPECS)" && printf '%s\n' $(CLIP_SPECS) || echo "[clip] none in $(CLIP_DIR)"
