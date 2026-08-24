#!/usr/bin/env bash
# Stop hook: when a turn ends with uncommitted source changes, run the repo's
# `make lint` + `make test-scoped`. A failure exits 2, which feeds the output
# back to Claude so it fixes the problem before handing work off.
#
# The repo is reached only through Make targets, which is what lets one hook
# serve a Python monorepo, a Vite front end, an Electron app and a static site.
# A repo that does not define a target simply skips it.
#
# Deliberately same-session and deterministic-only (fast loop). Judgment review
# by an independent session happens at ship time (/ship) and in CI, not on every
# stop.
#
# `make test-scoped`, not the full lane: mk/common.mk defaults `test-scoped` to
# `test-fast`, and a repo with a scope selector narrows it further. CI still
# evaluates the PR's entire diff, so the narrowing is a speed choice and never a
# coverage one.

set -uo pipefail

cd "${1:-${CLAUDE_PROJECT_DIR:-$PWD}}" 2>/dev/null || exit 0

input="$(cat)"

# Claude is already continuing because this hook blocked once this turn. Don't
# block again — prevents infinite loops when the failure needs the user (e.g. a
# broken environment rather than the change itself).
if printf '%s' "${input}" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
  exit 0
fi

[ -f Makefile ] || exit 0

# Fast exit for conversational turns: only verify when source files are dirty.
# Override per repo by exporting YEABOI_VERIFY_PATTERN.
pattern="${YEABOI_VERIFY_PATTERN:-\.(py|ts|tsx|js|mjs|cjs)$}"
if ! git status --porcelain 2>/dev/null | grep -qE "${pattern}"; then
  exit 0
fi

run() {
  local target="$1" out
  # A repo that does not define the target skips it rather than failing every
  # turn — the devkit is shared by repos with different toolchains.
  make -n "${target}" >/dev/null 2>&1 || return 0
  if ! out="$(make "${target}" 2>&1)"; then
    {
      echo "Stop-hook verification failed: make ${target}. Fix before finishing:"
      printf '%s\n' "${out}" | tail -50
    } >&2
    exit 2
  fi
}

run lint
run test-scoped

exit 0
