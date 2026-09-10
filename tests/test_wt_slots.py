"""Tests for scripts/wt_slots.py — the per-worktree port block and data home.

Worktrees share a machine, so without a slot they share every fixed port and
everything under ~/.yeaboi. The properties worth pinning are the ones whose
failure is silent: two worktrees agreeing on one slot, a service walking out of
its block into a neighbour's, a generated file that make and sh read differently,
and a data home nested where Settings -> Data Dir would sweep it away.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import wt_slots  # noqa: E402

# Run in a subprocess by TestConcurrency: an out-of-process racer is the only
# honest test of a file lock.
_ALLOCATE_ONE = (
    f"import sys; sys.path.insert(0, {str(SCRIPTS)!r}); import wt_slots; print(wt_slots.allocate(sys.argv[1]))"
)


@pytest.fixture(autouse=True)
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Never the developer's real registry — allocation has side effects."""
    path = tmp_path / "slots.json"
    monkeypatch.setenv("YEABOI_WT_SLOTS_FILE", str(path))
    return path


class TestAllocation:
    def test_the_first_worktree_gets_slot_one(self) -> None:
        assert wt_slots.allocate("first") == 1

    def test_slot_zero_is_never_handed_out(self) -> None:
        # Slot 0 is the main checkout: it emits no file and keeps every default.
        assert all(wt_slots.allocate(f"w{i}") != 0 for i in range(5))

    def test_the_same_name_twice_gets_the_same_slot(self) -> None:
        assert wt_slots.allocate("feature/x") == wt_slots.allocate("feature/x")

    def test_lowest_free_fills_the_hole_a_removal_left(self) -> None:
        wt_slots.allocate("a"), wt_slots.allocate("b"), wt_slots.allocate("c")
        wt_slots.release("b")
        assert wt_slots.allocate("d") == 2

    def test_release_is_idempotent(self) -> None:
        wt_slots.allocate("a")
        wt_slots.release("a")
        wt_slots.release("a")  # every repo's wt-rm calls this for one name
        assert wt_slots.get("a") is None

    def test_exhaustion_names_the_way_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wt_slots, "MAX_SLOT", 2)
        wt_slots.allocate("a"), wt_slots.allocate("b")
        with pytest.raises(RuntimeError, match="wt-list"):
            wt_slots.allocate("c")


class TestConcurrency:
    """`make wt-new` fans out across five repos in a thread pool."""

    def _race(self, registry: Path, names: list[str]) -> list[str]:
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", _ALLOCATE_ONE, name],
                stdout=subprocess.PIPE,
                text=True,
                env={**os.environ, "YEABOI_WT_SLOTS_FILE": str(registry)},
            )
            for name in names
        ]
        return [p.communicate()[0].strip() for p in procs]

    def test_racing_processes_get_distinct_slots(self, registry: Path) -> None:
        # Separate processes, not threads: a lock that only excludes threads
        # would pass a threaded test and still corrupt the registry here.
        out = self._race(registry, [f"w{i}" for i in range(12)])
        assert len(set(out)) == 12, out

    def test_five_repos_cutting_one_name_agree_on_one_slot(self, registry: Path) -> None:
        out = self._race(registry, ["one-feature"] * 5)
        assert len(set(out)) == 1, out


class TestPortMath:
    def test_no_walk_can_leave_its_slot(self) -> None:
        # retro and poker walk upward by 20 when their port is busy.
        offsets = [off for off, _key, _default in wt_slots.LAYOUT]
        assert offsets[0] + 20 < offsets[1], "retro's walk reaches poker"
        assert offsets[1] + 20 < offsets[2], "poker's walk reaches the deck"
        assert max(offsets) < wt_slots.BLOCK, "a service sits outside its own block"

    def test_no_port_reaches_the_ephemeral_range(self) -> None:
        # Linux allocates ephemeral ports from 32768, macOS from 49152.
        top = wt_slots.port_base(wt_slots.MAX_SLOT) + max(o for o, _k, _d in wt_slots.LAYOUT)
        assert top < 32768, top

    def test_every_variable_is_unique(self) -> None:
        keys = [key for _off, key, _default in wt_slots.LAYOUT]
        assert len(set(keys)) == len(keys)

    def test_blocks_do_not_overlap(self) -> None:
        assert wt_slots.port_base(2) - wt_slots.port_base(1) == wt_slots.BLOCK


