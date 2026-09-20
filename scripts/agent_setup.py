"""Link the pinned shared skills into the repository's standard discovery path."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def setup(root: Path, tooling: Path, check: bool = False) -> None:
    source = tooling.resolve() / "plugins" / "yeaboi-devkit" / "skills"
    skills = sorted(path for path in source.iterdir() if (path / "SKILL.md").is_file())
    destination = root / ".agents" / "skills"
    for skill in skills:
        link = destination / skill.name
        target = os.path.relpath(skill, destination)
        if link.is_symlink() and os.readlink(link) == target:
            continue
        if check:
            raise ValueError(f"{link} is missing or stale; run make agent-setup")
        if link.exists() or link.is_symlink():
            raise ValueError(f"refusing to replace an existing skill: {link}")
        destination.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target, target_is_directory=True)
    print(f"[agent] {len(skills)} shared skills {'checked' if check else 'ready'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--tooling", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        setup(args.root.resolve(), args.tooling, args.check)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"[agent] {exc}\n")


if __name__ == "__main__":
    main()
