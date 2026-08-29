---
name: repo-workflow
description: How every yeaboi repo is wired to the shared tooling — the Make-target contract, the .tooling pin, vendored contracts, repo-notes.md, and worktree layout. Read when adding a repo, changing a Makefile's shared targets, bumping the pin, or wondering why a command calls `make` instead of a script.
---

# The shared repo workflow

Five repos — `yeaboi` (all the Python), `yeaboi-frontend`, `yeaboi-desktop`, `yeaboi-site`,
`yeaboi-tooling` — run one development workflow. This describes the seams that make that possible,
so a change to one of them is made deliberately rather than by copying a neighbour.

## The interface is Make, not scripts

Every command and hook in the `yeaboi-devkit` plugin reaches a repo **only** through Make targets.
That is the whole reason one `/ship` and one Stop hook can drive a Python monorepo, a Vite front end,
an Electron app and a static site.

| Target | What it must do | Provided by |
|---|---|---|
| `lint` | Lint, exit non-zero on a finding | the repo (or `mk/node.mk`) |
| `test-fast` | The unit lane | the repo (or `mk/node.mk`) |
| `test-scoped` | Only what the working tree touches; falling back to `test-fast` is fine | the repo |
| `test` | Everything a PR must pass locally | the repo |
| `ship-gate` | The full gate `/ship` runs — lint, format, tests, and whatever else CI checks | the repo |
| `wt-new` `wt-rm` `wt-sets` | Worktree lifecycle, across the whole workspace | `mk/common.mk` |
| `wt-one` `wt-open` `wt-headless` `wt-issue` `wt-list` `wt-one-rm` | The same, this repo alone | `mk/common.mk` |
| `tooling-sync` `tooling-bump` `tooling-check` | The pin | `mk/common.mk` |
| `contracts-sync` `contracts-check` | Vendored contracts (no-ops without an upstream) | `mk/common.mk` |

`make tooling-check` fails when a repo is missing one of the first five. A repo that genuinely has no
use for a target drops it from `TOOLING_REQUIRED_TARGETS` **with a reason in the Makefile**, so the
absence is a decision somebody made rather than a gap.

The Stop hook skips a target the repo does not define rather than failing every turn. That keeps a
new repo usable on day one — but it also means a *typo* in a target name is silent. `tooling-check`
is what catches that, and it belongs in every repo's CI.

## The `.tooling` pin

`mk/*.mk` and the worktree scripts live in `yeaboi-tooling` and are consumed as a **gitignored clone
at a pinned sha**:

- `.tooling-rev` — committed, one sha of the tooling repo.
- `scripts/tooling-sync.sh` — committed, copied verbatim from `bootstrap/tooling-sync.sh`.
- `.tooling/` — gitignored clone, created on demand.
- The six-line block from `bootstrap/Makefile.head` at the top of the repo's Makefile, which syncs at
  parse time **only when the pin and the checkout disagree**, then includes `mk/common.mk`.

Not a submodule, deliberately: `git worktree add` does not populate submodules, and this workflow
lives in worktrees. A fresh worktree provisions itself on its first `make`.

Bump with `make tooling-bump` and commit `.tooling-rev`. Never edit anything under `.tooling/` —
`make tooling-check` fails on a dirty pinned checkout, because a local fix there is invisible to
every other repo and disappears on the next sync.

## Vendored contracts

A repo downstream of a contract keeps a **copy** and pins the sha it came from in `.contracts-rev`,
rather than importing across repos. `make contracts-check` re-materialises the contract at that sha
and fails if the vendored copy differs — an edited-in-place snapshot becomes a red check instead of a
wire mismatch found in production.

Being *behind* upstream is not drift; the pin is the point. `contracts-check` reports it and stays
green.

Set `CONTRACTS_REPO` and `CONTRACTS_PATHS` in the repo's Makefile. Repos with no upstream contract
leave both empty and the targets no-op.

## The workspace

The five repos are meant to sit side by side under one directory, because some work is one feature in
three of them. `workspace.toml` in the tooling repo is the list; `scripts/workspace.py` reads it, and
`mk/common.mk` exposes it, so these run from **any** repo:

| Target | What it does |
|---|---|
| `workspace-setup` | Clone every repo side by side and run each one's `provision.sh`. Idempotent — an existing checkout is left exactly as it is |
| `workspace-status` | Branch, ahead/behind, working state, `.tooling-rev` and `.contracts-rev`, for all five. Local refs only, so it is instant |
| `workspace-env` | The cross-repo dev seams as shell exports: `eval "$(make workspace-env)"` |
| `wt-new` `wt-sets` `wt-rm` | One feature's worktree across every repo, as one editor window |

The root is the parent of the **main** checkout, not of `$(CURDIR)` — inside a worktree that would be
`.claude/worktrees/`. Override with `YEABOI_WORKSPACE`.

`workspace.py` imports nothing outside the standard library and nothing added after 3.9, including
`tomllib`: it has to run under whatever `python3` a machine already has, and macOS ships 3.9. That is
why the manifest reader is hand-rolled — and why `tests/test_workspace.py` holds it to `tomllib`'s
answer on the real file, and why it raises on any construct it does not cover rather than guessing.

