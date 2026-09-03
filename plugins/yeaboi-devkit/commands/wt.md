---
description: Manage git worktrees for parallel development (new/list/rm/headless)
---

Worktree operations for parallel feature development. Arguments: $ARGUMENTS

Parse the arguments and run the matching Make target (never reimplement the scripts, and never call
them by path — they live in the pinned `.tooling/` clone and take the project from the environment).

**Two altitudes.** `new` and `rm` act on the whole workspace: one feature is one branch of the same
name in every repo, opened as one multi-root editor window. `one`, `headless` and `issue` act on the
current repo alone. Reach for the single-repo ones when a background agent is driving the worktree,
or when the work genuinely lives in one repo.

- `list` (or no arguments) — run `make wt-list` and, for each worktree, also check
  `gh pr list --head <branch>` to note whether it has an open PR. Present a compact table: name,
  branch, clean/dirty, PR status. This repo only; `sets` is the cross-repo view.
- `new <name>` — run `make wt-new NAME=<name>`. Cuts `.claude/worktrees/<name>` in **every** repo in
  the workspace, in parallel (each fetches origin, branches `<name>` off latest `origin/main`, copies
  `.env`, runs that repo's `scripts/provision.sh`), then opens all of them as one VS Code window from
  a generated `<workspace>/.worktrees/<name>.code-workspace`, with a single claude session that has
  `--add-dir` access to every worktree. Add `REPOS="yeaboi frontend"` to narrow it — repos are named
  as `workspace.toml` names them (`yeaboi`, `frontend`, `desktop`, `site`, `tooling`) or by directory.
  Add `HEADLESS=1` when background agents will drive them instead of a human-attended window.
  A cut always means a **new** branch off `origin/main`: if `<name>` already exists, locally or on
  `origin`, that repo refuses rather than hand the worktree somebody else's base — which is how one
  feature name ends up on a different base in each repo. Add `REUSE=1` to continue existing branches
  instead; they are checked out (tracking `origin/<name>` when that is where they live) and rebased
  onto `origin/main`.
  **Re-running is the refresh.** `make wt-new NAME=<name>` a second time fetches and rebases every
  repo's worktree onto `origin/main`, so one command brings the whole set back onto the latest base.
  A worktree with uncommitted changes is left alone with a note (nothing is ever stashed), and a
  rebase that conflicts is aborted — the worktree stays usable on its old base and `/sync-main`
  inside it is where you resolve it. A repo that is not cloned is skipped with a note
  (`make workspace-setup` clones it).
  Ship upstream first: the downstream PR is what carries the new pin.
- `one <name>` — run `make wt-one NAME=<name>`: the same cut in **this repo only**, opening that one
  folder in its own VS Code window. What `new` used to mean.
- `headless <name>` — run `make wt-headless NAME=<name>`: this repo only, no editor window, prints
  the path. This is the one an orchestrating session uses when it is fanning background agents out
  over PRs or migration batches — one worktree per agent, not one per repo.
- `issue <number>` — run `make wt-issue ISSUE=<number>` (add `HEADLESS=1` when a background agent
  will drive it). This repo only. Resolves the issue's branch via its linked branches
  (`gh issue develop --list`), falling back to the head branch of an open PR that closes the issue.
  If several branches match, it lists them — re-run as `one <branch>` with the one you want.
- `rm <name>` — first check every worktree of that name is clean (`git -C <path> status --porcelain`,
  the paths from `make wt-sets`) and has no unmerged work; warn and ask before removing anything
  dirty. Then run `make wt-rm NAME=<name>`, which removes it from every repo that has it and deletes
  the `.code-workspace`. `REPOS="…"` narrows it; `make wt-one-rm NAME=<name>` is this repo alone.
  `<name>` is the path after `.claude/worktrees/`, slashes included (`desktop/feature`, never just
  `feature`) — take it from `make wt-sets` output or `${PWD#*/.claude/worktrees/}`, not from
  `basename`, which drops everything before the last slash and removes nothing.
- `sets` — run `make wt-sets`: which worktree names exist in which repos, across the workspace. A
  name in more than one repo is a set.

`wt-set` and `wt-set-rm` are aliases for `wt-new` and `wt-rm`, kept because they read better when you
are deliberately naming a few repos.

Worktrees live under `<main checkout>/.claude/worktrees/`, in every repo. If the current directory is
itself a worktree, the scripts already resolve the main checkout — just run the target from here.

A fresh worktree has no `.tooling/` (it is gitignored, which is exactly why the shared tooling is a
pinned clone and not a submodule — `git worktree add` does not populate submodules). The first `make`
in it clones the pin automatically; nothing to do by hand.

The workspace targets — `wt-new`, `wt-rm`, `wt-sets`, and `workspace-setup` / `workspace-status` /
`workspace-env` — reach the sibling checkouts, so they need the repos side by side under one
directory. `make workspace-status` says which are missing; `make workspace-setup` clones and
provisions them.
