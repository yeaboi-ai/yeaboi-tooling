"""The launch contract, discovery and hook payloads shared by both assistants."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent
import agent_hook
import agent_setup
import worktree_paths


def test_selection_and_multiroot_arguments(tmp_path):
    folders = [tmp_path / "a repo", tmp_path / "b repo", tmp_path / "c repo"]
    for provider in agent.PROVIDERS:
        tasks = agent.editor_tasks(folders, provider)
        assert [task["command"] for task in tasks if "runOptions" in task] == [provider]
        assert all(task["type"] == "process" for task in tasks)
        assert tasks[0]["args"][:-1] == ["--add-dir", str(folders[1]), "--add-dir", str(folders[2]), "--"]
        assert "AGENTS.md" in tasks[0]["args"][-1]
        assert all(str(folder) in tasks[0]["args"][-1] for folder in folders)
        assert json.loads(tasks[0]["options"]["env"]["YEABOI_AGENT_ROOTS"]) == list(map(str, folders))
    assert all("runOptions" not in task for task in agent.editor_tasks(folders))
    with pytest.raises(ValueError):
        agent.editor_tasks(folders, "unknown")


def test_headless_runs_use_the_selected_cli_and_no_permission_bypass(tmp_path):
    assert agent.launch_args("codex", [tmp_path], "inspect", True) == ["codex", "exec", "--", "inspect"]
    assert agent.launch_args("claude", [tmp_path], "inspect", True) == ["claude", "--print", "--", "inspect"]
    with pytest.raises(ValueError):
        agent.launch_args("", [tmp_path])


def test_editor_refresh_preserves_user_tasks_and_changes_selected_provider(tmp_path):
    folder = tmp_path / ".vscode"
    folder.mkdir()
    (folder / "tasks.json").write_text(json.dumps({"tasks": [{"label": "build", "command": "make build"}]}))
    (folder / "settings.json").write_text('{"editor.tabSize": 4}')
    agent.configure_editor(tmp_path, "claude")
    agent.configure_editor(tmp_path, "codex")
    tasks = json.loads((folder / "tasks.json").read_text())["tasks"]
    assert len(tasks) == 3
    assert tasks[0]["command"] == "make build"
    assert [task["command"] for task in tasks if "runOptions" in task] == ["codex"]
    assert json.loads((folder / "settings.json").read_text())["editor.tabSize"] == 4


def test_skills_are_idempotent_and_never_replace_local_work(tmp_path):
    source = tmp_path / "tooling"
    skill = source / "plugins/yeaboi-devkit/skills/example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("one")
    repo = tmp_path / "repo"
    agent_setup.setup(repo, source)
    agent_setup.setup(repo, source)
    agent_setup.setup(repo, source, check=True)
    assert (repo / ".agents/skills/example/SKILL.md").read_text() == "one"
    assert "example/SKILL.md" in agent.task_prompt(repo, "example", "context")
    link = repo / ".agents/skills/example"
    link.unlink()
    link.mkdir()
    with pytest.raises(ValueError, match="refusing"):
        agent_setup.setup(repo, source)


def test_editor_refresh_accepts_jsonc_and_preserves_string_contents(tmp_path):
    folder = tmp_path / ".vscode"
    folder.mkdir()
    command = 'echo "https://example.com/*literal*/,}"'
    (folder / "tasks.json").write_text(
        '{ // developer task\n"tasks": [{"label": "build", "command": ' + json.dumps(command) + ",},],}"
    )
    (folder / "settings.json").write_text('{ /* preferences */ "editor.tabSize": 4,}')
    agent.configure_editor(tmp_path)
    tasks = json.loads((folder / "tasks.json").read_text())["tasks"]
    assert tasks[0] == {"label": "build", "command": command}
    assert len(tasks) == 3
    assert json.loads((folder / "settings.json").read_text())["editor.tabSize"] == 4


@pytest.mark.parametrize("invalid", ['{"value": 1/* comment */2}', '{"value": [,,]}'])
def test_editor_config_rejects_malformed_values(tmp_path, invalid):
    path = tmp_path / "settings.json"
    path.write_text(invalid)
    with pytest.raises(json.JSONDecodeError):
        agent.load_editor_config(path)


@pytest.mark.parametrize("fail", [False, True])
def test_stop_hook_verifies_the_repository_when_started_from_a_subdirectory(tmp_path, monkeypatch, fail):
    monkeypatch.delenv("YEABOI_AGENT_ROOTS", raising=False)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    nested = tmp_path / "tests"
    nested.mkdir()
    (tmp_path / "changed.py").write_text("changed = True\n")
    lint = "false" if fail else "echo lint >> verified"
    (tmp_path / "Makefile").write_text(f"lint:\n\t@{lint}\ntest-scoped:\n\t@echo test >> verified\n")
    result = subprocess.run(
        [sys.executable, str(Path(agent_hook.__file__)), "stop"],
        input=json.dumps({"cwd": str(nested)}),
        text=True,
        capture_output=True,
        cwd=nested,
    )
    assert result.returncode == (2 if fail else 0)
    if fail:
        assert "verification failed: make lint" in result.stderr
    else:
        assert (tmp_path / "verified").read_text().splitlines() == ["lint", "test"]
        assert json.loads(result.stdout) == {}


def test_format_adapter_handles_edits_and_multifile_patches():
    assert agent_hook.changed_files({"tool_input": {"file_path": "hello.py"}}) == ["hello.py"]
    patch = "*** Update File: a.py\n@@\n-x\n+y\n*** Add File: b space.py\n+x\n*** Delete File: c.py\n"
    assert agent_hook.changed_files({"tool_name": "apply_patch", "tool_input": {"command": patch}}) == [
        "a.py",
        "b space.py",
    ]
    assert agent_hook.changed_files({"tool_name": "Bash", "tool_input": {"command": patch}}) == []


def test_layout_resolution_and_conflicts(tmp_path):
    assert worktree_paths.target(tmp_path, "feature/nested") == tmp_path / ".worktrees/feature/nested"
    legacy = tmp_path / ".claude/worktrees/feature/nested"
    legacy.mkdir(parents=True)
    assert worktree_paths.target(tmp_path, "feature/nested") == legacy
    (tmp_path / ".worktrees/feature/nested").mkdir(parents=True)
    with pytest.raises(ValueError, match="ambiguous"):
        worktree_paths.target(tmp_path, "feature/nested")
    for name in ("../oops", "/tmp/other", "feature//oops", "@{-1}"):
        with pytest.raises(ValueError):
            worktree_paths.target(tmp_path, name)


@pytest.mark.parametrize("provider", agent.PROVIDERS)
def test_make_runs_the_selected_cli_with_literal_task_context(tmp_path, provider):
    tooling = Path(__file__).resolve().parents[1]
    (tmp_path / "Makefile").write_text(f"TOOLING := {tooling}\ninclude {tooling}/mk/common.mk\n")
    binary = tmp_path / provider
    binary.write_text(f"#!{sys.executable}\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n")
    binary.chmod(0o755)
    context = 'inspect "quoted text", $HOME and `touch unexpected`'
    result = subprocess.run(
        ["make", "agent-run", f"AGENT={provider}", "TASK=yeaboi-review", f"ARGS={context}"],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=True,
    )
    argv = json.loads(result.stdout.splitlines()[-1])
    assert argv[:2] == ["exec" if provider == "codex" else "--print", "--"]
    assert argv[-1].endswith(f"Task context: {context}")
    assert not (tmp_path / "unexpected").exists()
