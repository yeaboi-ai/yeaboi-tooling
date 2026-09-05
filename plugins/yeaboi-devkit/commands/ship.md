---
description: Ship the current feature branch — review, full gate, commit, push, PR
---

Ship the current feature branch. Arguments (optional): $ARGUMENTS — may include `auto-merge` to
enable auto-merge for low-risk changes (docs/chores/small fixes only).

**This procedure asks the user nothing of its own.** Whatever it learns along the way that the user
might act on — a sibling worktree still carrying work, a change worth a clip — is reported in step
10, after the PR exists, as an advisory. It never becomes a question in front of the push.

The contract this branch must satisfy: tests for every change, lint clean, security scan clean, and
whatever else this repo's gate covers — `make ship-gate` is the single command that decides. The
steps below are how it is executed interactively.

**Read `.claude/repo-notes.md` before you start, if this repo has one.** It carries the facts this
procedure deliberately does not hardcode: which pre-commit hooks to skip at step 2, what the gate
covers beyond the tests, and what happens to the branch after the push at step 7. Everything else
here is the same in every yeaboi repo.

**Two things about the order, because both were bugs.** The branch is **committed and rebased onto
`origin/main` before anything is verified**: a gate run on a stale base proves something about a tree
that will never exist, and `/ship` used to never fetch at all. And the **review runs in the
background alongside the test gate**, not in front of it — they are independent, and running them in
series put the reviewer's whole wall clock on the critical path for no benefit.

Follow these steps in order. If any step fails, stop, report what failed, and fix it before
continuing. Never skip the verification steps.

---

1. **Sanity.** Run `git branch --show-current`. If on `main`, stop: create a feature branch first.
   Then `git fetch origin` (you need it in step 3 and it costs nothing here).

   This ships **this repo's worktree only**. Other repos may carry a same-named worktree — `make
   wt-new` cuts a feature in every repo — and their work is theirs to ship, from their own `/ship`.
   Nothing here looks at them until the PR is open (step 10), and nothing here ever asks whether to
   ship them.

2. **Commit.** Stage the relevant changes and commit with a lowercase imperative message (e.g. "add
   streaming output"), ending with the repo's `Co-Authored-By` trailer.

   **Skip the pre-commit hook that re-runs the tests**, if this repo has one — `.claude/repo-notes.md`
   names it (e.g. `SKIP=unit-tests git commit …`). The Stop hook already ran the scoped tests at the
   end of the last turn and step 5's gate is about to run them in full. Three runs of the same tests
   is how a gate becomes one people pass with `--no-verify`. Secret scanning and formatting hooks
   still run — those catch something the gate does not.

   Committing here, rather than after the review, is what makes steps 3 and 4 possible at all: you
   cannot rebase a dirty tree, and a diff taken before the commit does not contain the work.

3. **Rebase onto `origin/main`.** `git rebase origin/main`. Resolve conflicts with the playbook in
   `/sync-main` — read it rather than improvising, because "take the other side" is the wrong answer
   for every generated file and produces a tree that merges green and reds CI.

   If the branch was pushed before, the later push needs `--force-with-lease`.

4. **Independent verification (fresh context, no author bias) — IN THE BACKGROUND.** Spawn the
   `code-reviewer` subagent. Give it ONLY: (a) the output of **`git diff origin/main...HEAD`**, and
   (b) a one-paragraph description of what this branch was supposed to do — NOT this conversation's
   history. Its checklist (spec fit, conventions, correctness) lives in the agent definition.

   **`origin/main`, never the local `main` ref.** Local `main` in a worktree is routinely several
   commits behind, and a three-dot diff taken against it hands the reviewer other people's
   already-merged PRs and none of this branch's work. That has happened, silently, and a review of
   the wrong diff reports clean. The devkit's own test suite fails if any command or agent file here
   names the local ref again.

   Do not wait for it. Move straight to step 5 and collect its findings in step 6.

5. **Full test gate — in the foreground, while step 4 runs.** One command:

   ```
   make ship-gate
   ```

   Whatever that expands to in this repo is the gate: it is defined once, in the repo's Makefile, so
   the local run and CI cannot drift apart by hand-copying a list of steps into this file. If it
   fails, fix the cause — never narrow the target.

6. **Resolve the review.** Collect the `code-reviewer` findings. Fix every finding at `blocker` or
   `should-fix` severity, or explain in the PR body why it is intentionally not addressed.

   Re-verify the fixes with `make test-scoped` + `make lint` — **not** the whole gate again. The gate
   in step 5 already covered the branch; this is checking a small delta on top of it.

7. **Last mile, then push + PR.** `main` moves during a ship. Before pushing:

   ```
   git fetch origin && git rev-list --count HEAD..origin/main
   ```

   If that is not `0`, rebase again (step 3's playbook) and re-run `make test-scoped`. Then
   `git push -u origin <branch>` and `gh pr create` against `main` with:
   - Title: same style as the commit message.
   - Body: a Summary section (what and why), a Test plan section (what was run), and the standard
     "🤖 Generated with Claude Code" footer.
   - **No `## Demo` section yet.** A clip is attached *after* the PR exists: `/record` appends the
     section with `gh pr edit`. Do not offer it here — step 10 points at it if the change is worth
     seeing.

   **Some repos rewrite the branch a minute after the push** — a version-bump commit pushed onto the
   PR branch by CI, for instance. Where that is true, `.claude/repo-notes.md` says so and says what
   it touches; any later push from this worktree must then `git pull --rebase` first and must
   **never** force-push over that commit.

