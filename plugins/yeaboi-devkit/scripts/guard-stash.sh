#!/usr/bin/env bash
# PreToolUse hook (Bash): refuse the spellings of `git stash` that can take
# another worktree's work off the stack they share.
#
# Every worktree of a repo shares one .git and therefore ONE stash stack.
# `git stash pop` applies the top entry and deletes it — with several agents
# working at once that entry is routinely somebody else's, and the deletion is
# not recoverable from the stack. `stash@{N}` is the same bug with a number on
# it: the index shifts whenever any other worktree pushes or drops.
#
# Exit 2 blocks the call and returns stderr to Claude, which is what makes this
# a redirect rather than a warning. Silent in a single-checkout repo: the hazard
# does not exist there, and this plugin ships to repos that never use worktrees.

set -uo pipefail

command="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))' 2>/dev/null)" || exit 0
[ -n "${command}" ] || exit 0

case "${command}" in *"git stash"*) ;; *) exit 0 ;; esac

mutates() { printf '%s' "${command}" | grep -qE 'git[[:space:]]+stash[[:space:]]+(pop|apply|drop|clear|branch)\b'; }

# Read-only subcommands are always fine.
if ! mutates; then
  printf '%s' "${command}" | grep -qE 'git[[:space:]]+stash[[:space:]]+(list|show)\b' && exit 0
fi

# A tagged push is the safe spelling, and is what `make stash` runs.
if printf '%s' "${command}" | grep -qE 'git[[:space:]]+stash[[:space:]]+push\b' \
  && printf '%s' "${command}" | grep -qE '(-m|--message)\b' && ! mutates; then
  exit 0
fi

# `apply <sha>` is the safe restore: an explicit, stable object rather than a
# position that another worktree can shift under you.
if printf '%s' "${command}" | grep -qE 'git[[:space:]]+stash[[:space:]]+apply[[:space:]]+[0-9a-f]{7,40}\b'; then
  exit 0
fi

# One working tree means no shared stack, so nothing to protect.
[ "$(git worktree list 2>/dev/null | wc -l | tr -d ' ')" -gt 1 ] || exit 0

cat >&2 <<'MSG'
Blocked: this repo's worktrees share one .git, so they share ONE stash stack.
`git stash pop` applies whatever is on top — routinely another session's work —
and then deletes it. `stash@{N}` is the same problem: the index shifts whenever
any other worktree pushes or drops.

Use the wrappers. They tag each entry with the worktree that made it, list only
this worktree's, and restore with `apply` against a resolved sha, so a wrong
guess costs nothing:

    make stash
    make stash-list
    make unstash

Reaching for a specific entry on purpose is fine — resolve it to a sha first
(`git stash list --format='%H %gs'`) and `git stash apply <sha>`.
MSG
exit 2
