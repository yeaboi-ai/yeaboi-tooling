---
description: Record a short clip of the feature this branch adds and attach it to the PR
---

Record a feature clip: a short GIF of **the one thing this branch changes**, attached to the PR and
backed by a scripted walkthrough committed alongside the code.

Arguments (optional): $ARGUMENTS — a slug for the clip, or a sentence describing what to show. With
no arguments, work it out from the diff.

This is not `make demo`. That records the whole surface into the README and is a rare, deliberate
act. A clip is cheap, scoped to one feature, and optional — if the change is invisible to a user,
say so and stop rather than recording something to have recorded it.

**Read `.claude/repo-notes.md` first.** Its `## Clips` section carries the facts this command
deliberately does not hardcode: how to drive *this* repo's surface, which ports and seeded fixtures
exist, and the traps specific to it. The procedure is here; the facts are there.

1. **Work out what to show.** Diff against `origin/main`, never local `main` — it lags in worktrees
   and will hand you a diff full of other people's work:

   ```
   git diff origin/main...HEAD --stat
   ```

   Name the single user-visible behaviour the branch adds. If there isn't one — a refactor, a CI
   change, a dependency bump — say so and stop. A clip of a change nobody can see is noise on the
   PR and a replay job that can only ever break.

2. **Write the spec** at `.demo/clips/<slug>.py`. Same keys and same step vocabulary as the repo's
   `demo_spec.py`, which is the best available example — read it before writing a new one. Omit the
   `gif` key: `make clip` names the output from the spec's filename.

   Two rules, both load-bearing:

   - **Drive on `await` markers, never `pause`.** A marker waits for the screen to actually say
     something, which makes the take fast on a quick machine and correct on a slow one. A clip built
     on sleeps is a clip that flakes in CI — and CI replay is half of why the spec is committed.
     Use `pause` only to *hold* a screen that is already up, so a viewer can read it.
   - **Never put a `key` step immediately after Escape.** A lone `\x1b` is only Escape if no second
     byte follows within ~100ms, so a key sent straight after it is read as an escape sequence and
     the take silently goes somewhere else. Put an `await` between them.

   Keep it short — ten to twenty seconds. One feature, entered, used, and its result visible.

3. **Record it.**

   ```
   make clip SPEC=.demo/clips/<slug>.py
   ```

   The GIF lands in `.demo/out/` (gitignored — only the spec is committed). If verification fails,
   the message says which bound it missed; fix the spec rather than loosening the bound, unless the
   surface genuinely warrants it (a shell transcript really does have few colours).

   **Look at the result before attaching it.** Read the GIF, and check a middle frame and the last
   frame — a take that drove the wrong screen still verifies, because verification only proves a
   recording is *alive*, not that it shows the feature.

4. **Publish and attach.**

   ```
   python3 .tooling/scripts/clip_publish.py .demo/out/<slug>.gif --markdown
   ```

   That pushes the GIF to the repo's orphan `demo-media` branch and prints a `## Demo` section. If a
   PR exists, append it to the body with `gh pr edit`; keep any existing body and add the section at
   the end. If there is no PR yet, hand the markdown to `/ship`, which will include it.

   Re-recording the same slug on the same branch overwrites in place, so the image already in the PR
   updates rather than being orphaned.

5. **Commit the spec** with the change — `.demo/clips/<slug>.py` only, never `.demo/out/`. It is
   what makes the recording reproducible, reviewable as part of the diff, and replayable by CI long
   after the GIF was made.