class TestTheDataHome:
    def test_it_is_a_sibling_of_the_real_home_not_a_child(self) -> None:
        # paths.move_data_tree() relocates every CHILD of ~/.yeaboi when the
        # user changes their Data Dir. Nesting worktree homes there would
        # silently sweep them all up and leave every worktree pointing at
        # nothing.
        home = wt_slots.home_for("some-feature")
        assert Path.home() / ".yeaboi" not in home.parents

    def test_a_slashed_name_does_not_escape_the_directory(self) -> None:
        assert wt_slots.home_for("../../etc").parent == Path.home() / ".yeaboi-worktrees"

    def test_purge_home_deletes_the_home_and_only_the_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        home = wt_slots.home_for("desktop/feature")
        home.mkdir(parents=True)
        (home / "state.json").write_text("{}\n")
        sibling = home.parent / "other-feature"
        sibling.mkdir()

        assert wt_slots.purge_home("desktop/feature") is True

        assert not home.exists()
        assert sibling.is_dir(), "a sibling worktree's home went with it"

    def test_purge_home_of_a_home_that_is_not_there_is_a_no_op(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        assert wt_slots.purge_home("never-cut") is False


class TestTheGeneratedFile:
    def _render(self, tmp_path: Path, name: str = "demo") -> Path:
        out = tmp_path / ".worktree.env"
        out.write_text("\n".join(wt_slots.env_lines(name, wt_slots.allocate(name))) + "\n")
        return out

    def test_make_and_sh_read_identical_values(self, tmp_path: Path) -> None:
        # The file is `export K=v` precisely so both readers agree. make strips
        # a trailing `#` comment but KEEPS the whitespace before it, so a
        # commented line would hand make "20300   " where sh sees "20300".
        env_file = self._render(tmp_path)
        keys = [key for _off, key, _default in wt_slots.LAYOUT] + ["YEABOI_HOME", "YEABOI_WT_SLOT"]
        (tmp_path / "Makefile").write_text(
            "-include $(CURDIR)/.worktree.env\nshow:\n\t@printf '%s\\n' " + " ".join(f'"$${k}"' for k in keys) + "\n"
        )
        from_make = subprocess.run(
            ["make", "-s", "show"], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout
        from_sh = subprocess.run(
            ["sh", "-c", f". ./{env_file.name}; printf '%s\\n' " + " ".join(f'"${k}"' for k in keys)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert from_make == from_sh, f"make={from_make!r} sh={from_sh!r}"

    def test_no_line_carries_a_trailing_comment(self, tmp_path: Path) -> None:
        for line in self._render(tmp_path).read_text().splitlines():
            if line.startswith("export"):
                assert "#" not in line, line

    def test_credentials_are_not_redirected(self, tmp_path: Path) -> None:
        # ~/.yeaboi/.env is pinned outside YEABOI_HOME on purpose: one set of
        # API keys serves every worktree.
        body = self._render(tmp_path).read_text()
        assert "YEABOI_HOME=" in body
        assert "ENV_FILE" not in body


class TestReconciling:
    """The registry can lose track of a live worktree; its ports do not care.

    `.worktree.env` is what make actually includes, so a tree whose registry
    entry went missing is still listening on its block. Handing that block to
    the next cut is what produced "Port 20762 is already in use" in a worktree
    that had done nothing wrong.
    """

    def _env(self, tmp_path: Path, name: str, slot: int) -> Path:
        out = tmp_path / wt_slots.slug(name) / ".worktree.env"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(wt_slots.env_lines(name, slot)) + "\n")
        return out

    def test_a_claim_round_trips_through_the_generated_file(self, tmp_path: Path) -> None:
        path = self._env(tmp_path, "desktop/settings-page", 7)
        assert wt_slots.read_claim(path) == ("desktop/settings-page", 7)

    def test_a_file_that_is_not_one_of_ours_claims_nothing(self, tmp_path: Path) -> None:
        stray = tmp_path / ".worktree.env"
        stray.write_text("export SOMETHING=else\n")
        assert wt_slots.read_claim(stray) is None
        assert wt_slots.read_claim(tmp_path / "absent.env") is None

    def test_a_live_tree_keeps_the_slot_it_is_already_serving_on(self) -> None:
        # The registry says 8; the tree on disk — and its running vite — say 7.
        wt_slots.allocate("desktop/settings-page")
        wt_slots.reconcile({"desktop/settings-page": 7})
        assert wt_slots.get("desktop/settings-page") == 7

    def test_a_missing_entry_is_not_free_to_hand_out(self) -> None:
        # 'project-mode-polish' was cut into the hole a per-repo rm punched in
        # the registry, and landed on a slot a live tree was serving from.
        wt_slots.reconcile({"desktop/settings-page": 7, "desktop/tips-ui": 8})
        assert wt_slots.allocate("project-mode-polish") not in (7, 8)

    def test_two_trees_on_one_slot_are_pulled_apart(self) -> None:
        moved = wt_slots.reconcile({"solo-mode": 18, "agents/ai-native-sdlc": 18})
        table = {name: wt_slots.get(name) for name in ("solo-mode", "agents/ai-native-sdlc")}
        assert table["solo-mode"] != table["agents/ai-native-sdlc"]
        # Sorted, so the same tree moves on every machine and on a re-run.
        assert set(moved) == {"solo-mode"}
        assert wt_slots.get("agents/ai-native-sdlc") == 18

    def test_a_claim_that_collides_with_nobody_is_never_moved(self) -> None:
        # The free slot below a live claim: picking it for the loser of an
        # unrelated collision walks that name onto ports 'c' is serving on.
        moved = wt_slots.reconcile({"a": 5, "b": 5, "c": 1})

        assert wt_slots.get("c") == 1, "c was in conflict with nobody"
        assert set(moved) == {"b"}
        assert wt_slots.get("b") not in (1, 5)

    def test_a_name_with_no_live_claim_keeps_its_slot_by_default(self) -> None:
        # It may be a cut still fanning out — its worktrees are not on disk to
        # be scanned yet — or a tree in a second workspace root. Freeing it is
        # exactly the race the up-front allocation exists to avoid.
        wt_slots.allocate("mid-cut")
        wt_slots.reconcile({"still-here": 5})
        assert wt_slots.get("mid-cut") == 1

    def test_collecting_is_what_takes_a_departed_name_off_the_books(self) -> None:
        wt_slots.allocate("shipped-and-removed")
        wt_slots.reconcile({"still-here": 5}, gc=True)
        assert wt_slots.get("shipped-and-removed") is None

    def test_a_live_claim_outranks_a_registry_entry_serving_nothing(self) -> None:
        # Kept entries must not be able to push a real worktree off its ports.
        wt_slots.allocate("ghost")  # slot 1
        assert wt_slots.reconcile({"real": 1}) == {}
        assert wt_slots.get("real") == 1
        assert wt_slots.get("ghost") is None

    def test_reconciling_twice_moves_nothing_the_second_time(self) -> None:
        claims = {"a": 3, "b": 3, "c": 1, "d": 2}
        wt_slots.reconcile(claims)
        settled = {name: wt_slots.get(name) for name in claims}
        assert wt_slots.reconcile(settled) == {}

    def test_a_name_pinned_to_two_slots_yields_to_one_pinned_to_a_single_slot(self) -> None:
        # 'a-split' wins on name alone, but its repos disagree — it is not
        # coherently serving on 7, while 'polish' may be serving on it now.
        moved = wt_slots.reconcile({"a-split": 7, "polish": 7}, unsettled={"a-split"})

        assert wt_slots.get("polish") == 7
        assert set(moved) == {"a-split"}

    def test_an_unsettled_name_keeps_its_slot_when_nothing_contests_it(self) -> None:
        # Losing every collision is not the same as always moving.
        assert wt_slots.reconcile({"quiet": 11}, unsettled={"quiet"}) == {}
        assert wt_slots.get("quiet") == 11
