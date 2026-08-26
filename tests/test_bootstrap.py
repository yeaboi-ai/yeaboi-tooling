"""End-to-end tests for the bootstrap: a repo pins this one and gets the shared targets.

Everything else in this repo is guarded by reading files. This is the one
mechanism that has to actually run — four repos will consume the shared tooling
through exactly these six lines of Makefile and one copied script, and a
bootstrap that half-works produces a `make` that hangs or an `include` that
fails with make's own error rather than ours.

Each test builds a throwaway "tooling origin" from this repo's real `mk/`,
`scripts/` and `bootstrap/`, plus a throwaway consumer repo that pins it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

MINIMAL_TARGETS = """
.PHONY: lint test test-fast test-scoped ship-gate
lint: ; @echo lint
test-fast: ; @echo test-fast
test-scoped: test-fast
test: test-fast
ship-gate: lint test tooling-check ; @echo gate
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir()
    return {
        **{k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "MAKE"))},
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_TERMINAL_PROMPT": "0",
    }


@pytest.fixture
def tooling(tmp_path: Path, env: dict[str, str]) -> tuple[Path, str]:
    """A git repo holding this repo's real shared halves. Returns (path, sha)."""
    repo = tmp_path / "tooling"
    repo.mkdir()
    for name in ("mk", "scripts", "bootstrap"):
        shutil.copytree(ROOT / name, repo / name)
    (repo / ".claude-plugin").mkdir()
    shutil.copy(ROOT / ".claude-plugin" / "marketplace.json", repo / ".claude-plugin")
    shutil.copy(ROOT / "workspace.toml", repo / "workspace.toml")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "tooling"], check=True, env=env)
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True, env=env
    ).stdout.strip()
    return repo, sha


