---
description: Manage git worktrees for parallel development (new/list/rm/headless)
---

Worktree operations for parallel feature development. Arguments: $ARGUMENTS

Parse the arguments and run the matching Make target (never reimplement the scripts, and never call
them by path — they live in the pinned `.tooling/` clone and take the project from the environment):

- `list` (or no arguments) — run `make wt-list` and, for each worktree, also check
  `gh pr list --head <branch>` to note whether it has an open PR. Present a compact table: name,
  branch, clean/dirty, PR status.
- `new <name>` — run `make wt-new NAME=<name>` (fetches origin, branches `<name>` off latest
  `origin/main`, creates `.claude/worktrees/<name>`, copies `.env`, runs the repo's
  `scripts/provision.sh`, then opens VS Code with a claude session). If the branch already exists
  locally the script reuses it as-is; if it exists only on `origin` it is checked out tracking the
  remote branch (not re-cut from main). Either way it reports how far behind main it is — rebase it
  with `/sync-main` inside the worktree.
- `headless <name>` — run `make wt-headless NAME=<name>` (same provisioning, no VS Code window;
  prints the path). Use this when the feature will be driven by a background agent from this session
  instead of a human-attended window.
- `issue <number>` — run `make wt-issue ISSUE=<number>` (add `HEADLESS=1` when a background agent
  will drive it). Resolves the issue's branch via its linked branches (`gh issue develop --list`),
  falling back to the head branch of an open PR that closes the issue. If several branches match, it
  lists them — re-run as `new <branch>` with the one you want.
- `rm <name>` — first check the worktree is clean (`git -C .claude/worktrees/<name> status
  --porcelain` from the main checkout) and has no unmerged work; warn and ask before removing
  anything dirty. Then run `make wt-rm NAME=<name>`.

- `set <name> <repo> <repo>…` — run `make wt-set NAME=<name> REPOS="<repo> <repo>"` (add `HEADLESS=1`
  when background agents will drive them). Cuts the same-named worktree in each named repo, for a
  feature that spans several. Repos are named as `workspace.toml` names them — `yeaboi`, `frontend`,
  `desktop`, `site`, `tooling` — or by directory. Ship upstream first: the downstream PR is what
  carries the new pin.
- `sets` — run `make wt-sets`: which worktree names exist in which repos, across the workspace. A
  name in more than one repo is a set.
- `set rm <name>` — run `make wt-set-rm NAME=<name>`, after the same cleanliness check as `rm`, in
  every repo that has that worktree.

Worktrees live under `<main checkout>/.claude/worktrees/`, in every repo. If the current directory is
itself a worktree, the scripts already resolve the main checkout — just run the target from here.

A fresh worktree has no `.tooling/` (it is gitignored, which is exactly why the shared tooling is a
pinned clone and not a submodule — `git worktree add` does not populate submodules). The first `make`
in it clones the pin automatically; nothing to do by hand.

The workspace targets — `wt-set`, `wt-sets`, `wt-set-rm`, and `workspace-setup` / `workspace-status`
/ `workspace-env` — reach the sibling checkouts, so they need the repos side by side under one
directory. `make workspace-status` says which are missing; `make workspace-setup` clones and
provisions them.
