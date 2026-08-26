"""Guards for the workspace: the manifest, its reader, and `setup`.

Two things here are load-bearing beyond their size. The manifest is the only
list of the repos that make up the product — the nightly builds its matrix from
it, so a row that goes missing takes a repo's cross-repo check with it silently.
And its reader is hand-rolled, because `workspace.py` has to run on whatever
python3 a machine already has; `TestTheReader` is what keeps hand-rolled from
meaning approximate.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "workspace.toml"
SCRIPT = ROOT / "scripts" / "workspace.py"


def _load():
    """Import scripts/workspace.py, which is a script rather than a package."""
    spec = importlib.util.spec_from_file_location("workspace", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Registered before it is executed: @dataclass resolves annotations through
    # sys.modules, and a module that is not there yet raises during the decorator.
    sys.modules["workspace"] = module
    spec.loader.exec_module(module)
    return module


workspace = _load()


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir()
    return {
        **{k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "MAKE", "YEABOI_"))},
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_TERMINAL_PROMPT": "0",
    }


class TestTheReader:
    def test_it_agrees_with_a_real_toml_parser_on_the_real_manifest(self) -> None:
        """The whole licence for hand-rolling one.

        `workspace.py` must run under the system interpreter, which on macOS is
        3.9 and has no tomllib. This test has one, and holds the reader to it.
        """
        text = MANIFEST.read_text()

        assert workspace.read_manifest(text) == tomllib.loads(text)

    @pytest.mark.parametrize(
        ("line", "why"),
        [
            ('name = "yeaboi"  # the Python one', "a trailing comment"),
            ("[[package]]", "a table that is not [[repo]]"),
            ("count = 3", "a value that is not a string or a boolean"),
            ('name = "say \\"hi\\""', "an escape"),
            ("names = [1, 2]", "an array"),
        ],
    )
    def test_it_refuses_what_it_cannot_read_rather_than_guessing(self, line: str, why: str) -> None:
        """A reader that half-understands a line is worse than one that stops."""
        with pytest.raises(ValueError):
            workspace.read_manifest(f"[[repo]]\n{line}\n")

    def test_a_key_before_any_table_is_refused(self) -> None:
        with pytest.raises(ValueError):
            workspace.read_manifest('name = "orphan"\n')


class TestTheManifest:
    def test_it_names_every_repo_in_the_fleet(self) -> None:
        assert {r.name for r in workspace.repos()} == {"yeaboi", "frontend", "desktop", "site", "tooling"}

    def test_every_row_is_complete_and_distinct(self) -> None:
        repos = workspace.repos()

        assert len({r.dir for r in repos}) == len(repos), "two repos claim the same directory"
        assert len({r.url for r in repos}) == len(repos)
        for repo in repos:
            assert repo.url.startswith("https://github.com/yeaboi-ai/")
            assert repo.url.endswith(".git")
            assert repo.toolchain in {"python", "node"}
            assert repo.holds, f"{repo.name} says nothing about what it holds"

    def test_the_python_repo_is_the_one_directory_that_is_not_its_name(self) -> None:
        """`dir` exists for exactly this: the remote is yeaboi.ai, not yeaboi."""
        yeaboi = next(r for r in workspace.repos() if r.name == "yeaboi")

        assert yeaboi.dir == "yeaboi.ai"

    def test_the_slug_is_what_actions_checkout_wants(self) -> None:
        assert {r.slug for r in workspace.repos()} == {
            "yeaboi-ai/yeaboi.ai",
            "yeaboi-ai/yeaboi-frontend",
            "yeaboi-ai/yeaboi-desktop",
            "yeaboi-ai/yeaboi-site",
            "yeaboi-ai/yeaboi-tooling",
        }

    def test_the_repos_that_vendor_a_contract_are_the_three_downstream_ones(self) -> None:
        """The nightly's matrix. yeaboi is upstream of all of them and vendors
        nothing; the tooling repo is consumed by sha, not by contract."""
        assert {r.name for r in workspace.repos() if r.vendors} == {"frontend", "desktop", "site"}

    def test_the_matrix_command_emits_what_the_nightly_indexes(self) -> None:
        out = subprocess.run([sys.executable, str(SCRIPT), "matrix"], capture_output=True, text=True, check=True).stdout
        rows = json.loads(out)

        assert rows, "an empty matrix would make the nightly green by running nothing"
        for row in rows:
            assert set(row) == {"name", "dir", "slug", "toolchain"}


class TestSelectingRepos:
    def test_a_repo_answers_to_its_name_or_its_directory(self) -> None:
        by_name = workspace.select(["yeaboi", "frontend"])
        by_dir = workspace.select(["yeaboi.ai", "yeaboi-frontend"])

        assert by_name == by_dir

    def test_a_repeated_repo_is_cut_once(self) -> None:
        assert len(workspace.select(["yeaboi", "yeaboi.ai"])) == 1

    def test_an_unknown_repo_names_the_known_ones(self) -> None:
        with pytest.raises(SystemExit) as caught:
            workspace.select(["frontend", "backend"])

        assert "backend" in str(caught.value)
        assert "desktop" in str(caught.value), "the error should list what it would have accepted"


def _origin(tmp_path: Path, env: dict[str, str], name: str) -> Path:
    """A throwaway repo to clone, wired the way a real one is."""
    repo = tmp_path / "origins" / name
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "provision.sh").write_text("#!/usr/bin/env bash\ntouch .provisioned\n")
    (repo / "Makefile").write_text(".PHONY: tooling-check\ntooling-check: ; @echo ok\n")
    (repo / ".tooling-rev").write_text("0" * 40 + "\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True, env=env)
    return repo


@pytest.fixture
def fleet(tmp_path: Path, env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two local origins and a manifest pointing at them. Returns the root."""
    rows = []
    for name in ("alpha", "beta"):
        origin = _origin(tmp_path, env, name)
        rows.append(
            f'[[repo]]\nname = "{name}"\ndir = "{name}"\nurl = "{origin}"\n'
            f'toolchain = "python"\nvendors = false\nholds = "a test double"\n'
        )
    manifest = tmp_path / "workspace.toml"
    manifest.write_text("\n".join(rows))
    monkeypatch.setattr(workspace, "MANIFEST", manifest)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return tmp_path / "workspace"