@pytest.fixture
def consumer(tmp_path: Path, tooling: tuple[Path, str], env: dict[str, str]) -> Path:
    """A repo pinned to `tooling`, wired exactly as bootstrap/README says."""
    _, sha = tooling
    repo = tmp_path / "consumer"
    (repo / "scripts").mkdir(parents=True)
    (repo / ".tooling-rev").write_text(sha + "\n")
    shutil.copy(ROOT / "bootstrap" / "tooling-sync.sh", repo / "scripts" / "tooling-sync.sh")
    (repo / "Makefile").write_text((ROOT / "bootstrap" / "Makefile.head").read_text() + MINIMAL_TARGETS)
    (repo / ".gitignore").write_text(".tooling/\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True, env=env)
    return repo


def _make(repo: Path, target: str, env: dict[str, str], tooling_repo: Path, **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", *([target] if target else [])],
        cwd=repo,
        capture_output=True,
        text=True,
        # 60s is not a patience setting: a recipe line containing $(MAKE) runs
        # even under --dry-run, so probing a target that depends on the probe
        # recurses forever. This bound is what turns that into a failure.
        timeout=60,
        env={**env, "TOOLING_REPO": str(tooling_repo), **kw.pop("extra_env", {})},
    )


class TestTheBootstrapProvisionsItself:
    def test_a_fresh_checkout_clones_the_pin_on_the_first_make(
        self, consumer: Path, tooling: tuple[Path, str], env: dict[str, str]
    ) -> None:
        """A new worktree has no .tooling/ — that is why this is not a submodule."""
        tooling_path, sha = tooling
        assert not (consumer / ".tooling").exists()

        result = _make(consumer, "tooling-check", env, tooling_path)

        assert result.returncode == 0, result.stderr
        assert (consumer / ".tooling" / "mk" / "common.mk").is_file()
        assert (consumer / ".tooling" / ".git" / "tooling-rev").read_text().strip() == sha
        assert "pin honoured" in result.stdout

    def test_the_steady_state_touches_no_network(
        self, consumer: Path, tooling: tuple[Path, str], env: dict[str, str]
    ) -> None:
        """The sync runs at parse time; if it ran every time, every `make` would fetch."""
        tooling_path, _ = tooling
        _make(consumer, "tooling-check", env, tooling_path)

        # Point the repo URL at nothing. A second run that reached for it fails.
        gone = tooling_path.parent / "gone.git"
        result = _make(consumer, "tooling-check", env, gone)

        assert result.returncode == 0, f"the second run went to the network: {result.stderr}"
        assert not gone.exists()

    def test_the_shared_targets_are_available_to_the_consumer(
        self, consumer: Path, tooling: tuple[Path, str], env: dict[str, str]
    ) -> None:
        tooling_path, _ = tooling
        result = _make(consumer, "wt-list", env, tooling_path)

        assert result.returncode == 0, result.stderr
        assert "BRANCH" in result.stdout, "mk/common.mk's wt-list did not run"

    def test_the_workspace_targets_reach_the_manifest_inside_the_pin(
        self, consumer: Path, tooling: tuple[Path, str], env: dict[str, str]
    ) -> None:
        """workspace.py and workspace.toml both live in `.tooling/`, and the
        script resolves the manifest from its own location. Nothing else in the
        shared half does that, so nothing else would notice it breaking."""
        tooling_path, _ = tooling
        result = _make(consumer, "workspace-status", env, tooling_path)

        assert result.returncode == 0, result.stderr
        assert "yeaboi-frontend" in result.stdout, "the manifest was not read"
        assert "not cloned" in result.stdout

    def test_a_bare_make_prints_help_rather_than_cutting_a_worktree(
        self, consumer: Path, tooling: tuple[Path, str], env: dict[str, str]
    ) -> None:
        """An include brings targets with it, and the first target wins the default goal."""
        tooling_path, _ = tooling
        (consumer / "Makefile").write_text((consumer / "Makefile").read_text() + "\nhelp: ; @echo HELP-RAN\n")

        result = _make(consumer, "", env, tooling_path)

        assert "HELP-RAN" in result.stdout, result.stdout + result.stderr


class TestTheContract:
    def test_a_missing_shared_target_is_named(
        self, consumer: Path, tooling: tuple[Path, str], env: dict[str, str]
    ) -> None:
        tooling_path, _ = tooling
        text = (consumer / "Makefile").read_text().replace("test-scoped: test-fast", "")
        (consumer / "Makefile").write_text(text)

        result = _make(consumer, "tooling-check", env, tooling_path)

        assert result.returncode != 0
        assert "test-scoped" in result.stdout + result.stderr

    def test_probing_the_gate_terminates(self, consumer: Path, tooling: tuple[Path, str], env: dict[str, str]) -> None:
        """`ship-gate` depends on `tooling-check`, which probes `ship-gate`.

        With `$(MAKE)` in the probe that recursed without bound, because GNU make
        runs such a line even under --dry-run. The 60s timeout in `_make` is the
        assertion; reaching it raises rather than failing.
        """
        tooling_path, _ = tooling
        result = _make(consumer, "ship-gate", env, tooling_path)

        assert result.returncode == 0, result.stderr
        assert "gate" in result.stdout


class TestThePinIsHonoured:
    def test_a_stale_checkout_is_re_synced_not_ignored(
        self, consumer: Path, tooling: tuple[Path, str], env: dict[str, str]
    ) -> None:
        tooling_path, first = tooling
        _make(consumer, "tooling-check", env, tooling_path)
        (tooling_path / "mk" / "extra.mk").write_text("# later\n")
        subprocess.run(["git", "-C", str(tooling_path), "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", str(tooling_path), "commit", "-qm", "later"], check=True, env=env)
        second = subprocess.run(
            ["git", "-C", str(tooling_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout.strip()
        assert second != first
        (consumer / ".tooling-rev").write_text(second + "\n")

        result = _make(consumer, "tooling-check", env, tooling_path)

        assert result.returncode == 0, result.stderr
        assert (consumer / ".tooling" / "mk" / "extra.mk").is_file()

    def test_a_locally_edited_pin_is_refused(
        self, consumer: Path, tooling: tuple[Path, str], env: dict[str, str]
    ) -> None:
        """A fix made inside `.tooling/` is invisible to every other repo and vanishes on sync."""
        tooling_path, _ = tooling
        _make(consumer, "tooling-check", env, tooling_path)
        (consumer / ".tooling" / "scripts" / "wt-list.sh").write_text("# tampered\n")

        result = _make(consumer, "tooling-check", env, tooling_path)

        assert result.returncode != 0
        assert "local modifications" in result.stderr

    def test_a_drifted_bootstrap_copy_is_refused(
        self, consumer: Path, tooling: tuple[Path, str], env: dict[str, str]
    ) -> None:
        """The bootstrap is copied, not included — it is the one file that can rot silently."""
        tooling_path, _ = tooling
        _make(consumer, "tooling-check", env, tooling_path)
        script = consumer / "scripts" / "tooling-sync.sh"
        script.write_text(script.read_text() + "\n# local tweak\n")

        result = _make(consumer, "tooling-check", env, tooling_path)

        assert result.returncode != 0
        assert "drifted" in result.stderr
