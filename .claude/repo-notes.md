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

## Unattended lane

None yet — every PR here is hand-shipped, so the `pr-feedback` review is advisory.
