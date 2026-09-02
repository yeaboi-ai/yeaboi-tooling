"""Guards for the shared devkit: the plugin manifests, the Make-target contract, the commands.

Nothing here imports anything — these are repo-reading guards. They exist because
the devkit's failure mode is silence: a command that names a Make target no repo
defines simply does nothing useful, in four repos at once.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "yeaboi-devkit"
COMMANDS = sorted((PLUGIN / "commands").glob("*.md"))
AGENTS = sorted((PLUGIN / "agents").glob("*.md"))
PROSE = COMMANDS + AGENTS


def _read(path: Path) -> str:
    return path.read_text()


class TestManifests:
    def test_marketplace_points_at_a_real_plugin(self):
        market = json.loads(_read(ROOT / ".claude-plugin" / "marketplace.json"))
        assert market["plugins"], "the marketplace lists no plugins"
        for entry in market["plugins"]:
            source = entry["source"]
            assert source.startswith("./"), f"{source!r} must be a marketplace-root-relative path"
            manifest = ROOT / source / ".claude-plugin" / "plugin.json"
            assert manifest.is_file(), f"{source} has no .claude-plugin/plugin.json"
            assert json.loads(_read(manifest))["name"] == entry["name"], (
                "the marketplace entry and the plugin manifest disagree on the plugin name — "
                "`enabledPlugins` keys are `<plugin>@<marketplace>` and would silently never match"
            )

    def test_component_directories_are_at_the_plugin_root(self):
        """Not inside .claude-plugin/ — that layout loads nothing, with no error."""
        for name in ("commands", "agents", "skills", "hooks", "scripts"):
            assert (PLUGIN / name).is_dir(), f"plugins/yeaboi-devkit/{name}/ is missing"
            assert not (PLUGIN / ".claude-plugin" / name).exists()

    def test_every_skill_declares_its_frontmatter(self):
        for skill in sorted((PLUGIN / "skills").glob("*/SKILL.md")):
            text = _read(skill)
            assert text.startswith("---\n"), f"{skill.name} has no frontmatter"
            head = text.split("---", 2)[1]
            for key in ("name:", "description:"):
                assert key in head, f"{skill.parent.name}/SKILL.md is missing {key}"


class TestHooks:
    def test_every_hook_command_resolves_to_a_script_that_exists(self):
        hooks = json.loads(_read(PLUGIN / "hooks" / "hooks.json"))["hooks"]
        seen = 0
        for event, matchers in hooks.items():
            for matcher in matchers:
                for hook in matcher["hooks"]:
                    command = hook["command"]
                    command = command if isinstance(command, str) else command[0]
                    match = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}\"?(/[\w./-]+)", command)
                    assert match, f"{event} hook does not anchor its script on ${{CLAUDE_PLUGIN_ROOT}}: {command!r}"
                    script = PLUGIN / match.group(1).lstrip("/")
                    assert script.is_file(), f"{event} hook points at {script}, which does not exist"
                    seen += 1
        assert seen >= 2, "the format and verify hooks should both be declared"

    @pytest.mark.parametrize("script", sorted((PLUGIN / "scripts").glob("*.sh")), ids=lambda p: p.name)
    def test_hook_scripts_are_executable(self, script: Path):
        """A plugin ships file modes; a non-executable hook fails once per turn, quietly."""
        assert script.stat().st_mode & stat.S_IXUSR, f"chmod +x {script.relative_to(ROOT)}"

    def test_the_stop_hook_only_calls_targets_the_contract_promises(self):
        text = _read(PLUGIN / "scripts" / "verify-stop.sh")
        called = set(re.findall(r"^run (\w[\w-]*)$", text, re.MULTILINE))
        assert called, "the Stop hook runs no targets at all"
        assert called <= required_targets(), (
            f"the Stop hook calls {called - required_targets()}, which no repo promises"
        )

    def test_the_stop_hook_cannot_loop(self):
        assert "stop_hook_active" in _read(PLUGIN / "scripts" / "verify-stop.sh"), (
            "without the stop_hook_active guard a failing verification blocks forever"
        )


class TestTheStashGuard:
    """The PreToolUse hook that keeps one worktree off another's stashed work.

    Worktrees share a .git and therefore one stash stack; `git stash pop` takes
    the top entry — routinely somebody else's — and deletes it. The guard has to
    block that spelling while leaving the safe ones, and every wrapper it names
    has to exist.
    """

    GUARD = PLUGIN / "scripts" / "guard-stash.sh"

    @pytest.fixture
    def shared_stack(self, tmp_path: Path) -> Path:
        """A repo with two worktrees — the only shape where the hazard exists.

        Not this checkout: CI clones a single working tree, so a guard that is
        (correctly) inert there would make every block case pass vacuously.
        """
        repo = tmp_path / "repo"
        env = {**os.environ, "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "GIT_CONFIG_SYSTEM": os.devnull}
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
        (repo / "f.txt").write_text("one\n")
        for args in (["add", "-A"], ["-c", "user.email=t@e.com", "-c", "user.name=t", "commit", "-qm", "one"]):
            subprocess.run(["git", "-C", str(repo), *args], check=True, env=env)
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "-q", str(tmp_path / "wt"), "-b", "wt"], check=True, env=env
        )
        return repo

    def _verdict(self, command: str, cwd: Path) -> int:
        payload = json.dumps({"tool_input": {"command": command}})
        return subprocess.run(
            ["bash", str(self.GUARD)],
            input=payload,
            capture_output=True,
            text=True,
            cwd=cwd,
        ).returncode

    def test_it_is_registered_as_a_pretooluse_bash_hook(self):
        hooks = json.loads(_read(PLUGIN / "hooks" / "hooks.json"))["hooks"]
        assert "PreToolUse" in hooks, "the stash guard is not wired to any event"
        assert any(m.get("matcher") == "Bash" for m in hooks["PreToolUse"])

    @pytest.mark.parametrize(
        "command",
        [
            "git stash pop",
            "git stash",
            "cd sub && git stash pop",
            "git stash apply stash@{0}",
            "git stash drop",
            "git stash clear",
        ],
    )
    def test_it_blocks_the_spellings_that_can_take_another_worktree_s_work(self, command: str, shared_stack: Path):
        # Exit 2 is what returns stderr to Claude, turning this into a redirect.
        assert self._verdict(command, shared_stack) == 2, f"{command!r} was allowed"

    @pytest.mark.parametrize(
        "command",
        [
            "git stash list",
            "git stash show",
            'git stash push -u -m "wt:feature"',
            "git stash apply 8f3a91c2b4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9",
            "git status",
            "ls -la",
        ],
    )
    def test_it_allows_the_safe_spellings(self, command: str, shared_stack: Path):
        assert self._verdict(command, shared_stack) == 0, f"{command!r} was blocked"

    def test_it_is_inert_in_a_repo_with_one_working_tree(self, tmp_path: Path):
        """This plugin ships to repos that never use worktrees; the hazard is theirs to not have."""
        subprocess.run(["git", "init", "-q", str(tmp_path / "solo")], check=True)
        assert self._verdict("git stash pop", tmp_path / "solo") == 0

    def test_the_message_names_wrappers_that_exist(self, shared_stack: Path):
        out = subprocess.run(
            ["bash", str(self.GUARD)],
            input=json.dumps({"tool_input": {"command": "git stash pop"}}),
            capture_output=True,
            text=True,
            cwd=shared_stack,
        )
        named = set(re.findall(r"make ([a-z][a-z-]*)", out.stderr))
        assert named, "the block message points nowhere"
        assert named <= provided_targets() | required_targets(), (
            f"the guard points at {named - provided_targets() - required_targets()}, which no repo provides"
        )


def required_targets() -> set[str]:
    """The targets `mk/common.mk` says every repo must define."""
    line = re.search(r"^TOOLING_REQUIRED_TARGETS \?= (.+)$", _read(ROOT / "mk" / "common.mk"), re.MULTILINE)
    assert line, "mk/common.mk no longer declares TOOLING_REQUIRED_TARGETS"
    return set(line.group(1).split())


def provided_targets() -> set[str]:
    """Every target the shared mk fragments define."""
    found: set[str] = set()
    for fragment in sorted((ROOT / "mk").glob("*.mk")):
        found |= set(re.findall(r"^([a-z][\w-]*):", _read(fragment), re.MULTILINE))
    return found


class TestTheMakeInterface:
    """The plugin speaks to a repo only through Make. A typo'd target is silence."""

    def test_every_target_the_prose_invokes_is_provided_or_required(self):
        known = provided_targets() | required_targets()
        offenders: list[str] = []
        for path in PROSE:
            for n, line in enumerate(_read(path).splitlines(), 1):
                for target in re.findall(r"`make ([a-z][\w-]*)", line):
                    if target not in known:
                        offenders.append(f"{path.relative_to(ROOT)}:{n}: make {target}")
        assert not offenders, (
            "these call Make targets that neither mk/*.mk provides nor TOOLING_REQUIRED_TARGETS "
            "demands of every repo, so they do nothing in a repo that never defined them:\n" + "\n".join(offenders)
        )

    def test_the_prose_never_calls_the_shared_scripts_by_path(self):
        """`.tooling/` is a pinned clone whose layout is ours to change; `make` is the interface."""
        offenders = [
            f"{path.relative_to(ROOT)}:{n}: {line.strip()}"
            for path in PROSE
            for n, line in enumerate(_read(path).splitlines(), 1)
            if re.search(r"bash\s+\.?\S*scripts/(wt|wt-list|wt-issue|contracts|tooling-sync)\.sh", line)
        ]
        assert not offenders, "call the Make target instead:\n" + "\n".join(offenders)

    def test_the_prose_does_not_reach_into_a_repo_s_own_toolchain(self):
        """`uv run …` in a shared command assumes every repo is the Python one."""
        offenders = [
            f"{path.relative_to(ROOT)}:{n}: {line.strip()}"
            for path in PROSE
            for n, line in enumerate(_read(path).splitlines(), 1)
            if re.search(r"\b(uv run|npm run|pytest)\b", line)
        ]
        assert not offenders, (
            "these hardcode one repo's toolchain; go through a Make target so the same command "
            "works in the front-end, desktop and site repos:\n" + "\n".join(offenders)
        )

    def test_agents_are_referred_to_by_name_not_by_path(self):
        """`.claude/agents/x.md` stopped being where these live when they moved into the plugin."""
        offenders = [
            f"{path.relative_to(ROOT)}:{n}"
            for path in PROSE
            for n, line in enumerate(_read(path).splitlines(), 1)
            if ".claude/agents/" in line
        ]
        assert not offenders, "the plugin's agents are addressed by name:\n" + "\n".join(offenders)


