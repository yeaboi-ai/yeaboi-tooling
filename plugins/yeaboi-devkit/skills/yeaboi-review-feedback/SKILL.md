---
name: yeaboi-review-feedback
description: Read and address Claude, Codex, and human feedback on a GitHub pull request. Use when asked to inspect or resolve PR review feedback.
---

Slash-command references such as `/sync-main` mean the corresponding `yeaboi-sync-main` skill in Codex.
Use the current assistant’s native tools; never require the other assistant to perform a shared procedure.


Read `AGENTS.md` and `.agents/repo-notes.md`. Resolve the PR from the supplied number or current branch.

Run `make review-feedback PR=<n>` and inspect the findings, including `advisory_items` when present.
For further context read `gh pr view <n> --json comments,reviews,statusCheckRollup` and the inline review
comments through `gh api repos/<owner>/<repo>/pulls/<n>/comments --paginate`.

Read feedback from both Claude and `chatgpt-codex-connector[bot]`, as well as humans. Native Codex
reviews do not emit Claude's verdict markers. Missing Codex output is not a clean review or a
reason to wait indefinitely. Codex findings are advisory initially; keep them visible separately.

When asked to address feedback, inspect each claim, fix defects and explain disagreements with
evidence. Verify changes through `make lint` and `make test-scoped`. Reply in the relevant thread
before resolving it. Do not claim a fix based only on a reply or dismiss a human's unresolved
thread because an AI reviewer passed. Respect the repo's push/rebase playbook and review caps.

Request a new native Codex review with `@codex review` only when the user asks for a review or
the requested feedback workflow requires re-review. Report CI, enforced feedback, and advisory
findings separately. Do not merge without authorization.
