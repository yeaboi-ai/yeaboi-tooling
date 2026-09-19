"""Shared Claude/Codex launch and editor tasks. Authentication belongs to each CLI."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

PROVIDERS = ("claude", "codex")
TASK_LABELS = {"claude", "codex", "agent: claude", "agent: codex"}


def launch_args(provider: str, folders: list[Path], prompt: str = "", headless: bool = False) -> list[str]:
    if provider not in PROVIDERS:
        raise ValueError("choose AGENT=claude or AGENT=codex")
    argv = [provider]
    if headless:
        argv += ["exec"] if provider == "codex" else ["--print"]
    for folder in folders[1:]:
        argv += ["--add-dir", str(folder)]
    if len(folders) > 1:
        instructions = "Before working in each repository, read its AGENTS.md and .agents/repo-notes.md. Repositories: "
        instructions += ", ".join(str(folder) for folder in folders)
        prompt = f"{instructions}\n{prompt}".rstrip()
    if prompt:
        # Claude's --add-dir is variadic; end options before the prompt.
        argv += ["--", prompt]
    return argv


def editor_tasks(folders: list[Path], selected: str = "") -> list[dict]:
    if selected and selected not in PROVIDERS:
        raise ValueError("AGENT must be claude or codex (leave unset to offer both)")
    tasks = []
    for provider in PROVIDERS:
        task = {
            "label": f"agent: {provider}",
            "type": "process",
            "command": provider,
            "args": launch_args(provider, folders)[1:],
            "options": {"cwd": str(folders[0]), "env": {"YEABOI_AGENT_ROOTS": json.dumps([str(p) for p in folders])}},
            "presentation": {"reveal": "always", "panel": "new", "focus": True, "showReuseMessage": False},
            "problemMatcher": [],
        }
        if provider == selected:
            task["runOptions"] = {"runOn": "folderOpen"}
        tasks.append(task)
    return tasks


def configure_editor(root: Path, selected: str = "") -> None:
    directory = root / ".vscode"
    directory.mkdir(exist_ok=True)
    path = directory / "tasks.json"
    data = json.loads(path.read_text()) if path.exists() else {"version": "2.0.0"}
    data["tasks"] = [task for task in data.get("tasks", []) if task.get("label") not in TASK_LABELS]
    data["tasks"].extend(editor_tasks([root], selected))
    path.write_text(json.dumps(data, indent=2) + "\n")
    path = directory / "settings.json"
    settings = json.loads(path.read_text()) if path.exists() else {}
    settings["task.allowAutomaticTasks"] = "on"
    path.write_text(json.dumps(settings, indent=2) + "\n")


def task_prompt(root: Path, task: str, context: str) -> str:
    if not task or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in task):
        raise ValueError("TASK must name an installed skill")
    skill = root / ".agents" / "skills" / task / "SKILL.md"
    if not skill.is_file():
        raise ValueError(f"no skill {task!r}; run make agent-setup first")
    return f"Read AGENTS.md and {skill.relative_to(root)} and follow that skill.\nTask context: {context}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("launch", "run", "editor", "check"))
    parser.add_argument("--agent", default=os.getenv("AGENT", ""))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--add-dir", type=Path, action="append", default=[])
    parser.add_argument("--task", default="")
    parser.add_argument("--context", default=os.getenv("YEABOI_AGENT_CONTEXT", ""))
    args = parser.parse_args()
    args.root = args.root.resolve()
    args.add_dir = [path.resolve() for path in args.add_dir]
    try:
        if args.mode == "editor":
            configure_editor(args.root, args.agent)
            return 0
        if args.mode == "check":
            for provider in PROVIDERS:
                print(f"{provider}: {shutil.which(provider) or 'not installed'}")
            print("Codex: sign in with codex login; review project hooks with /hooks.")
            return 0
        prompt = task_prompt(args.root, args.task, args.context) if args.task else ""
        if args.mode == "run" and not prompt:
            raise ValueError("agent-run requires TASK=<skill> and AGENT=claude|codex")
        argv = launch_args(args.agent, [args.root, *args.add_dir], prompt, args.mode == "run")
        if not shutil.which(args.agent):
            raise ValueError(f"{args.agent} is not installed; install and sign in to that CLI first")
        return subprocess.call(
            argv,
            cwd=args.root,
            env={**os.environ, "YEABOI_AGENT_ROOTS": json.dumps([str(args.root), *map(str, args.add_dir)])},
        )
    except (ValueError, OSError) as exc:
        parser.exit(1, f"[agent] {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
