"""Decide whether a PR should be nudged for a missing feature clip.

Writes `nudge=` and `surface=` to stdout in GITHUB_OUTPUT format. Never fails
the build: an undecidable case answers "no". A clip is optional, so the cost of
a false negative is nothing and the cost of a false positive is noise on
somebody's PR.

Globs are matched with `fnmatch`, where `*` crosses `/` — so `src/ui/*` covers
the whole subtree and there is no need for a `**` dialect.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
import sys

CLIP_DIR = ".demo/clips/"


def changed_files(base: str, head: str) -> list[str]:
    if not base or not head:
        return []
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def first_surface_hit(paths: list[str], globs: list[str]) -> str | None:
    for path in paths:
        for pattern in globs:
            if fnmatch.fnmatch(path, pattern):
                return path
    return None


def main() -> int:
    paths = changed_files(os.environ.get("BASE", ""), os.environ.get("HEAD", ""))
    globs = [g.strip() for g in os.environ.get("SURFACES", "").splitlines() if g.strip()]
    body = os.environ.get("BODY") or ""

    hit = first_surface_hit(paths, globs)
    attached = any(p.startswith(CLIP_DIR) and p.endswith(".py") for p in paths) or "## Demo" in body

    nudge = "yes" if hit and not attached else "no"
    print(f"nudge={nudge}")
    print(f"surface={hit or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
