---
name: yeaboi-review
description: Independently review a feature diff for correctness and fit to its stated intent before shipping.
---

Read `../../agents/code-reviewer.md` for the checklist. Review `git diff origin/main...HEAD`
and the task context. Stay read-only, report consequential findings with file and line references,
and distinguish blockers from should-fix findings and nits. Do not push or post comments.