class TestTheFragmentsAreSafeToInclude:
    """A shared fragment is parsed by four repos; its mistakes are everyone's."""

    @pytest.mark.parametrize("fragment", sorted((ROOT / "mk").glob("*.mk")), ids=lambda p: p.name)
    def test_no_recipe_line_names_the_make_variable(self, fragment: Path):
        """GNU make *executes* such a line under --dry-run, so a probe recurses forever."""
        offenders = [
            f"{fragment.name}:{n}: {line.strip()}"
            for n, line in enumerate(_read(fragment).splitlines(), 1)
            if line.startswith("\t") and ("$(MAKE)" in line or "${MAKE}" in line)
        ]
        assert not offenders, "recipe lines must call plain `make`:\n" + "\n".join(offenders)

    def test_the_target_probe_reads_one_line(self):
        """--dry-run prints the recipe, so the probe's own text is part of its input."""
        assert "head -1" in _read(ROOT / "mk" / "common.mk"), (
            "tooling-check's probe no longer anchors to a single line — a recipe that reaches it "
            "feeds this recipe's text back in, and the comparison then matches itself"
        )


class TestNoCommandTrustsLocalMain:
    """`git diff main...HEAD` in a worktree reviews somebody else's merged PRs."""

    STALE = re.compile(r"(?<!origin/)\bmain\.\.\.|git (diff|rebase|merge) main\b|\.\.\.main\b")

    @pytest.mark.parametrize("path", PROSE, ids=lambda p: p.name)
    def test_the_base_ref_is_always_remote(self, path: Path):
        offenders = [
            f"{path.relative_to(ROOT)}:{n}: {line.strip()}"
            for n, line in enumerate(_read(path).splitlines(), 1)
            if self.STALE.search(line)
        ]
        assert not offenders, (
            "these reference local `main`, which in a worktree is routinely several commits behind "
            "origin/main. Use `origin/main`:\n" + "\n".join(offenders)
        )


