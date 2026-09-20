<div align="center">

<img src="https://yeaboi.ai/banner.jpg" alt="yeaboi.ai" width="800"/>

# 🤙 yeaboi-tooling

**The development workflow every yeaboi repo shares, in one place: the shared Claude Code and Codex procedures, the hooks that verify a turn, the Make fragments, and the worktree scripts.**

[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)
[![Part of yeaboi](https://img.shields.io/badge/part%20of-yeaboi-ff6600?style=for-the-badge)](https://github.com/yeaboi-ai/yeaboi.ai)

[![CI](https://img.shields.io/github/actions/workflow/status/yeaboi-ai/yeaboi-tooling/ci.yml?style=for-the-badge&label=CI&logo=github)](https://github.com/yeaboi-ai/yeaboi-tooling/actions)

</div>

---

<div align="center">
<img src="https://yeaboi.ai/demo-tooling.gif" alt="A terminal running make workspace-status, showing branch, working state and both pins across all six yeaboi repos, then make wt-list" width="800"/>

*Six checkouts, one command. `make demo` re-records this from `demo_spec.py`.*
</div>

---

## Claude Code and Codex

Both CLIs read the root `AGENTS.md` natively; repository details live in `.agents/repo-notes.md`.
Claude Code requires version 2.1.277 or later. Shared procedures have one implementation in the
devkit's skills. Claude's existing slash commands read those skills, and `make agent-setup` links
the pinned skills into Codex's
`.agents/skills` discovery path. Repo-specific skills are tracked in `.agents/skills`, with Claude
compatibility links. Never copy procedures into a second provider-specific implementation.

Claude defaults to `AGENTS.md` when there is no project or ancestor `CLAUDE.md` or
`CLAUDE.local.md`. If you keep personal project instructions in one of those files, select
`claude-md-and-agents-md` under `/config` → **Project instructions**. After upgrading Claude,
start a new session and check `/context` to confirm `AGENTS.md` loaded. See
[Claude's native AGENTS.md documentation](https://code.claude.com/docs/en/memory#agents-md)
for availability restrictions. Hosted workflow prompts explicitly read the shared file too.

```sh
make agent-setup                         # first checkout / after bumping the tooling pin
make agent-check                         # skill links, CLI availability, login/trust guidance
make wt-new NAME=feature-x               # one editor window; offers both launch tasks
make wt-new NAME=feature-x AGENT=codex    # auto-start only Codex
make wt-open NAME=feature-x AGENT=claude  # switch the launch choice on an existing tree
make agent AGENT=codex                   # use the current checkout
make agent AGENT=claude TASK=yeaboi-ship  # same shipping procedure
make review-feedback PR=123              # includes native Codex's advisory feedback
```

New trees live in `<main>/.worktrees/<name>`. Existing `.claude/worktrees/<name>` trees
stay where they are and work with the same lifecycle commands. Mixed sets are supported.
A name present in both layouts is ambiguous and must be resolved by explicit Git paths; scripts
never choose one to delete. Ports, private data homes, nested names and the tagged stash stack
remain shared contracts. `HEADLESS=1` creates trees without opening an editor or launching an AI.
Generated editor tasks preserve unrelated user tasks and start at most one selected assistant.

Codex uses its normal ChatGPT CLI login (`codex login`), with no API-key provisioning here.
Review project hooks with `/hooks` after trusting the project: formatting, scoped checks and
stash protection adapt to Codex's payloads and delegate to the existing shared scripts.
`make verify-changes` is the explicit lint + scoped-test fallback; `make ship-gate` remains authoritative.
Do not bypass the CLI sandbox or hook trust. Models remain a user preference.

### Reviews and hosted automation

- Claude reviews run after successful CI. The reusable workflow is consumed at the same tooling
  commit as the Make targets; yeaboi.ai retains its existing stricter feedback workflow.
- Enable native Codex automatic code review for all six repositories in
  [Codex code review settings](https://chatgpt.com/codex/cloud/settings/code-review), after connecting
  GitHub. Choose **On PR open**, keep exhaustive review off, and keep credit overage off. This uses
  the subscription and runs independently of CI; it does not share Claude's after-CI timing.
- Codex findings are advisory initially. No missing completion marker, reaction, or unavailable
  native review holds a merge. Human review and the existing unattended Claude gate remain intact.
- Each repo needs the Claude GitHub App and `CLAUDE_CODE_OAUTH_TOKEN` available to its review
  workflow. Secrets are configured in GitHub, never committed or copied out of a local login.
- Hosted writer bots stay on Claude. The `development-automation` skill in yeaboi.ai and desktop
  runs their existing procedures from either local CLI. For example:
  `make agent AGENT=codex TASK=development-automation ARGS="diagnose CI run 123"`.
  `make agent-run` is the corresponding non-interactive invocation, with the same eligibility
  and approval gates. It does not install a local scheduler or export credentials to CI.

Ship tooling first, then bump each consumer's `.tooling-rev` and reusable-workflow reference to
that commit. Run `make agent-setup` after the bump. Roll back by restoring both pins together;
legacy worktrees need no migration in either direction. Account-level native review settings are
an independent rollout step and can be disabled without changing required checks.

## What this is

Six repos consume it — [`yeaboi`](https://github.com/yeaboi-ai/yeaboi.ai) (all the Python: engines,
TUI, CLI, MCP, Slack), [`yeaboi-frontend`](https://github.com/yeaboi-ai/yeaboi-frontend),
[`yeaboi-desktop`](https://github.com/yeaboi-ai/yeaboi-desktop),
[`yeaboi-site`](https://github.com/yeaboi-ai/yeaboi-site),
[`yeaboi-sandbox`](https://github.com/yeaboi-ai/yeaboi-sandbox), and this one.

## The two halves

**A Claude Code plugin** (`plugins/yeaboi-devkit/`), installed from this repo as a marketplace.
Carries `/ship`, `/sync-main`, `/wt`, `/migrate`, the `code-reviewer` / `test-writer` / `migrator`
agents, the `repo-workflow` skill, and the PostToolUse + Stop hooks.

**A pinned clone** (`mk/`, `scripts/`, `bootstrap/`), consumed as a gitignored `.tooling/` checkout at
the sha in each repo's `.tooling-rev`. Carries the shared Make targets and the worktree lifecycle.

Claude installs the plugin adapter; `make` uses the pinned clone. Both read the shared
procedures in `plugins/yeaboi-devkit/skills/`, exposed to Codex by `make agent-setup`.

## The one rule

**The plugin speaks to a repo only through Make targets.** That is what lets one `/ship` and one Stop
hook drive a Python monorepo, a Vite front end, an Electron app and a static site. A command that
reaches for `uv run` or a script path is a command that works in exactly one repo — `make
tooling-check` and this repo's own guards both refuse it.

The contract, and everything else about how the seams work, is in the `repo-workflow` skill
(`plugins/yeaboi-devkit/skills/repo-workflow/SKILL.md`). Read that before changing any of it.

## The workspace

Six repos make one product, so `workspace.toml` names them and `scripts/workspace.py` treats the
sibling checkouts as one thing. The targets come from `mk/common.mk`, so they work from **any** repo
in the workspace, not only from this one:

```bash
make workspace-setup    # clone all six side by side and provision each (idempotent)
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

### One feature across every repo

One product, so one feature is one branch name everywhere. `wt-new` cuts it in every repo at once —
in parallel — and opens all of them as a single multi-root VS Code window with launch tasks
for Claude and Codex. Set `AGENT=claude` or `AGENT=codex` to start one automatically:

```bash
make wt-new NAME=poker-export                           # all six, one window
make wt-new NAME=poker-export REPOS="yeaboi frontend"   # narrow it to a few
make wt-new NAME=poker-export HEADLESS=1                # cut them, open no editor
make wt-new NAME=poker-export                           # again: rebase them all onto origin/main
make wt-sets                                            # what is cut where
make wt-rm NAME=poker-export                            # every repo that has it
make wt-rm-all                                          # every worktree there is (prompts; YES=1 skips)
```

Each repo branches `<name>` off freshly fetched `origin/main`, always as a **new** branch — an
existing one is refused rather than quietly handing that repo an older base (`REUSE=1` continues it
instead, rebased). Running the same command again is the refresh: every worktree in the set is
rebased onto `origin/main`. A dirty worktree is skipped and a conflicting rebase is aborted, each
with a note; `/sync-main` in that worktree is where you finish the job.

Run it from any repo in the workspace. The window's file lands in `<workspace>/.worktrees/` beside
the repos, because it names paths in all of them. `make wt-one NAME=…` is the single-repo cut when
you really do want one.

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
   and `.worktrees/` to `.gitignore`.
4. Add `extraKnownMarketplaces` + `enabledPlugins` to its `.claude/settings.json` — copy this repo's.
5. Add `scripts/provision.sh` (what a fresh worktree of it needs) and `.agents/repo-notes.md` (the
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

Recording never runs in CI. The output is committed and guarded, so the running-surface requirement
is paid by whoever changes the product, never by a PR. (Replaying a *clip* does run there — see
below. It drives the steps without rendering, so it needs neither `agg` nor `ffmpeg` nor a second
checkout, and the bargain above does not apply to it.)

## Feature clips

`demo` answers *what does this product look like*. A clip answers the question a reviewer actually
has — **show me the thing this PR changes** — and it is optional, per PR, and cheap.

```bash
make clip SPEC=.demo/clips/my-feature.py   # record one clip into .demo/out/ (gitignored)
make clip-replay                           # drive every committed spec, render nothing
make clip-list                             # what this repo has
```

Same engine and same step vocabulary as a demo. Two differences, both in how it is driven: `--clip`
lowers the verify floor (a demo tours a surface for six seconds or more; a clip can be over in
three), and `--root` anchors the spec's relative paths at the repo root, so `"cwd": "."` means the
same thing in a clip two directories down as it does in a root `demo_spec.py`.

Unlike `mk/demo.mk`, these targets are **not** guarded on a spec existing — that guard is there
because the yeaboi repo keeps its own `demo`, and `clip` collides with nothing. Every repo gets the
targets on its next pin bump, including the one where most features land.

Three pieces make a clip more than a picture:

- **The spec is committed**, at `.demo/clips/<slug>.py`. The walkthrough is reviewable as part of
  the diff, and re-recordable by anyone later.
- **CI replays it.** An `await` step already fails when its marker never renders, so replay is a
  working end-to-end test for free. A clip of a feature that has since broken stops replaying the
  day it breaks, instead of quietly becoming a lie.
- **The GIF is hosted per repo**, on an orphan `demo-media` branch at `clips/<branch>/<slug>.gif`.
  Every yeaboi repo is public, so `raw.githubusercontent.com` renders it inline in the PR — no CDN
  and no second PR to merge first. The branch shares no history with `main`, so a binary that
  changes on every re-record never weighs on a clone of the code. The path is keyed on the branch,
  not the PR number, so it works before the PR exists and updates in place after it does.

```bash
python3 .tooling/scripts/clip_publish.py .demo/out/my-feature.gif --markdown
```

`/record` does all of this — reads the diff, reads the repo's `## Clips` notes, writes the spec,
records, publishes and attaches. `/ship` points at it in its final report when a diff touches a
user-facing surface — the PR opens first, and the clip is attached to it afterwards.

A repo opts into the CI half by calling `clip-check.yml` from its own `ci.yml` with the globs that
mean "a user could see this". **Neither of its jobs may ever be a required check** — the nudge
always exits zero, and the whole point of a clip is that it is optional.

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