8. **Auto-merge (only if `auto-merge` was passed)** — three conditions, all of them:
   - the change is genuinely low-risk (docs, chore, small fix; no core logic, schema, or workflow
     changes), and
   - `gh pr view --json mergeStateStatus` is not `BEHIND`, and
   - CI has not been superseded by a newer `origin/main` since step 7.

   Then `gh pr merge --auto --squash`. If any condition fails, say so and skip this step.

   The middle condition is not ceremony: a ruleset that does not require a branch to be up to date
   before merging means `--auto` on a branch that has fallen behind merges a tree CI never built.

9. **Hand off the review loop** — say plainly that the PR is **not done yet**, and why: the
   post-CI review workflow fires *after* CI succeeds, which is minutes from now, so at this moment
   its review does not exist. The `code-reviewer` pass in step 4 is not it — that one had no CI
   results, no diff-on-`main` context, and nobody else's eyes.

   Name the follow-up: `/pr-feedback <n>` once CI is green, or `/babysit-prs` across every open PR.
   Do not wait for it here; a `/ship` that blocks for ten minutes gets run less often.

   **On a branch you are shipping by hand, that review is advisory and the `pr-feedback` status stays
   green.** It runs once, posts what it found, and does not hold the merge — you are the person it
   would otherwise be arguing with. Read it anyway; that is the whole point of it existing. The gate
   enforces on the unattended lane, whose branch prefixes and labels `.claude/repo-notes.md` names,
   where nobody is on the other end. **A human reviewer's unresolved thread, or a `Request changes`
   review, still holds the check here** — that one has somebody waiting by construction.

   So step 8 does need the judgement it asks for: `gh pr merge --auto` waits on the required checks,
   and on a hand-shipped branch `pr-feedback` will be green whatever the review says. An auto-merge
   can outrun the review here — which is why step 8 is limited to changes that are genuinely
   low-risk.

10. **Report** — output the PR URL and a one-line status, ending with what is still outstanding: the
    pending review. If step 3 or step 7 rebased, say how far behind the branch had fallen and what
    conflicted.

    Then the **advisories**: things the user may want to act on next, stated as facts. **Not
    questions, not offers, and never a reason to undo or hold anything above.** The PR is open; these
    are what to do after it.

    - **The rest of the set.** Derive `<name>` from the worktree path: it is **everything after
      `.claude/worktrees/`** in `pwd` — `name="${PWD#*/.claude/worktrees/}"`. A nested name like
      `desktop/feature` must keep its slash: `basename` would say `feature`, and `make wt-siblings
      NAME=feature` then prints "no repo has a worktree named 'feature'" and exits 0 — a false
      all-clear that hides the siblings. Then:

      ```
      make wt-siblings NAME=<name>
      ```

      **A non-zero exit here is information, not a failed step** — the "if any step fails, stop"
      rule does not apply to it. It exits 1 when another repo's worktree still carries commits or
      uncommitted files. For each such repo, one line: the repo, what it owes, and that it ships
      from its own worktree with its own `/ship`. Add the ordering hint when a vendored contract is
      involved: the repo that *generates* the contract merges first, and until it does the
      `contracts-check` / manifest-match gates on the downstream PR stay red on purpose. Do not
      offer to ship, stash, commit or otherwise touch a sibling's work — it is not this PR's.

      This scan exists because a feature once shipped from the Python repo while its desktop half
      sat unmerged in the sibling worktree; the vendored manifest that landed described an app
      nobody could find, and was "corrected" to match the older desktop before anyone thought to
      look for a worktree of the same name. One line in the report would have shown it.

    - **A clip.** If the diff touches a user-facing surface, one line: this changes what a user
      sees, and `/record` will script a short clip and attach it to PR #<n>. If the change is
      invisible — a refactor, a CI change, a dependency bump — say nothing. Where the repo runs
      `clip-check.yml`, CI posts the same nudge on the PR; this line just gets there first.

---

Review feedback is not answered here, for the plain reason that it does not exist yet — `/ship` opens
the PR, and answering what comes back is a separate sitting (`/pr-feedback`).