class TestShipRunsTheGate:
    SHIP = PLUGIN / "commands" / "ship.md"

    def test_ship_names_the_gate(self):
        assert "make ship-gate" in _read(self.SHIP)

    def test_ship_checks_the_rest_of_the_worktree_set(self):
        """`make wt-new` cuts a feature in every repo; /ship works one repo at a
        time. Without this check a feature ships from one repo and the rest of
        the set is forgotten — which has happened, to a vendored contract."""
        text = _read(self.SHIP)
        assert "wt-siblings" in text, "/ship must look for the rest of the set before opening a PR"
        assert "dependency order" in text, "/ship must say which repo of a set goes first"

    def test_ship_fetches_and_rebases_before_verifying(self):
        text = _read(self.SHIP)
        assert "git fetch origin" in text, "/ship must fetch — it verified stale trees for months without one"
        assert "git rebase origin/main" in text
        # The gate has to come after the rebase, or it proves something about a
        # tree that will not exist after merge. Compare against the fenced
        # *invocation*, not the first mention — the intro names the gate too.
        fenced = re.search(r"^[ \t]*```\n[ \t]*make ship-gate\n[ \t]*```", text, re.MULTILINE)
        assert fenced, "the gate should be shown as a single fenced command"
        assert text.index("git rebase origin/main") < fenced.start()

    def test_the_review_is_backgrounded(self):
        assert "BACKGROUND" in _read(self.SHIP) or "in the background" in _read(self.SHIP).lower()

    def test_ship_and_sync_main_defer_repo_facts_to_repo_notes(self):
        """The procedure is shared; the facts are not. Inlining one repo's facts breaks the others."""
        for name in ("ship.md", "sync-main.md"):
            assert ".claude/repo-notes.md" in _read(PLUGIN / "commands" / name), (
                f"{name} no longer points at the per-repo notes — either it inlined a repo's facts, "
                "or the seam was renamed and this guard is the only thing that noticed"
            )


