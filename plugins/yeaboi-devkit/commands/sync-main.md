---
description: Rebase the current worktree branch on latest main and re-verify
---

Bring the current feature branch up to date with `origin/main`.

`make wt-new` / `make wt-one` already rebase a worktree onto `origin/main` when they can, and
abort the rebase when it conflicts — this command is where that gets finished, and the only place
the playbook below gets applied, because a dirty tree and a conflict are both judgement calls a
provisioning script must not make.

1. Run `git branch --show-current`. If on `main`, just run `git pull --ff-only` and stop.
2. `git fetch origin`. Report the drift: `git rev-list --count HEAD..origin/main`.
3. If the working tree is dirty, run `make stash` first and `make unstash` at the end. The stash
   stack is shared with every other worktree of this repo, so a bare `git stash pop` can take —
   and delete — somebody else's work; `make stash` tags the entry and `make unstash` restores this
   worktree's own by sha. A bare pop is blocked by the devkit's PreToolUse guard.
4. `git rebase origin/main` — **`origin/main`, never local `main`**, which in a worktree is routinely
   several commits behind and would rebase you onto a base that no longer exists upstream.
5. Resolve conflicts with the playbook below. `make unstash` if one was created, resolving the same way.
6. Re-verify on the new base: `make test-scoped` + `make lint`. If the rebase touched **any generated
   file**, run `make ship-gate` instead — a scoped test run cannot see a stale bundle, a stale
   fixture, or a package that lost a generated tree.
7. Report: how many commits the branch was behind, every conflict and how it was resolved, and the
   verification result.

## Conflict playbook

**Read `.claude/repo-notes.md` § Conflict playbook first if this repo has one.** It names this
repo's generated files and the resolution each one needs, and it beats every general rule below.

The rules that hold in every repo:

- **A generated file is rebuilt, never chosen.** For a bundle, a lockfile, a snapshot or a vendored
  contract that conflicts, *both* sides are stale. Taking either produces a tree that merges green
  and reds the next build. Get git out of the conflicted state however is convenient, then re-run the
  generator and commit what it wrote.
- **Never a `union` merge driver** on generated output — it interleaves two builds into something
  that is syntactically plausible and semantically garbage.
- **Name a side by what it is, never by `--ours`/`--theirs`.** Those two flags *invert* under rebase:
  `git rebase origin/main` replays your commits onto upstream, so `--ours` is `origin/main` and
  `--theirs` is your own work — the opposite of what they mean in a merge. "Take the upstream side"
  is unambiguous in both; "take theirs" is a coin flip.
- **A version bump or a prepend-only changelog** conflicts by construction between any two
  release-worthy PRs. Keep upstream's and drop yours; the release automation re-applies it.
- **Two-way-bound registries** (a capability row and the entry another file must carry for it) keep
  **both** sides, in **both** files. A resolution that keeps one side only reds the parity checks.
- **Anything else** is a genuine overlap — merge both intents and say in the report what you did and
  why.
