#!/usr/bin/env bash
# PostToolUse hook (Edit|Write|MultiEdit): auto-format the touched file so every
# edit lands pre-formatted and lint round-trips disappear.
#
# Receives the hook payload as JSON on stdin; extracts tool_input.file_path and
# picks the formatter from the extension — ruff for Python, the repo's own
# `npm run format:file` for TypeScript/JavaScript when it defines one.
#
# Best-effort by design: unknown extensions, missing files, and formatter errors
# all exit 0 — formatting must never block the session.

set -uo pipefail

file_path="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))' 2>/dev/null)"

[ -n "${file_path}" ] || exit 0
[ -f "${file_path}" ] || exit 0

format_python() {
  # Same uv fallback as the Makefile; plain ruff if uv is absent.
  local ruff
  if command -v uv >/dev/null 2>&1; then
    ruff="uv run ruff"
  elif [ -x "${HOME}/.local/bin/uv" ]; then
    ruff="${HOME}/.local/bin/uv run ruff"
  elif command -v ruff >/dev/null 2>&1; then
    ruff="ruff"
  else
    return 0
  fi
  ${ruff} format -q "${file_path}" 2>/dev/null || true
  ${ruff} check -q --fix "${file_path}" 2>/dev/null || true
}

format_node() {
  # Only when the repo opts in: a `format:file` script that takes one path.
  local dir
  dir="${CLAUDE_PROJECT_DIR:-$PWD}"
  [ -f "${dir}/package.json" ] || return 0
  grep -q '"format:file"' "${dir}/package.json" 2>/dev/null || return 0
  (cd "${dir}" && npm run --silent format:file -- "${file_path}") >/dev/null 2>&1 || true
}

case "${file_path}" in
  *.py) format_python ;;
  *.ts | *.tsx | *.js | *.jsx | *.mjs | *.cjs) format_node ;;
esac

exit 0
