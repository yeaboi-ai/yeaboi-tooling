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
