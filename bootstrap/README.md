# bootstrap/

The two files a repo **copies** in order to reach the shared tooling. Everything else it gets by
reference, from the `.tooling/` clone these create.

| File | Copied to | Purpose |
|---|---|---|
| `tooling-sync.sh` | `<repo>/scripts/tooling-sync.sh` | Clone/checkout `.tooling/` at the sha in `.tooling-rev`; `--bump` moves the pin, `--check` asserts it |
| `Makefile.head` | the top of `<repo>/Makefile` | Sync at parse time when the pin and the checkout disagree, then `include $(TOOLING)/mk/common.mk` |

Copied rather than included because of the chicken and egg: a repo cannot include a file from a clone
it has not made yet. `make tooling-check` diffs the repo's copy of `tooling-sync.sh` against this one
and fails on drift, so the one file that can rot silently does not.

`.tooling/` is gitignored and pinned, **not a submodule**: `git worktree add` does not populate
submodules, and this workflow lives in worktrees. A fresh worktree provisions itself on its first
`make`, with no network in the steady state — the sync runs only when `.tooling-rev` and the stamp in
`.tooling/.git/tooling-rev` disagree.
