"""Tests for scripts/wt.sh — the git-worktree provisioning script behind `make wt-new`.

The script's job is to cut every new feature branch from the *freshly fetched*
upstream default branch, so a stale main checkout cannot hand a worktree an old
base. That guarantee, and the four fallbacks around it, are only observable by
running the real script against real git repositories — so each test builds a
throwaway bare "origin" plus a clone in tmp_path and inspects the resulting refs.

Provisioning is the repo's own `scripts/provision.sh`, so most cases simply omit
it — a real toolchain install would put a minute on every test. `TestProvision`
covers the seam itself.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

WT_SH = Path(__file__).resolve().parents[1] / "scripts" / "wt.sh"


def _git(repo: Path, *args: str, env: dict[str, str], check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=env,
        check=check,
    )
    return result.stdout.strip()


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """Git env isolated from the developer's real config, hooks and credentials.

    Every inherited GIT_* variable is dropped, not just overridden. Under the
    pre-commit hook the suite runs with GIT_INDEX_FILE / GIT_DIR / GIT_WORK_TREE
    pointing at the *real* repository, and `git -C <tmp> add -A` obeys those over
    -C: the temp repo's tree lands in the real index, recording every real file
    as deleted. Inheriting the environment here is not a tidiness question.
    """
    home = tmp_path / "home"
    home.mkdir()
    return {
        **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
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
def repo(tmp_path: Path, env: dict[str, str]) -> Path:
    """A bare origin + a clone of it holding scripts/wt.sh, both on `main`.

    Returns the clone (the "main checkout" the script operates against).
    """
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, env=env)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, env=env)

    scripts = work / "scripts"
    scripts.mkdir()
    shutil.copy(WT_SH, scripts / "wt.sh")
    (work / "f.txt").write_text("one\n")
    _git(work, "add", "-A", env=env)
    _git(work, "commit", "-qm", "one", env=env)
    _git(work, "push", "-q", "-u", "origin", "main", env=env)
    # Worktrees are gitignored in the real repo; mirror that so the clone reads
    # as clean once one exists.
    (work / ".git" / "info" / "exclude").write_text(".claude/worktrees/\n")
    return work


def _push_upstream_commit(tmp_path: Path, env: dict[str, str], branch: str = "main") -> str:
    """Land a commit on origin/<branch> from a second clone, leaving `repo` stale."""
    other = tmp_path / f"other-{branch}"
    subprocess.run(["git", "clone", "-q", "-b", branch, str(tmp_path / "origin.git"), str(other)], check=True, env=env)
    (other / "f2.txt").write_text("two\n")
    _git(other, "add", "-A", env=env)
    _git(other, "commit", "-qm", "two", env=env)
    _git(other, "push", "-q", "origin", branch, env=env)
    return _git(other, "rev-parse", "HEAD", env=env)


def _push_remote_only_branch(tmp_path: Path, env: dict[str, str], name: str) -> str:
    """Create a branch that exists on origin but NOT in `repo` (a teammate's branch)."""
    other = tmp_path / f"other-rb-{name.replace('/', '-')}"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True, env=env)
    _git(other, "checkout", "-qb", name, env=env)
    (other / "rb.txt").write_text(f"{name}\n")
    _git(other, "add", "-A", env=env)
    _git(other, "commit", "-qm", "remote work", env=env)
    _git(other, "push", "-q", "origin", name, env=env)
    return _git(other, "rev-parse", "HEAD", env=env)


def _run_wt(repo: Path, name: str, env: dict[str, str], action: str = "headless") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/wt.sh", name, action],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )


class TestBranchBase:
    """The core guarantee: a new branch starts at the latest upstream default."""

    def test_new_branch_starts_at_origin_main_when_local_is_stale(
        self, tmp_path: Path, repo: Path, env: dict[str, str]
    ) -> None:
        upstream = _push_upstream_commit(tmp_path, env)
        local_before = _git(repo, "rev-parse", "HEAD", env=env)
        assert local_before != upstream  # the clone really is behind

        result = _run_wt(repo, "feat-a", env)

        assert result.returncode == 0, result.stderr
        assert _git(repo, "rev-parse", "feat-a", env=env) == upstream

    def test_new_branch_has_no_upstream(self, tmp_path: Path, repo: Path, env: dict[str, str]) -> None:
        """--no-track: otherwise a bare `git push` in the worktree aims at main."""
        _push_upstream_commit(tmp_path, env)
        _run_wt(repo, "feat-a", env)

        tracking = subprocess.run(
            ["git", "-C", str(repo), "config", "--get", "branch.feat-a.merge"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert tracking.stdout.strip() == ""

    def test_honours_a_default_branch_that_is_not_main(self, tmp_path: Path, repo: Path, env: dict[str, str]) -> None:
        """origin/HEAD is asked for, not assumed — a wrong guess means a stale base."""
        origin = tmp_path / "origin.git"
        _git(repo, "branch", "-q", "trunk", env=env)
        _git(repo, "push", "-q", "origin", "trunk", env=env)
        _git(origin, "symbolic-ref", "HEAD", "refs/heads/trunk", env=env)
        upstream = _push_upstream_commit(tmp_path, env, branch="trunk")
        # Unset locally, as on clones built with `git init` + `git remote add`.
        _git(repo, "remote", "set-head", "origin", "-d", env=env, check=False)

        result = _run_wt(repo, "feat-a", env)

        assert result.returncode == 0, result.stderr
        assert _git(repo, "rev-parse", "feat-a", env=env) == upstream

    def test_no_origin_remote_falls_back_to_head(self, repo: Path, env: dict[str, str]) -> None:
        _git(repo, "remote", "remove", "origin", env=env)
        head = _git(repo, "rev-parse", "HEAD", env=env)

        result = _run_wt(repo, "solo", env)

        assert result.returncode == 0, result.stderr
        assert "no 'origin' remote" in result.stdout
        assert _git(repo, "rev-parse", "solo", env=env) == head


class TestExistingBranch:
    """Provisioning must never rewrite history that already exists."""

    def test_existing_branch_is_reused_untouched(self, tmp_path: Path, repo: Path, env: dict[str, str]) -> None:
        old = _git(repo, "rev-parse", "HEAD", env=env)
        _git(repo, "branch", "old-feat", old, env=env)
        _push_upstream_commit(tmp_path, env)

        result = _run_wt(repo, "old-feat", env)

        assert result.returncode == 0, result.stderr
        assert _git(repo, "rev-parse", "old-feat", env=env) == old
        assert "1 commit(s) behind" in result.stdout


class TestRemoteBranch:
    """A branch existing only on origin is continued, never shadowed by a re-cut."""

    def test_remote_only_branch_is_checked_out_tracking(self, tmp_path: Path, repo: Path, env: dict[str, str]) -> None:
        remote_tip = _push_remote_only_branch(tmp_path, env, "feat-r")
        main_tip = _git(repo, "rev-parse", "HEAD", env=env)
        assert remote_tip != main_tip

        result = _run_wt(repo, "feat-r", env)

        assert result.returncode == 0, result.stderr
        # The regression this path exists to prevent: a fresh same-named branch
        # cut from origin/main instead of the teammate's actual branch.
        assert _git(repo, "rev-parse", "feat-r", env=env) == remote_tip
        assert "checked out existing remote branch origin/feat-r" in result.stdout
        # --track: a bare `git push` in the worktree must aim at origin/feat-r.
        assert _git(repo, "config", "--get", "branch.feat-r.merge", env=env) == "refs/heads/feat-r"

    def test_local_branch_wins_over_remote_of_same_name(self, tmp_path: Path, repo: Path, env: dict[str, str]) -> None:
        local_tip = _git(repo, "rev-parse", "HEAD", env=env)
        _git(repo, "branch", "feat-r", local_tip, env=env)
        _push_remote_only_branch(tmp_path, env, "feat-r")

        result = _run_wt(repo, "feat-r", env)

        assert result.returncode == 0, result.stderr
        assert _git(repo, "rev-parse", "feat-r", env=env) == local_tip

    def test_nested_branch_name_creates_nested_worktree(self, tmp_path: Path, repo: Path, env: dict[str, str]) -> None:
        """Slash-containing names (feature/foo, 123-issue-title) must nest, not fail."""
        remote_tip = _push_remote_only_branch(tmp_path, env, "feature/nested-fix")

        result = _run_wt(repo, "feature/nested-fix", env)

        assert result.returncode == 0, result.stderr
        assert (repo / ".claude" / "worktrees" / "feature" / "nested-fix").is_dir()
        assert _git(repo, "rev-parse", "feature/nested-fix", env=env) == remote_tip


class TestLocalDefaultSync:
    """The main checkout's own default branch is a convenience, never a risk."""

    def test_clean_checkout_is_fast_forwarded(self, tmp_path: Path, repo: Path, env: dict[str, str]) -> None:
        upstream = _push_upstream_commit(tmp_path, env)

        result = _run_wt(repo, "feat-a", env)

        assert "fast-forwarded 'main'" in result.stdout
        assert _git(repo, "rev-parse", "main", env=env) == upstream

    def test_uncommitted_changes_leave_the_checkout_alone(
        self, tmp_path: Path, repo: Path, env: dict[str, str]
    ) -> None:
        upstream = _push_upstream_commit(tmp_path, env)
        local_before = _git(repo, "rev-parse", "HEAD", env=env)
        (repo / "f.txt").write_text("edited\n")

        result = _run_wt(repo, "feat-a", env)

        assert "uncommitted changes" in result.stdout
        assert _git(repo, "rev-parse", "main", env=env) == local_before
        assert (repo / "f.txt").read_text() == "edited\n"
        # …and the new branch still starts at the upstream tip.
        assert _git(repo, "rev-parse", "feat-a", env=env) == upstream

    def test_untracked_files_do_not_block_the_fast_forward(
        self, tmp_path: Path, repo: Path, env: dict[str, str]
    ) -> None:
        """A real checkout always has untracked junk; counting it would kill this path."""
        upstream = _push_upstream_commit(tmp_path, env)
        (repo / "stray.log").write_text("noise\n")

        _run_wt(repo, "feat-a", env)

        assert _git(repo, "rev-parse", "main", env=env) == upstream


class TestProvision:
    """The seam between the shared script and the repo's own toolchain."""

    def test_provision_script_runs_inside_the_new_worktree(self, repo: Path, env: dict[str, str]) -> None:
        (repo / "scripts" / "provision.sh").write_text("#!/bin/sh\npwd > provisioned.txt\n")
        _git(repo, "add", "-A", env=env)
        _git(repo, "commit", "-qm", "provision", env=env)
        # The worktree is cut from origin/main, so an unpushed commit would not
        # be in it — which is the whole point of cutting from upstream.
        _git(repo, "push", "-q", "origin", "main", env=env)

        result = _run_wt(repo, "feat-p", env)

        assert result.returncode == 0, result.stderr
        stamp = repo / ".claude" / "worktrees" / "feat-p" / "provisioned.txt"
        assert stamp.is_file(), "provision.sh did not run"
        # Its cwd is the worktree, not the main checkout — a venv built in the
        # wrong tree is worse than none.
        assert Path(stamp.read_text().strip()).resolve() == (repo / ".claude" / "worktrees" / "feat-p").resolve()

    def test_a_failing_provision_leaves_the_worktree_usable(self, repo: Path, env: dict[str, str]) -> None:
        """A missing toolchain must not cost the branch — the tree is the expensive part."""
        (repo / "scripts" / "provision.sh").write_text("#!/bin/sh\nexit 3\n")
        _git(repo, "add", "-A", env=env)
        _git(repo, "commit", "-qm", "provision", env=env)
        # The worktree is cut from origin/main, so an unpushed commit would not
        # be in it — which is the whole point of cutting from upstream.
        _git(repo, "push", "-q", "origin", "main", env=env)

        result = _run_wt(repo, "feat-p", env)

        assert result.returncode == 0, result.stderr
        assert "provision.sh failed" in result.stdout
        assert (repo / ".claude" / "worktrees" / "feat-p").is_dir()

    def test_no_provision_script_is_reported_not_fatal(self, repo: Path, env: dict[str, str]) -> None:
        result = _run_wt(repo, "feat-p", env)

        assert result.returncode == 0, result.stderr
        assert "no scripts/provision.sh" in result.stdout


class TestRepoResolution:
    """The script is reached at `.tooling/scripts/wt.sh` — a *different* git repo.

    Resolving the project from `$BASH_SOURCE` (as this script did while it lived
    in the repo it served) would cut every worktree in the tooling clone.
    """

    def test_the_project_comes_from_the_cwd_not_the_script_path(self, repo: Path, env: dict[str, str]) -> None:
        nested = repo / ".tooling"
        subprocess.run(["git", "init", "-q", "-b", "main", str(nested)], check=True, env=env)
        (nested / "scripts").mkdir()
        shutil.copy(WT_SH, nested / "scripts" / "wt.sh")
        (nested / "seed.txt").write_text("x\n")
        _git(nested, "add", "-A", env=env)
        _git(nested, "commit", "-qm", "seed", env=env)

        result = subprocess.run(
            ["bash", ".tooling/scripts/wt.sh", "feat-n", "headless"],
            cwd=repo,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, result.stderr
        assert (repo / ".claude" / "worktrees" / "feat-n").is_dir()
        assert not (nested / ".claude").exists(), "the worktree was cut in the tooling clone"

    def test_wt_repo_dir_overrides_the_cwd(self, tmp_path: Path, repo: Path, env: dict[str, str]) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        result = subprocess.run(
            ["bash", str(repo / "scripts" / "wt.sh"), "feat-e", "headless"],
            cwd=elsewhere,
            capture_output=True,
            text=True,
            env={**env, "WT_REPO_DIR": str(repo)},
        )

        assert result.returncode == 0, result.stderr
        assert (repo / ".claude" / "worktrees" / "feat-e").is_dir()
