<div align="center">

<img src="https://yeaboi.ai/banner.jpg" alt="yeaboi.ai" width="800"/>

# 🤙 yeaboi-tooling

**The development workflow every yeaboi repo shares, in one place: the Claude Code commands and agents, the hooks that verify a turn, the Make fragments, and the worktree scripts.**

[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)
[![Part of yeaboi](https://img.shields.io/badge/part%20of-yeaboi-ff6600?style=for-the-badge)](https://github.com/yeaboi-ai/yeaboi.ai)

[![CI](https://img.shields.io/github/actions/workflow/status/yeaboi-ai/yeaboi-tooling/ci.yml?style=for-the-badge&label=CI&logo=github)](https://github.com/yeaboi-ai/yeaboi-tooling/actions)

</div>

---

<div align="center">
<img src="https://yeaboi.ai/demo-tooling.gif" alt="A terminal running make workspace-status, showing branch, working state and both pins across all five yeaboi repos, then make wt-list" width="800"/>

*Five checkouts, one command. `make demo` re-records this from `demo_spec.py`.*
</div>

---

## What this is

Five repos consume it — [`yeaboi`](https://github.com/yeaboi-ai/yeaboi.ai) (all the Python: engines,
TUI, CLI, MCP, Slack), [`yeaboi-frontend`](https://github.com/yeaboi-ai/yeaboi-frontend),
[`yeaboi-desktop`](https://github.com/yeaboi-ai/yeaboi-desktop),
[`yeaboi-site`](https://github.com/yeaboi-ai/yeaboi-site), and this one.

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

## The workspace

Five repos make one product, so `workspace.toml` names them and `scripts/workspace.py` treats the
sibling checkouts as one thing. The targets come from `mk/common.mk`, so they work from **any** repo
in the workspace, not only from this one:

```bash
make workspace-setup    # clone all five side by side and provision each (idempotent)
make workspace-status   # branch, working state and both pins, across every repo
eval "$(make workspace-env)"   # wire one checkout to another (see below)
```

The root is the parent of the main checkout you run from — override with `YEABOI_WORKSPACE`.

### The three dev seams

Each is one checkout serving another instead of a published artifact, and `make workspace-env`
prints all three as exports. A seam whose target is not built yet comes out commented, saying which
`make` builds it — every one of these paths must exist, because `assets.py` raises rather than
falling back and an absent interpreter is a sidecar that never starts.

| Export | Lets you |
|---|---|
| `YEABOI_WEB_STATIC` | serve the front end's working build from the Python boards, without publishing a wheel |
| `YEABOI_REPO` | run the desktop shell against a yeaboi working tree instead of the bundled runtime |
| `YEABOI_DESKTOP_PYTHON` | skip uv resolution on every desktop launch |

### One feature across several repos

```bash
make wt-set NAME=poker-export REPOS="yeaboi frontend"   # same-named worktree in each
make wt-sets                                            # what is cut where
make wt-set-rm NAME=poker-export
```

Nothing records a "set": a recorded one goes stale the moment somebody removes a worktree by hand,
and the truth is a directory listing. **Ship upstream first** — the `yeaboi` PR merges, then the
downstream PR carries the new `.contracts-rev`.

## The nightly cross-repo check

Every other gate in the fleet asks "is this change green against the pins I already have?". Nothing
asks "would these repos still be green against the contracts and packages as they are *now*" — and
no PR can, because the answer changes when a **different** repo merges or publishes.

`.github/workflows/nightly.yml` asks it on a clock: for every repo that vendors a contract, it
re-vendors from `yeaboi.ai@main` and runs **that repo's own `make ship-gate`**; and it re-tests
`yeaboi`'s shipped-bundle guards against the newest published `yeaboi-web-assets` rather than the
locked one. A failure files one issue here and comments on it thereafter.

The matrix comes from `workspace.toml`. A hard-coded list would be a sixth place to remember a repo
exists.

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
7. Add a `[[repo]]` row to `workspace.toml` — that is what puts it in `make workspace-setup`,
   and (with `vendors = true`) in the nightly cross-repo check.
8. Write a `demo_spec.py` describing the GIF its README opens with — `make demo` is part of the
   required contract, so `tooling-check` fails until it has one. See *The demo recorder* below.

## The demo recorder

Every repo's README opens with a GIF of its own surface, and every one of those GIFs is
reproducible: `make demo` re-records it from a `demo_spec.py` committed in the repo it shows.
`demo` is in `TOOLING_REQUIRED_TARGETS`, and `mk/demo.mk` is included from `mk/common.mk`, so a
repo satisfies the contract by supplying a spec and nothing else.

One step vocabulary, two capture backends, one verifier:

| `kind` | pipeline | needs |
|---|---|---|
| `"tty"` | a pty session → asciinema cast → `agg` | `brew install agg` |
| `"page"` | CDP screencast → `ffmpeg` | `brew install ffmpeg` |

The page backend drives Playwright, which also launches Electron — the desktop renderer throws
`preload bridge missing` outside the shell, so it cannot be filmed by pointing a browser at its dev
server. Playwright installs into `.tooling/recorder/` on first use, so **no consuming repo gains a
devDependency**, and Electron comes from the repo that already has it.

Frames come from `Page.startScreencast`, not a `page.screenshot()` loop. A screenshot of a full-size
page costs more than a frame interval, so a loop either blocks or drops frames — and dropping them
rescales the whole timeline, which turned a 13-second take into a 2.8-second one. The screencast is
push-based and carries a timestamp per frame, so an ffmpeg concat list reproduces the original
timing exactly.

```bash
make demo          # record, render, verify
make demo-render   # re-render from the committed cast — terminal demos only
make demo-check    # verify what is committed, without re-recording
```

Terminal demos commit a `.cast.gz` and re-render offline. Page demos commit only the GIF, because
keeping every frame would add hundreds of megabytes to the site repo — re-rendering one means
re-recording it, which needs its surface running. All of them are written into a **yeaboi-site**
checkout, which is where the site serves them from and where every README points.

Nothing here runs in CI. The output is committed and guarded, so the running-surface requirement is
paid by whoever changes the product, never by a PR.

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

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
