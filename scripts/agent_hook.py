"""Adapt Codex hook payloads to the devkit's shared verification and formatting."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins" / "yeaboi-devkit" / "scripts"


def changed_files(payload: dict) -> list[str]:
    tool = payload.get("tool_input", {})
    if tool.get("file_path"):
        return [tool["file_path"]]
    if payload.get("tool_name") == "apply_patch":
        return re.findall(r"^\*\*\* (?:Update File|Add File|Move to): (.+)$", tool.get("command", ""), re.MULTILINE)
    return []


def main() -> int:
    mode = sys.argv[1]
    raw = sys.stdin.read()
    payload = json.loads(raw)
    cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
    roots = [Path(path).resolve() for path in json.loads(os.getenv("YEABOI_AGENT_ROOTS", "[]"))] or [cwd]
    if mode == "stash":
        return subprocess.run(["bash", str(SCRIPTS / "guard-stash.sh")], input=raw, text=True, cwd=cwd).returncode
    if mode == "stop":
        failed = False
        for root in roots:
            result = subprocess.run(
                ["bash", str(SCRIPTS / "verify-stop.sh"), str(root)], input=raw, text=True, cwd=root
            )
            failed = result.returncode != 0 or failed
        if failed:
            return 2
        # Codex's Stop event requires JSON when stdout is non-empty.
        print("{}")
        return 0
    if mode == "format":
        for name in changed_files(payload):
            path = (cwd / name).resolve()
            if not path.is_file() or not any(path.is_relative_to(root) for root in roots):
                continue
            repo = subprocess.run(
                ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"], capture_output=True, text=True
            )
            if repo.returncode:
                continue
            subprocess.run(
                ["bash", str(SCRIPTS / "format-file.sh")],
                input=json.dumps({"tool_input": {"file_path": str(path)}}),
                text=True,
                cwd=repo.stdout.strip(),
                env={**os.environ, "CLAUDE_PROJECT_DIR": repo.stdout.strip()},
            )
        return 0
    raise ValueError(f"unknown hook: {mode}")


if __name__ == "__main__":
    raise SystemExit(main())
