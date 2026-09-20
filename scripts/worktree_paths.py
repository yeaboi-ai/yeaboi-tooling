"""Resolve managed worktrees, including trees created before the neutral layout."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

LAYOUTS = (Path(".worktrees"), Path(".claude/worktrees"))


def target(root: Path, name: str) -> Path:
    if not name or name.startswith("-") or any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError(f"invalid worktree name: {name!r}")
    check = subprocess.run(["git", "-C", str(root), "check-ref-format", f"refs/heads/{name}"], capture_output=True)
    if check.returncode:
        raise ValueError(f"invalid worktree branch: {name!r}")
    candidates = [root / layout / name for layout in LAYOUTS]
    listing = subprocess.run(
        ["git", "-C", str(root), "worktree", "list", "--porcelain"], capture_output=True, text=True
    )
    registered = {line[9:] for line in listing.stdout.splitlines() if line.startswith("worktree ")}
    existing = [path for path in candidates if path.exists() or str(path) in registered]
    if len(existing) > 1:
        raise ValueError(f"ambiguous worktree {name!r}: exists in both layouts; resolve by explicit git worktree path")
    chosen = existing[0] if existing else candidates[0]
    home = root / next(layout for layout in LAYOUTS if root / layout in chosen.parents)
    if not chosen.resolve().is_relative_to(home.resolve()):
        raise ValueError(f"worktree path escapes its root: {chosen}")
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("name")
    args = parser.parse_args()
    try:
        print(target(args.root, args.name))
    except ValueError as exc:
        parser.exit(1, f"[wt] {exc}\n")


if __name__ == "__main__":
    main()