### The dev seams

Three, all of them one checkout serving another instead of a published artifact:

- `YEABOI_WEB_STATIC` — the Python boards serve the front end's working build (`assets.py` checks it
  before the installed `yeaboi_web_assets`).
- `YEABOI_REPO` — the desktop shell's dev sidecar runs `yeaboi app` from a yeaboi working tree.
- `YEABOI_DESKTOP_PYTHON` — an explicit interpreter, skipping uv resolution on every launch.

Every one of those paths must exist: `assets.py` raises rather than falling back, and an absent
interpreter is a sidecar that never starts. `workspace-env` comments out a seam whose target is not
built and names the `make` that builds it.

### A feature that spans repos

`make wt-new NAME=x` cuts the same-named worktree in every repo, in parallel, and opens all of them
as one multi-root VS Code window (`<workspace>/.worktrees/x.code-workspace`) running a single claude
session with `--add-dir` over every worktree. `REPOS="yeaboi frontend"` narrows it; `HEADLESS=1`
skips the window; `make wt-one NAME=x` is the single-repo cut.

Running it again is the refresh: every repo's worktree is rebased onto freshly fetched `origin/main`,
so a set that has drifted is brought back with the command that cut it. Dirty worktrees are skipped
and conflicting rebases are aborted, both with a note — `/sync-main` in that worktree is the human
path.

Per-repo cuts inside a set go through `wt-headless`, never `wt-new` — `wt-new` is the set command, so
that would recurse, and `wt-headless` is the one worktree target every repo already has at whatever
`.tooling` pin it is on, so a set can be cut before the siblings bump. Headless also means wt.sh
writes no per-folder `.vscode/`, which is what keeps the window at one claude session rather than one
per root.

Nothing records the set — a recorded one goes stale the moment somebody removes a worktree by
hand, so `wt-sets` reads the directories instead.

**Ship upstream first.** The `yeaboi` PR merges; the downstream PR then carries the new
`.contracts-rev`. There is no way to land both halves at once, and the manifest-match and
`contracts-check` gates are red in between on purpose.

## The nightly cross-repo check

Every gate on a PR asks whether the change is green **against the pins it already has**. Nothing on a
PR can ask whether the repos are green against the contracts and packages **as they are now**,
because that answer changes when a different repo merges or publishes — a front end can ship a broken
package at noon and the desktop finds out at its next PR, a fortnight later.

`.github/workflows/nightly.yml` in the tooling repo asks it on a clock:

- For each repo with `vendors = true`: check it out, `make contracts-sync` from `yeaboi.ai@main`, and
  run **that repo's own `make ship-gate`**. The gate it trusts before shipping is the gate it should
  survive against fresh contracts, so there is no checklist maintained centrally to rot.
- For `yeaboi`: `uv lock --upgrade-package yeaboi-web-assets`, then the guards that read the
  *shipped* bundles. Without the upgrade it would re-test the version yeaboi's own CI already tested.

A red run opens one issue and comments on it thereafter. Fix it in the repo the run names — the
nightly is not the thing that is wrong.

## `.claude/repo-notes.md`

The shared commands carry the *procedure*; the repo carries its *facts*. `/ship` and `/sync-main`
both read `.claude/repo-notes.md` when it exists. It is the one place a repo says:

- **Commit** — which pre-commit hook `/ship` step 2 skips, and the `Co-Authored-By` trailer.
- **Gate** — what `make ship-gate` covers beyond the tests, and any registry a new capability must be
  added to.
- **After the push** — anything CI does to the branch (a version-bump commit, a generated-file
  commit) that makes a later force-push destructive.
- **Conflict playbook** — this repo's generated files and the resolution each one needs. It overrides
  the general rules in `/sync-main`.
- **Unattended lane** — the branch prefixes and labels on which the `pr-feedback` gate enforces
  rather than advises.

Keep it short. Anything longer than a page is a skill, not a note.

## Worktrees

`<main checkout>/.claude/worktrees/<name>` in every repo, cut from freshly fetched `origin/main`.
Always a **new** branch: an existing `<name>`, local or on `origin`, is refused unless `REUSE=1` says
to continue it, and a reused branch is rebased onto `origin/main` on the way in. `wt.sh` copies
`.env` from the main checkout and then runs the repo's own `scripts/provision.sh` — that is the seam
where a Python repo makes a venv and installs pre-commit, a Node repo runs `npm ci`, and a static
site does nothing at all. Re-running on an existing worktree only moves the base: it rebases, and
never re-provisions or rewrites `.env`.

The scripts resolve the project from `$PWD` (or `WT_REPO_DIR`), never from their own path: they live
inside `.tooling/`, which is a different git repository, and resolving from `$BASH_SOURCE` would cut
every worktree in the tooling repo. `mk/common.mk` passes `WT_REPO_DIR=$(CURDIR)` for that reason.
