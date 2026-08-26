"""Sanity-check a rendered demo GIF.

Shared by both capture backends, because the ways a recording goes wrong are
the same whether the frames came from a terminal or a browser: the take froze,
the page never painted, the per-frame delays were lost in encoding, or the
animation ends on a blank frame that then sits there for the whole README loop.

Bounds are per-spec rather than global — a mostly-monochrome shell transcript
legitimately carries far fewer colours than a TUI or a rendered board.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Bounds:
    """What a sane GIF looks like. Every field is a spec-level override."""

    max_bytes: int = 6 * 1024 * 1024
    frames: tuple[int, int] = (50, 1500)
    duration_s: tuple[float, float] = (6.0, 45.0)
    min_distinct_colors: int = 64

    @classmethod
    def from_spec(cls, raw: dict | None) -> Bounds:
        if not raw:
            return cls()
        known = {f: raw[f] for f in ("max_bytes", "frames", "duration_s", "min_distinct_colors") if f in raw}
        for key in ("frames", "duration_s"):
            if key in known:
                known[key] = tuple(known[key])
        unknown = set(raw) - {"max_bytes", "frames", "duration_s", "min_distinct_colors"}
        if unknown:
            raise ValueError(f"unknown verify bound(s): {sorted(unknown)}")
        return cls(**known)


def verify_gif(gif_path: Path, bounds: Bounds | None = None) -> list[str]:
    """Return a list of problems with the GIF; empty means sane."""
    from PIL import Image

    bounds = bounds or Bounds()
    problems: list[str] = []
    if not gif_path.is_file():
        return [f"missing artifact: {gif_path}"]

    size = gif_path.stat().st_size
    if size > bounds.max_bytes:
        problems.append(f"gif is {size} bytes (limit {bounds.max_bytes})")

    # Frames MUST be read via seek(), one at a time: ImageSequence.Iterator
    # yields the same underlying Image object mutated in place, so collecting
    # frames into a list silently reads every one at the last seek position.
    with Image.open(gif_path) as im:
        n = getattr(im, "n_frames", 1)
        if not (bounds.frames[0] <= n <= bounds.frames[1]):
            problems.append(f"gif has {n} frames (expected {bounds.frames[0]}-{bounds.frames[1]})")

        total_ms = 0
        for i in range(n):
            im.seek(i)
            total_ms += im.info.get("duration", 0)
        total_s = total_ms / 1000
        if not (bounds.duration_s[0] <= total_s <= bounds.duration_s[1]):
            problems.append(
                f"gif plays for {total_s:.1f}s (expected {bounds.duration_s[0]}-{bounds.duration_s[1]}s) "
                "— per-frame durations are broken"
            )

        # Mean luminance cannot tell a blank dark screen from a rendered one on
        # a dark theme, but colour richness can: real content uses dozens of
        # palette entries, a blank frame a couple.
        color_peak = 0
        last_colors = 0
        signatures = set()
        for i in sorted({(n - 1) * k // 4 for k in range(5)} if n >= 5 else {0}):
            im.seek(i)
            rgb = im.convert("RGB")
            signatures.add(rgb.tobytes())
            colors = rgb.getcolors(4096)
            count = 4097 if colors is None else len(colors)
            color_peak = max(color_peak, count)
            if i == n - 1:
                last_colors = count

        if len(signatures) < 2:
            problems.append("all sampled frames are identical — frozen recording")
        if color_peak < bounds.min_distinct_colors:
            problems.append(
                f"sampled frames peak at {color_peak} distinct colors "
                f"(expected >= {bounds.min_distinct_colors}) — blank recording"
            )
        elif last_colors < bounds.min_distinct_colors:
            # The final frame is held on every README loop, so a blank one there
            # is the most visible failure of all. The peak check cannot see it.
            problems.append(f"final frame has only {last_colors} distinct colors — the gif ends on a blank screen")

    return problems