class TestSetup:
    def test_it_clones_and_provisions_every_repo(self, fleet: Path, capsys: pytest.CaptureFixture) -> None:
        code = workspace.main(["--root", str(fleet), "setup"])

        assert code == 0, capsys.readouterr().out
        for name in ("alpha", "beta"):
            assert (fleet / name / ".git").is_dir()
            assert (fleet / name / ".provisioned").is_file(), f"{name}'s provision.sh did not run"

    def test_a_second_run_leaves_the_checkouts_alone(self, fleet: Path, capsys: pytest.CaptureFixture) -> None:
        """`setup` is how you add the sixth repo, so it runs against a workspace
        that mostly exists. Re-cloning would discard whatever is in flight."""
        workspace.main(["--root", str(fleet), "setup"])
        (fleet / "alpha" / "work-in-progress").write_text("mine\n")
        capsys.readouterr()

        code = workspace.main(["--root", str(fleet), "setup"])

        assert code == 0
        assert (fleet / "alpha" / "work-in-progress").is_file()
        assert "present" in capsys.readouterr().out

    def test_one_repo_failing_does_not_take_the_others_with_it(
        self, fleet: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        rows = [r for r in workspace.repos()]
        broken = workspace.Repo(**{**rows[0].__dict__, "url": str(fleet / "nothing-here")})
        monkeypatch.setattr(workspace, "repos", lambda: [broken, rows[1]])

        code = workspace.main(["--root", str(fleet), "setup"])
        out = capsys.readouterr().out

        assert code == 1, "a failed clone must be reported, not swallowed"
        assert (fleet / "beta" / ".git").is_dir(), "the second repo was skipped by the first one's failure"
        assert "alpha (clone)" in out

    def test_a_checkout_that_predates_the_shared_tooling_is_named_as_behind(
        self, fleet: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """It fails `make tooling-check` with make's own "no rule to make
        target", which says nothing about what is actually wrong."""
        workspace.main(["--root", str(fleet), "setup"])
        (fleet / "alpha" / ".tooling-rev").unlink()
        capsys.readouterr()

        code = workspace.main(["--root", str(fleet), "setup"])
        out = capsys.readouterr().out

        assert code == 1
        assert "predates the shared tooling" in out
        assert "git -C" in out, "it should say how to fix it"


class TestStatusAndEnv:
    def test_status_reports_what_is_not_cloned_yet(self, fleet: Path, capsys: pytest.CaptureFixture) -> None:
        workspace.main(["--root", str(fleet), "status"])
        out = capsys.readouterr().out

        assert "not cloned" in out
        assert "make workspace-setup" in out

    def test_status_reads_the_branch_and_the_working_state(self, fleet: Path, capsys: pytest.CaptureFixture) -> None:
        workspace.main(["--root", str(fleet), "setup"])
        (fleet / "alpha" / "scratch").write_text("x\n")
        capsys.readouterr()

        workspace.main(["--root", str(fleet), "status"])
        out = capsys.readouterr().out

        assert "main" in out
        assert "1 dirty" in out

    def test_env_comments_out_a_seam_whose_target_is_not_built(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """`assets.py` raises rather than falling back, so exporting
        YEABOI_WEB_STATIC at a path that does not exist breaks every board."""
        workspace.main(["--root", str(tmp_path / "empty"), "env"])
        out = capsys.readouterr().out

        assert "export YEABOI_WEB_STATIC" not in out
        assert "make build" in out, "it should say how to make the missing half"

    def test_env_exports_the_seams_that_do_exist(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        root = tmp_path / "built"
        (root / "yeaboi-frontend" / "yeaboi_web_assets" / "static").mkdir(parents=True)
        (root / "yeaboi.ai" / ".venv" / "bin").mkdir(parents=True)
        (root / "yeaboi.ai" / ".venv" / "bin" / "python").write_text("")

        workspace.main(["--root", str(root), "env"])
        out = capsys.readouterr().out

        assert f"export YEABOI_WEB_STATIC={root}/yeaboi-frontend/yeaboi_web_assets/static" in out
        assert f"export YEABOI_DESKTOP_PYTHON={root}/yeaboi.ai/.venv/bin/python" in out
        assert f"export YEABOI_REPO={root}/yeaboi.ai" in out


class TestWorktreeSets:
    def test_a_name_in_several_repos_is_reported_as_a_set(self, fleet: Path, capsys: pytest.CaptureFixture) -> None:
        """Nothing records a set — a recorded one goes stale the moment somebody
        removes a worktree by hand. The listing is the directories themselves."""
        workspace.main(["--root", str(fleet), "setup"])
        for name in ("alpha", "beta"):
            tree = fleet / name / ".claude" / "worktrees" / "shared-feature"
            tree.mkdir(parents=True)
            (tree / ".git").write_text("gitdir: elsewhere\n")
        (fleet / "alpha" / ".claude" / "worktrees" / "solo").mkdir()
        capsys.readouterr()

        workspace.main(["--root", str(fleet), "wt-sets"])
        out = capsys.readouterr().out

        assert "shared-feature" in out and "(a set)" in out
        assert "solo" not in out, "a directory with no .git is not a worktree"

    def test_removing_a_name_no_repo_has_says_so(self, fleet: Path, capsys: pytest.CaptureFixture) -> None:
        workspace.main(["--root", str(fleet), "setup"])
        capsys.readouterr()

        code = workspace.main(["--root", str(fleet), "wt-set-rm", "never-cut"])

        assert code == 1
        assert "no repo has a worktree named" in capsys.readouterr().out


class TestTheNightly:
    """The one check nobody's PR can run, so nothing else notices it rotting."""

    @pytest.fixture
    def nightly(self) -> str:
        return (ROOT / ".github" / "workflows" / "nightly.yml").read_text()

    def test_its_matrix_comes_from_the_manifest(self, nightly: str) -> None:
        """A hard-coded list here is a sixth place to remember a repo exists."""
        assert "workspace.py matrix" in nightly
        assert "fromJSON(needs.plan.outputs.repos)" in nightly

    def test_it_runs_each_repo_s_own_gate_against_freshly_vendored_contracts(self, nightly: str) -> None:
        assert "make contracts-sync" in nightly
        assert "make ship-gate" in nightly

    def test_it_takes_the_newest_published_web_assets_rather_than_the_locked_one(self, nightly: str) -> None:
        """Without the upgrade it would re-test the version yeaboi's own CI
        already tested — the one thing that cannot have broken overnight."""
        assert "uv lock --upgrade-package yeaboi-web-assets" in nightly

    def test_it_reuses_one_issue_instead_of_filing_one_a_morning(self, nightly: str) -> None:
        assert "gh issue comment" in nightly
        assert "gh issue create" in nightly

    def test_it_can_be_run_by_hand(self, nightly: str) -> None:
        """A cross-repo check you cannot trigger is one you cannot use to
        confirm a fix landed."""
        assert "workflow_dispatch" in nightly