class TestBootstrap:
    HEAD = ROOT / "bootstrap" / "Makefile.head"
    SYNC = ROOT / "bootstrap" / "tooling-sync.sh"

    def test_the_makefile_head_includes_the_shared_fragment(self):
        text = _read(self.HEAD)
        assert "include $(TOOLING)/mk/common.mk" in text
        assert ".DEFAULT_GOAL" in text, (
            "an include brings targets with it and the first target wins the default goal — "
            "without this, a bare `make` cuts a worktree"
        )

    def test_the_pin_reads_do_not_leak_to_stderr(self):
        """`< missing 2>/dev/null` silences the command, not the shell's redirection.

        A fresh worktree has no `.tooling/`, so the read misses on the very first
        `make` — and printed a "No such file or directory" line above the sync it
        was about to do anyway.
        """
        for line in _read(self.HEAD).splitlines():
            if line.startswith(("TOOLING_REV", "TOOLING_HAVE")):
                assert "cat " in line and "2>/dev/null |" in line, (
                    f"read the pin through `cat … 2>/dev/null | tr`, not a `<` redirection: {line}"
                )

    def test_the_head_syncs_before_it_includes(self):
        text = _read(self.HEAD)
        assert text.index("tooling-sync.sh") < text.index("include $(TOOLING)/mk/common.mk"), (
            "the include would fail on a fresh worktree, where .tooling/ does not exist yet"
        )

    def test_the_bootstrap_and_the_fragment_agree_on_the_defaults(self):
        sync, common = _read(self.SYNC), _read(ROOT / "mk" / "common.mk")
        for pattern in (r"TOOLING_DIR:-(\.tooling)", r"TOOLING_REPO:-(\S+?)\}"):
            match = re.search(pattern, sync)
            assert match, f"{pattern} no longer appears in bootstrap/tooling-sync.sh"
            assert match.group(1) in common, (
                f"bootstrap/tooling-sync.sh uses {match.group(1)!r} and mk/common.mk does not — "
                "the two halves of the pin would look in different places"
            )

    def test_check_mode_refuses_a_drifted_copy(self):
        """The bootstrap is copied into every repo, so it is the one file that can rot silently."""
        text = _read(self.SYNC)
        assert "--check" in text and "has drifted from" in text
