"""Guards for the demo recorder.

The recorder itself cannot be exercised in CI — it needs agg, ffmpeg, a
browser and a running surface. What is guarded here is everything that can go
wrong without any of those: a spec that names a key nothing reads, bounds that
silently do not apply, a path that resolves against the wrong directory, and
the alt-screen coupling that would make a shell session unrecordable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "recorder"))
sys.path.insert(0, str(ROOT / "scripts"))

import record  # noqa: E402
import ttyrec  # noqa: E402
from verify import Bounds  # noqa: E402


def write_spec(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "demo_spec.py"
    path.write_text(body)
    return path


MINIMAL = 'SPEC = {"kind": "tty", "gif": "x.gif", "steps": []}'


class TestSpecLoading:
    def test_loads_a_minimal_spec(self, tmp_path):
        spec = record.load_spec(write_spec(tmp_path, MINIMAL))
        assert spec.kind == "tty"
        assert spec.gif == "x.gif"

    def test_unknown_key_is_refused(self, tmp_path):
        # A typo'd key would otherwise be silently ignored and the demo would
        # record something other than what the spec appears to say.
        path = write_spec(tmp_path, 'SPEC = {"kind": "tty", "gif": "x.gif", "steps": [], "colour_scheme": "dark"}')
        with pytest.raises(SystemExit, match="colour_scheme"):
            record.load_spec(path)

    def test_missing_spec_dict_is_refused(self, tmp_path):
        with pytest.raises(SystemExit, match="no SPEC"):
            record.load_spec(write_spec(tmp_path, "NOT_SPEC = {}"))

    def test_missing_file_is_refused(self, tmp_path):
        with pytest.raises(SystemExit, match="no demo spec"):
            record.load_spec(tmp_path / "absent.py")

    def test_root_is_the_spec_dir_not_the_cwd(self, tmp_path):
        # Relative paths in a spec must mean "relative to the repo it describes",
        # or `make demo` and a one-off run from elsewhere disagree.
        spec = record.load_spec(write_spec(tmp_path, MINIMAL))
        assert spec.root == tmp_path


class TestPathResolution:
    def test_relative_cwd_anchors_to_the_spec(self, tmp_path):
        spec = record.load_spec(write_spec(tmp_path, 'SPEC = {"kind": "tty", "gif": "x.gif", "steps": [], "cwd": "."}'))
        assert spec.resolve_cwd(Path("/unused")) == tmp_path.resolve()

    def test_no_cwd_means_a_throwaway_dir(self, tmp_path):
        spec = record.load_spec(write_spec(tmp_path, MINIMAL))
        sentinel = Path("/tmp/sentinel")
        assert spec.resolve_cwd(sentinel) == sentinel

    def test_electron_paths_anchor_to_the_spec(self, tmp_path):
        spec = record.load_spec(
            write_spec(
                tmp_path,
                'SPEC = {"kind": "page", "gif": "x.gif", "steps": [],'
                ' "electron": {"executable": "node_modules/e", "cwd": ".", "args": ["a"]}}',
            )
        )
        block = spec.resolve_electron()
        assert block["executable"] == str(tmp_path.resolve() / "node_modules/e")
        assert block["cwd"] == str(tmp_path.resolve())
        assert block["args"] == ["a"], "args must survive path anchoring untouched"

    def test_electron_absent_stays_none(self, tmp_path):
        assert record.load_spec(write_spec(tmp_path, MINIMAL)).resolve_electron() is None


class TestBounds:
    def test_defaults_are_the_tui_tuned_ones(self):
        assert Bounds.from_spec(None).min_distinct_colors == 64

    def test_a_spec_overrides_one_bound_without_losing_the_rest(self):
        b = Bounds.from_spec({"min_distinct_colors": 8})
        assert b.min_distinct_colors == 8
        assert b.max_bytes == Bounds().max_bytes

    def test_lists_become_tuples(self):
        # A spec is hand-written Python, so a range arrives as a list as often
        # as a tuple; comparisons downstream must not care.
        assert Bounds.from_spec({"frames": [1, 2]}).frames == (1, 2)

    def test_unknown_bound_is_refused(self):
        with pytest.raises(ValueError, match="min_colors"):
            Bounds.from_spec({"min_colors": 8})


class TestAltScreen:
    """A shell session never enters the alternate screen buffer.

    Requiring it unconditionally — as the yeaboi repo's TUI recorder does —
    would fail every take, and truncating the cast at its exit sequence would
    end the recording at the first byte that happened to match.
    """

    def test_watching_off_keeps_writing_past_an_exit_sequence(self, tmp_path):
        cast = ttyrec.CastWriter(tmp_path / "c.cast", cols=80, rows=24, watch_alt_screen=False)
        cast.feed(b"before\x1b[?1049lafter", 1.0)
        cast.close()
        assert "after" in (tmp_path / "c.cast").read_text()

    def test_watching_on_truncates_at_the_exit_sequence(self, tmp_path):
        cast = ttyrec.CastWriter(tmp_path / "c.cast", cols=80, rows=24, watch_alt_screen=True)
        cast.feed(b"before\x1b[?1049lafter", 1.0)
        cast.close()
        body = (tmp_path / "c.cast").read_text()
        assert "before" in body
        assert "after" not in body

    def test_entry_is_seen_across_a_chunk_boundary(self, tmp_path):
        # The escape can be split across two os.read() calls; a carry is what
        # keeps that from reading as "the TUI never started".
        cast = ttyrec.CastWriter(tmp_path / "c.cast", cols=80, rows=24, watch_alt_screen=True)
        cast.feed(b"\x1b[?10", 1.0)
        cast.feed(b"49h", 1.1)
        cast.close()
        assert cast.saw_alt_screen


class TestCastWriter:
    def test_header_carries_the_spec_geometry(self, tmp_path):
        import json

        ttyrec.CastWriter(tmp_path / "c.cast", cols=100, rows=26, title="t").close()
        header = json.loads((tmp_path / "c.cast").read_text().splitlines()[0])
        assert (header["width"], header["height"], header["title"]) == (100, 26, "t")

    def test_split_multibyte_glyph_never_becomes_a_replacement_char(self, tmp_path):
        cast = ttyrec.CastWriter(tmp_path / "c.cast", cols=80, rows=24, watch_alt_screen=False)
        glyph = "🦆".encode()
        cast.feed(glyph[:2], 1.0)
        cast.feed(glyph[2:], 1.01)
        cast.close()
        body = (tmp_path / "c.cast").read_text()
        assert "\\ufffd" not in body.lower()


class TestSharedTargets:
    def test_demo_is_in_the_shared_contract(self):
        # The whole point of the recorder is that every repo has one. If `demo`
        # leaves TOOLING_REQUIRED_TARGETS, a repo can quietly lose its GIF.
        common = (ROOT / "mk" / "common.mk").read_text()
        line = next(ln for ln in common.splitlines() if ln.startswith("TOOLING_REQUIRED_TARGETS"))
        assert "demo" in line.split("=", 1)[1].split()

    def test_demo_mk_defines_every_target_it_documents(self):
        demo_mk = (ROOT / "mk" / "demo.mk").read_text()
        for target in ("demo:", "demo-render:", "demo-check:"):
            assert f"\n{target}" in demo_mk, f"mk/demo.mk is missing {target}"

    def test_demo_mk_supplies_its_own_uv(self):
        # A Node repo's Makefile never defines UV, and the recorder is Python.
        assert "UV ?=" in (ROOT / "mk" / "demo.mk").read_text()

    def test_this_repo_has_a_spec(self):
        assert (ROOT / "demo_spec.py").is_file()
