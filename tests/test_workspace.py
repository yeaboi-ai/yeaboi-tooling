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
import shutil
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

    def test_the_repos_that_vendor_a_contract_are_the_two_downstream_ones(self) -> None:
        """The nightly's matrix. yeaboi is upstream of both and vendors nothing;
        the tooling repo is consumed by sha, not by contract; and desktop
        GENERATES its routes manifest rather than vendoring one, so re-vendoring
        it there would fight the generator that owns the file."""
        assert {r.name for r in workspace.repos() if r.vendors} == {"frontend", "site"}

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

    def test_a_branch_shaped_name_is_still_a_set(self, fleet: Path, capsys: pytest.CaptureFixture) -> None:
        """`desktop/tips-ui` nests on disk, so a single-level scan saw only the
        `desktop` parent — no .git, skipped — and the set went unreported. That
        is how a feature ships in one repo and is forgotten in the other."""
        workspace.main(["--root", str(fleet), "setup"])
        for name in ("alpha", "beta"):
            tree = fleet / name / ".claude" / "worktrees" / "desktop" / "tips-ui"
            tree.mkdir(parents=True)
            (tree / ".git").write_text("gitdir: elsewhere\n")
        capsys.readouterr()

        workspace.main(["--root", str(fleet), "wt-sets"])
        out = capsys.readouterr().out

        assert "desktop/tips-ui" in out, "a nested worktree name must survive the scan"
        assert "(a set)" in out

    def test_the_pinned_tooling_clone_is_not_a_worktree(self, fleet: Path) -> None:
        """Every worktree carries a .tooling checkout at the pinned sha. It has a
        .git, but it is not a worktree of this repo and must never be a name."""
        workspace.main(["--root", str(fleet), "setup"])
        tree = fleet / "alpha" / ".claude" / "worktrees" / "feature"
        (tree / ".tooling").mkdir(parents=True)
        (tree / ".git").write_text("gitdir: elsewhere\n")
        (tree / ".tooling" / ".git").write_text("gitdir: elsewhere\n")

        assert workspace.worktrees(fleet / "alpha") == ["feature"]

    def test_removing_a_name_no_repo_has_says_so(self, fleet: Path, capsys: pytest.CaptureFixture) -> None:
        workspace.main(["--root", str(fleet), "setup"])
        capsys.readouterr()

        code = workspace.main(["--root", str(fleet), "wt-set-rm", "never-cut"])

        assert code == 1
        assert "no repo has a worktree named" in capsys.readouterr().out


