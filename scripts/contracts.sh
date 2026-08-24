#!/usr/bin/env bash
# contracts.sh sync|check <repo-url> <dest-dir> <path>... — vendor a contract.
#
# A repo downstream of a contract keeps a copy of it rather than importing
# across repos, and pins the upstream sha it took the copy from in
# `.contracts-rev`. `check` re-materialises the contract at that sha and fails
# if the vendored copy differs — so an edited-in-place snapshot is a red check
# rather than a wire mismatch found in production.
#
# Being *behind* upstream is not drift: the pin is the point. `check` says so
# and stays green; the nightly cross-repo job is what escalates a stale pin.
#
# Reached through `make contracts-sync` / `make contracts-check`, which supply
# CONTRACTS_REPO, CONTRACTS_DIR and CONTRACTS_PATHS.

set -euo pipefail

MODE="${1:?usage: contracts.sh sync|check <repo-url> <dest-dir> <path>...}"
REPO="${2:?missing repo url}"
DEST="${3:?missing dest dir}"
shift 3
PATHS=("$@")
[ ${#PATHS[@]} -gt 0 ] || { echo "[contracts] no paths given" >&2; exit 1; }

PIN=".contracts-rev"

say() { echo "[contracts] $*" >&2; }
die() { say "$*"; exit 1; }

git_offline() { GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes}" git "$@"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Blobless partial clone: the contract is a handful of files in a repo that is
# not, and `check` runs on every PR.
git_offline clone --quiet --filter=blob:none --no-checkout "$REPO" "$WORK/src" \
  || die "cannot reach $REPO"

materialise() {  # <sha> -> $WORK/out/<paths>
  local rev="$1"
  rm -rf "$WORK/out"
  mkdir -p "$WORK/out"
  git -C "$WORK/src" cat-file -e "$rev^{commit}" 2>/dev/null \
    || die "$REPO has no commit $rev"
  local p
  for p in "${PATHS[@]}"; do
    git -C "$WORK/src" archive "$rev" -- "$p" 2>/dev/null | tar -x -C "$WORK/out" \
      || die "$REPO@${rev:0:12} has no path '$p'"
  done
}

case "$MODE" in
  sync)
    git_offline -C "$WORK/src" fetch --quiet origin main || die "cannot fetch main from $REPO"
    tip="$(git -C "$WORK/src" rev-parse origin/main)"
    materialise "$tip"
    for p in "${PATHS[@]}"; do
      mkdir -p "$DEST/$(dirname "$p")"
      rm -rf "${DEST:?}/$p"
      cp -R "$WORK/out/$p" "$DEST/$p"
    done
    printf '%s\n' "$tip" >"$PIN"
    say "vendored ${#PATHS[@]} path(s) from ${tip:0:12} into $DEST/ — commit them with $PIN"
    ;;
  check)
    [ -f "$PIN" ] || die "no $PIN — run: make contracts-sync"
    want="$(tr -d '[:space:]' <"$PIN")"
    materialise "$want"
    for p in "${PATHS[@]}"; do
      [ -e "$DEST/$p" ] || die "$DEST/$p is missing but $PIN pins it — run: make contracts-sync"
      if ! diff -ru "$WORK/out/$p" "$DEST/$p"; then
        die "$DEST/$p differs from $REPO@${want:0:12}. A vendored contract is a snapshot, never edited here — change it upstream and run: make contracts-sync"
      fi
    done
    if git_offline -C "$WORK/src" fetch --quiet origin main 2>/dev/null; then
      tip="$(git -C "$WORK/src" rev-parse origin/main)"
      if [ "$tip" != "$want" ]; then
        behind="$(git -C "$WORK/src" rev-list --count "$want..$tip" -- "${PATHS[@]}" 2>/dev/null || echo '?')"
        if [ "$behind" != "0" ]; then
          say "note: the pin is $behind commit(s) behind upstream on these paths — \`make contracts-sync\` when you want them"
        fi
      fi
    fi
    say "ok — ${#PATHS[@]} path(s) match $REPO@${want:0:12}"
    ;;
  *)
    die "mode must be 'sync' or 'check' (got '$MODE')"
    ;;
esac
