"""Guards for the feature-clip lane.

A clip is optional by design, which makes every failure mode here a quiet one:
a nudge that turns into a merge gate, a replay that silently renders nothing,
a clip whose relative paths resolve against the wrong directory, or a target
that disappears in the one repo that has no `demo_spec.py`. None of those show
up as a red build on the PR that introduces them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "recorder"))
sys.path.insert(0, str(ROOT / "scripts"))

import clip_nudge  # noqa: E402
import clip_publish  # noqa: E402
import record  # noqa: E402
from verify import Bounds  # noqa: E402


class TestClipBounds:
    def test_clip_floor_is_lower_than_a_demo(self):
        # A demo tours a surface; a clip shows one thing and can be over in
        # three seconds. Without this a good short clip fails verification.
        assert Bounds.for_clip().duration_s[0] < Bounds().duration_s[0]
        assert Bounds.for_clip().frames[0] < Bounds().frames[0]

    def test_clip_keeps_the_ceilings(self):
        # Only the floors move. The size limit is what stops a clip becoming a
        # second demo, and GitHub will not render an oversized GIF inline.
        assert Bounds.for_clip().max_bytes == Bounds().max_bytes
        assert Bounds.for_clip().duration_s[1] == Bounds().duration_s[1]

    def test_a_specs_own_bounds_beat_the_clip_floor(self, tmp_path):
        spec = record.load_spec(_spec(tmp_path, 'SPEC = {"kind":"tty","steps":[],"verify":{"frames":[7,9]}}'))
        args = _Args(clip=True)
        assert record.resolve_bounds(spec, args).frames == (7, 9)

    def test_clip_floor_applies_when_a_spec_declares_none(self, tmp_path):
        spec = record.load_spec(_spec(tmp_path, 'SPEC = {"kind":"tty","steps":[]}'))
        assert record.resolve_bounds(spec, _Args(clip=True)) == Bounds.for_clip()
        assert record.resolve_bounds(spec, _Args(clip=False)) == Bounds()


class TestSpecAnchoring:
    def test_root_override_anchors_at_the_repo_not_the_spec(self, tmp_path):
        # `"cwd": "."` has to mean the repo root in a clip, exactly as it does
        # in a root demo_spec.py. Without --root it would mean .demo/clips/.
        clips = tmp_path / ".demo" / "clips"
        clips.mkdir(parents=True)
        path = clips / "feature.py"
        path.write_text('SPEC = {"kind":"tty","steps":[],"cwd":"."}')

        anchored = record.load_spec(path, root=tmp_path)
        assert anchored.resolve_cwd(tmp_path) == tmp_path.resolve()
        assert record.load_spec(path).resolve_cwd(tmp_path) == clips.resolve()

    def test_gif_is_optional_so_a_clip_carries_no_dead_key(self, tmp_path):
        # `make clip` names the output from the spec filename, so a `gif` key
        # in a clip would be written and never read.
        assert record.load_spec(_spec(tmp_path, 'SPEC = {"kind":"tty","steps":[]}')).gif == ""


class TestNudge:
    GLOBS = ["src/yeaboi/ui/*", "recorder/*", "mk/*.mk"]

    @pytest.mark.parametrize(
        "path,hit",
        [
            ("src/yeaboi/ui/mode_select/__init__.py", True),  # `*` crosses `/`
            ("recorder/record.py", True),
            ("mk/clip.mk", True),
            ("src/yeaboi/pricing.py", False),
            ("README.md", False),
        ],
    )
    def test_surface_matching(self, path, hit):
        assert bool(clip_nudge.first_surface_hit([path], self.GLOBS)) is hit

    def test_undecidable_never_nudges(self):
        # No base/head means no diff to reason about. A false positive is noise
        # on somebody's PR; a false negative costs nothing.
        assert clip_nudge.changed_files("", "") == []


class TestNudgeIsNotAGate:
    def test_the_comment_carries_no_pr_feedback_marker(self):
        # scripts/pr_feedback.py in the yeaboi repo counts `pr-feedback:`
        # markers in PR comments into a MERGE GATE. A nudge that emitted one
        # would turn an optional suggestion into a blocker.
        # Comments are stripped: the prose here explains the trap by naming it,
        # and what matters is that no marker reaches the emitted body.
        emitted = "\n".join(line for line in _workflow().splitlines() if not line.lstrip().startswith("#"))
        assert "clip-nudge" in emitted
        assert "pr-feedback:" not in emitted

    def test_neither_job_is_named_like_a_required_check(self):
        workflow = _workflow()
        # `replay` is skippable per repo; the nudge always exits 0.
        assert "if: inputs.replay" in workflow
        assert "continue-on-error: true" in workflow


class TestPublishUrl:
    def test_url_targets_the_media_branch_under_the_branch_name(self):
        url = clip_publish.RAW.format(
            owner="yeaboi-ai", repo="yeaboi-tooling", branch=clip_publish.MEDIA_BRANCH, path="clips/x/y.gif"
        )
        assert url == "https://raw.githubusercontent.com/yeaboi-ai/yeaboi-tooling/demo-media/clips/x/y.gif"

    def test_the_main_repo_is_named_yeaboi_ai(self):
        # The repo is `yeaboi.ai`, not `yeaboi` — a dot in the path segment
        # that a hand-built URL gets wrong.
        url = clip_publish.RAW.format(
            owner="yeaboi-ai", repo="yeaboi.ai", branch=clip_publish.MEDIA_BRANCH, path="clips/b/c.gif"
        )
        assert "/yeaboi.ai/demo-media/" in url

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("feature/my-thing", "feature/my-thing"),  # a slash is a real path segment
            ("feature/it's brôken", "feature/it-s-br-ken"),
            ("--leading", "leading"),
        ],
    )
    def test_slugify(self, raw, expected):
        assert clip_publish.slugify(raw) == expected


class TestMakeTargets:
    """The targets must exist in a repo with no demo_spec.py.

    mk/demo.mk guards its recipes on a spec existing, because the yeaboi repo
    keeps its own `demo`. Clips must not inherit that guard: the main repo is
    where most features land.
    """

    @pytest.mark.parametrize("target", ["clip", "clip-replay", "clip-list"])
    def test_target_is_defined_without_a_demo_spec(self, tmp_path, target):
        (tmp_path / "Makefile").write_text(f"TOOLING := {ROOT}\ninclude {ROOT}/mk/clip.mk\n")
        proc = subprocess.run(["make", "-n", target], cwd=tmp_path, capture_output=True, text=True)
        assert "No rule to make target" not in proc.stderr
        assert "Nothing to be done" not in proc.stdout

    def test_clip_demands_a_spec(self, tmp_path):
        (tmp_path / "Makefile").write_text(f"TOOLING := {ROOT}\ninclude {ROOT}/mk/clip.mk\n")
        proc = subprocess.run(["make", "clip"], cwd=tmp_path, capture_output=True, text=True)
        assert proc.returncode != 0
        assert "SPEC=" in proc.stdout


def _workflow() -> str:
    return (ROOT / ".github" / "workflows" / "clip-check.yml").read_text()


def _spec(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "demo_spec.py"
    path.write_text(body)
    return path


class _Args:
    """Stand-in for the argparse namespace resolve_bounds reads."""

    def __init__(self, clip: bool = False):
        self.clip = clip
