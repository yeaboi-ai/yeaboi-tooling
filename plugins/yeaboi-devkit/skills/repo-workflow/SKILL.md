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
| `wt-new` `wt-open` `wt-headless` `wt-issue` `wt-list` `wt-rm` | Worktree lifecycle | `mk/common.mk` |
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
`wt.sh` copies `.env` from the main checkout and then runs the repo's own `scripts/provision.sh` —
that is the seam where a Python repo makes a venv and installs pre-commit, a Node repo runs `npm ci`,
and a static site does nothing at all.

The scripts resolve the project from `$PWD` (or `WT_REPO_DIR`), never from their own path: they live
inside `.tooling/`, which is a different git repository, and resolving from `$BASH_SOURCE` would cut
every worktree in the tooling repo. `mk/common.mk` passes `WT_REPO_DIR=$(CURDIR)` for that reason.
