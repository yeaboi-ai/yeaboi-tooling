# Agent instructions — yeaboi-tooling

Read `.agents/repo-notes.md` for this repo's toolchain, verification gate, generated files,
release behavior, and conflict playbook. Use the Make interface for development and verification.

- Run `make lint` and `make test-scoped` for code changes; run `make ship-gate` before shipping.
- Keep work on a feature branch and in its own worktree. Never modify a sibling's work without a request.
- Shared tooling is owned by yeaboi-tooling; never edit a pinned `.tooling/` checkout.
- Preserve vendored contracts; change the producing repo and update the downstream pin.
- Use `make stash`, `make stash-list`, and `make unstash`: worktrees share a stash stack.
- Attribute AI assistance to the assistant that actually contributed; omit unknown model details.

## Shared assistant workflow

Run `make agent-setup` on a fresh checkout to expose the pinned shared skills, then
`make agent-check` to check discovery and CLI availability. Claude commands and Codex skills
read the same procedures. Codex uses `.agents/skills/`; Claude's existing commands remain available.
Start either CLI with `make agent AGENT=claude` or `make agent AGENT=codex`.
Use `TASK=yeaboi-ship` (or another installed skill) and `ARGS="task context"` to select a procedure;
`make agent-run` runs it non-interactively using the CLI's local login.

`make wt-new NAME=x` creates a workspace set and offers both editor launch tasks.
`AGENT=claude` or `AGENT=codex` auto-starts exactly one. `HEADLESS=1` opens no editor.
New worktrees use `<main>/.worktrees/<name>`; existing `.claude/worktrees/<name>` trees remain in place
and are supported by the same commands. `make wt-one` / `make wt-one-rm` affect only this repo;
`make wt-new` / `make wt-rm` affect the workspace set. Use `REPOS="..."` to narrow a set.

Codex hooks require project trust and a review in `/hooks`. They use the same formatting,
scoped verification, and stash guard as Claude. Do not bypass hook trust or sandbox permissions.
Use the installed CLI's own local authentication; this setup expects Codex's ChatGPT login.

## Code Review Rules

- Flag consequential correctness, security, and compatibility defects in changed code; leave mechanical checks to CI.
- Check worktree and repository boundaries: preserve existing work, isolate ports/data, and avoid operating on the main checkout by mistake.
- Preserve this repo's generated-file, contract, and release invariants in `.agents/repo-notes.md`.
- Configure Claude and native Codex GitHub reviews independently. Codex feedback is advisory initially;
  it must remain visible in feedback reports without being treated as a required completion signal.
