# yeaboi-tooling

The development workflow every yeaboi repo shares, in one place: the Claude Code commands and agents,
the hooks that verify a turn, the Make fragments, and the worktree scripts.

Five repos consume it — [`yeaboi`](https://github.com/yeaboi-ai/yeaboi.ai) (all the Python: engines,
TUI, CLI, MCP, Slack), `yeaboi-frontend`, `yeaboi-desktop`, `yeaboi-site`, and this one.

## The two halves

**A Claude Code plugin** (`plugins/yeaboi-devkit/`), installed from this repo as a marketplace.
Carries `/ship`, `/sync-main`, `/wt`, `/migrate`, the `code-reviewer` / `test-writer` / `migrator`
agents, the `repo-workflow` skill, and the PostToolUse + Stop hooks.

**A pinned clone** (`mk/`, `scripts/`, `bootstrap/`), consumed as a gitignored `.tooling/` checkout at
the sha in each repo's `.tooling-rev`. Carries the shared Make targets and the worktree lifecycle.

Two halves because they are installed by different things: Claude installs a plugin, `make` needs
files on disk.

## The one rule

**The plugin speaks to a repo only through Make targets.** That is what lets one `/ship` and one Stop
hook drive a Python monorepo, a Vite front end, an Electron app and a static site. A command that
reaches for `uv run` or a script path is a command that works in exactly one repo — `make
tooling-check` and this repo's own guards both refuse it.

The contract, and everything else about how the seams work, is in the `repo-workflow` skill
(`plugins/yeaboi-devkit/skills/repo-workflow/SKILL.md`). Read that before changing any of it.

## Adding a repo to the workflow

1. Copy `bootstrap/tooling-sync.sh` to the repo's `scripts/tooling-sync.sh`.
2. Paste `bootstrap/Makefile.head` at the top of its `Makefile`, and define `lint`, `test`,
   `test-fast`, `test-scoped`, `ship-gate` below it (a Node repo can `include $(TOOLING)/mk/node.mk`
   and get them).
3. Write `.tooling-rev` with a sha of this repo (`make tooling-bump` does it), and add `.tooling/`
   and `.claude/worktrees/` to `.gitignore`.
4. Add `extraKnownMarketplaces` + `enabledPlugins` to its `.claude/settings.json` — copy this repo's.
5. Add `scripts/provision.sh` (what a fresh worktree of it needs) and `.claude/repo-notes.md` (the
   facts `/ship` and `/sync-main` ask for).
6. Run `make tooling-check` and put it in the repo's CI.

## Working on this repo

```bash
make install       # uv sync
make test          # the guards
make lint          # ruff + shellcheck
make ship-gate     # everything, in the order /ship runs it
```

A change under `plugins/yeaboi-devkit/` changes the workflow in **every** yeaboi repo the moment it
bumps `.tooling-rev` — say in the PR body which repos need the bump.

## Not shared yet

Deliberate, and each has a reason worth keeping visible:

- **`/pr-feedback`, `/babysit-prs`, and the `pr-fixer` / `pr-responder` agents** stay in the `yeaboi`
  repo. They drive `scripts/pr_feedback.py`, which is stdlib-only and portable, but the workflow that
  runs it is a `pull_request_target` gate whose security argument is "the only thing executed is the
  script as it exists on `main`". Moving the script means rewriting that gate, and a broken required
  check blocks every PR in the repo with nothing in the UI saying why. It moves in its own PR.
- **`mk/static.mk`** — the site repo does not exist yet, and a fragment invented before its consumer
  is a fragment that rots.
- **Reusable `claude-review.yml` / `codeql.yml`** — same reason; they arrive with the repo that calls
  them, and org-level secrets with them.
