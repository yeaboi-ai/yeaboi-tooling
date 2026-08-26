# repo-notes — yeaboi-tooling

The facts `/ship` and `/sync-main` do not hardcode. Keep this short; anything longer than a page is
a skill, not a note.

## Commit

No pre-commit hooks here — commit normally. Trailer:

```
Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

## Gate

`make ship-gate` = `lint` (ruff + shellcheck) → `format-check` → `test` → `tooling-check`.

`shellcheck` is skipped with a printed note when it is not on PATH; CI has it, so a local skip is a
convenience and never a coverage decision. If you changed a shell script and cannot run it locally,
say so in the PR.

Changing anything under `plugins/yeaboi-devkit/` changes the workflow in **every** yeaboi repo at the
moment they bump `.tooling-rev`. Say in the PR body which repos need a bump.

## After the push

Nothing rewrites the branch. A later push is a plain `git push`.

## Conflict playbook

Nothing here is generated, so the general rules in `/sync-main` are the whole story.

## Clips

A clip here is a **shell session**, not a TUI — the same shape as this repo's `demo_spec.py`, which
is the example to copy.

- `kind: "tty"`, `cmd: ["bash", "--noprofile", "--norc"]`, 100 cols.
- `require_alt_screen: False`. A shell never enters the alternate screen buffer, so the default
  would fail every take, and truncating on its exit would end the cast immediately.
- Pin the prompt in `env` (`PS1="$ "`), and set `BASH_SILENCE_DEPRECATION_WARNING=1` — macOS ships
  bash 3.2 and its three-line "use zsh" notice is otherwise the first thing in frame.
- Type commands character by character (the `_type` helper). A shell echoes each character back, and
  that echo is what puts motion in the cast; writing a line at once emits one event, which `agg`
  renders as a single static frame.
- Lower the colour floor: `"verify": {"min_distinct_colors": 8}`. A shell transcript is mostly one
  foreground colour on one background, and the TUI-tuned default of 64 rejects a good take.
- **Never run `make clip-replay` inside a clip.** It replays every spec in `.demo/clips/`, including
  the one being recorded, which does not terminate.

Every command in a clip must be read-only — a take gets re-run against a real checkout.

## Unattended lane

None yet — every PR here is hand-shipped, so the `pr-feedback` review is advisory.