class TestCuttingASet:
    """`make wt-new` — one branch name, every repo, one editor window.

    The per-repo cut is a `make` in another checkout, so it is stubbed here; what
    these hold is the part this module actually owns — who gets cut, what the
    window is made of, and what a rebuild of it removes.
    """

    @staticmethod
    def _stub(monkeypatch: pytest.MonkeyPatch, calls: list, ok: bool = True):
        """Stand in for `make -C <repo> wt-headless`, saying what it would say."""

        def fake(args: list[str], cwd=None) -> tuple[bool, str]:
            calls.append(args)
            name = next(a.split("=", 1)[1] for a in args if a.startswith("NAME="))
            if ok:
                (Path(args[2]) / ".claude" / "worktrees" / name).mkdir(parents=True, exist_ok=True)
            recipe = 'WT_REPO_DIR="' + args[2] + '" bash wt.sh headless'
            return ok, f"{recipe}\n[wt] worktree ready: {name}\n"

        monkeypatch.setattr(workspace, "run_capture", fake)
        return fake

    def test_no_repos_flag_means_every_repo(self, fleet: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The whole point: `make wt-new NAME=x` takes no second argument."""
        workspace.main(["--root", str(fleet), "setup"])
        calls: list = []
        self._stub(monkeypatch, calls)

        code = workspace.main(["--root", str(fleet), "wt-set", "wide", "--headless"])

        assert code == 0
        assert [args[3] for args in calls] == ["wt-headless"] * 2, "the cut must not recurse through wt-new"
        assert {Path(args[2]).name for args in calls} == {"alpha", "beta"}

    def test_reuse_is_forwarded_to_every_repo(self, fleet: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """REUSE=1 is what lets wt.sh continue an existing branch instead of refusing it."""
        workspace.main(["--root", str(fleet), "setup"])
        calls: list = []
        self._stub(monkeypatch, calls)

        assert workspace.main(["--root", str(fleet), "wt-set", "shared", "--headless", "--reuse"]) == 0

        assert all("REUSE=1" in args for args in calls)
        # Appended, never inserted: the target is read positionally at [3].
        assert [args[3] for args in calls] == ["wt-headless"] * 2

        calls.clear()
        assert workspace.main(["--root", str(fleet), "wt-set", "fresh", "--headless"]) == 0
        assert not any("REUSE=1" in args for args in calls), "a plain cut must never reuse"

    def test_an_uncloned_repo_is_skipped_when_the_workspace_is_implied(
        self, fleet: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """A machine missing a sibling must not lose the command that means 'all'."""
        workspace.main(["--root", str(fleet), "setup"])
        shutil.rmtree(fleet / "beta")
        calls: list = []
        self._stub(monkeypatch, calls)

        code = workspace.main(["--root", str(fleet), "wt-set", "partial", "--headless"])
        out = capsys.readouterr().out

        assert code == 0
        assert [Path(args[2]).name for args in calls] == ["alpha"]
        assert "beta: not cloned — skipped" in out

    def test_naming_an_uncloned_repo_is_a_failure(
        self, fleet: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Asking for it by name and silently not getting it is the bad case."""
        workspace.main(["--root", str(fleet), "setup"])
        shutil.rmtree(fleet / "beta")
        self._stub(monkeypatch, [])

        code = workspace.main(["--root", str(fleet), "wt-set", "named", "--repos", "alpha beta", "--headless"])

        assert code == 1
        assert "could not cut 'named' in: beta" in capsys.readouterr().out

    def test_the_window_is_one_file_over_every_worktree(self, fleet: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        workspace.main(["--root", str(fleet), "setup"])
        self._stub(monkeypatch, [])

        workspace.main(["--root", str(fleet), "wt-set", "one-window", "--headless"])

        spec = json.loads((fleet / ".worktrees" / "one-window.code-workspace").read_text())
        folders = [f["path"] for f in spec["folders"]]
        assert [f["name"] for f in spec["folders"]] == ["alpha", "beta"], "manifest order"
        assert folders == [str(fleet / n / ".claude" / "worktrees" / "one-window") for n in ("alpha", "beta")]

        (task,) = spec["tasks"]["tasks"]
        assert task["options"]["cwd"] == folders[0], "the session starts in the first repo…"
        assert folders[1] in task["command"] and "--add-dir" in task["command"], "…and can see the rest"
        assert spec["settings"]["task.allowAutomaticTasks"] == "on", "else VS Code asks before starting claude"

    def test_a_pre_existing_folder_task_is_removed(self, fleet: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A `wt-one` worktree joining a set would otherwise start a second
        claude of its own beside the workspace-level one."""
        workspace.main(["--root", str(fleet), "setup"])
        self._stub(monkeypatch, [])
        stale = fleet / "alpha" / ".claude" / "worktrees" / "reused" / ".vscode"
        stale.mkdir(parents=True)
        (stale / "tasks.json").write_text('{"tasks": [{"runOptions": {"runOn": "folderOpen"}}]}')

        workspace.main(["--root", str(fleet), "wt-set", "reused", "--headless"])

        assert not (stale / "tasks.json").exists()

    def test_a_succeeding_repo_s_output_loses_what_only_fits_one_repo(self) -> None:
        """Five copies of make's recipe line and of wt.sh's background-agent note
        bury the five lines that say a worktree is ready."""
        noisy = (
            'WT_REPO_DIR="/x" CODE="code" bash .tooling/scripts/wt.sh "f" headless\n'
            "[wt] worktree ready: /x/.claude/worktrees/f\n"
            "[wt] headless — no VS Code auto-launch; drive it with a background agent\n"
        )

        assert workspace.tidy(noisy).splitlines() == ["[wt] worktree ready: /x/.claude/worktrees/f"]

    def test_a_failing_repo_keeps_every_line(
        self, fleet: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Whatever is diagnostic about a failure is in the part tidy() removes."""
        workspace.main(["--root", str(fleet), "setup"])
        self._stub(monkeypatch, [], ok=False)

        code = workspace.main(["--root", str(fleet), "wt-set", "broken", "--headless"])
        out = capsys.readouterr().out

        assert code == 1
        assert "could not cut 'broken' in: alpha, beta" in out
        assert "WT_REPO_DIR=" in out, "the recipe line tidy() drops is where a failure says what it ran"

    def test_removing_a_set_takes_its_window_with_it(self, fleet: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        workspace.main(["--root", str(fleet), "setup"])
        self._stub(monkeypatch, [])
        workspace.main(["--root", str(fleet), "wt-set", "gone", "--headless"])
        for name in ("alpha", "beta"):
            (fleet / name / ".claude" / "worktrees" / "gone" / ".git").write_text("gitdir: elsewhere\n")
        spec = fleet / ".worktrees" / "gone.code-workspace"
        assert spec.is_file()

        removals: list = []
        self._stub(monkeypatch, removals)
        code = workspace.main(["--root", str(fleet), "wt-set-rm", "gone"])

        assert code == 0
        assert [args[3] for args in removals] == ["wt-one-rm"] * 2, "wt-rm here would recurse"
        assert not spec.exists()


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


class TestWorktreeSiblings:
    """The guard that stops a feature shipping from one repo of a set."""

    @staticmethod
    def _cut(fleet: Path, repo: str, name: str) -> Path:
        tree = fleet / repo / ".claude" / "worktrees" / name
        tree.mkdir(parents=True)
        (tree / ".git").write_text("gitdir: elsewhere\n")
        return tree

    def test_a_sibling_owing_work_fails_the_check(
        self, fleet: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        workspace.main(["--root", str(fleet), "setup"])
        for repo in ("alpha", "beta"):
            self._cut(fleet, repo, "desktop/feature")
        monkeypatch.setattr(workspace, "unshipped", lambda path: "3 commit(s) ahead")
        capsys.readouterr()

        rc = workspace.main(["--root", str(fleet), "wt-siblings", "desktop/feature"])
        out = capsys.readouterr().out

        assert rc == 1, "a sibling still owing work must fail, not merely advise"
        assert "still owe work" in out
        assert "alpha" in out and "beta" in out

    def test_a_clean_set_passes(
        self, fleet: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        workspace.main(["--root", str(fleet), "setup"])
        self._cut(fleet, "alpha", "solo-feature")
        monkeypatch.setattr(workspace, "unshipped", lambda path: "clean")
        capsys.readouterr()

        assert workspace.main(["--root", str(fleet), "wt-siblings", "solo-feature"]) == 0

    def test_an_unknown_name_is_not_a_failure(self, fleet: Path, capsys: pytest.CaptureFixture) -> None:
        workspace.main(["--root", str(fleet), "setup"])
        capsys.readouterr()
        assert workspace.main(["--root", str(fleet), "wt-siblings", "never-cut"]) == 0
