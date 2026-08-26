"""Record, render and verify a repo's demo GIF.

One entry point for both capture backends. A repo describes its own demo in a
``demo_spec.py`` at its root; this reads it, drives the right backend, and
verifies the result. Every GIF is written into the yeaboi-site checkout, which
is where the site serves them from and where the READMEs point.

    python recorder/record.py            # record + render + verify
    python recorder/record.py --render-only   # re-render from the cast (tty only)
    python recorder/record.py --check-only    # verify what is committed
    python recorder/record.py --spec .demo/clips/x.py --gif out.gif --clip
    python recorder/record.py --spec .demo/clips/x.py --replay   # drive it, render nothing

Needs ``agg`` for terminal demos and ``ffmpeg`` for page demos — but only to
render. ``--replay`` drives the steps and asserts they resolve, which needs
neither, so it is the one mode that runs on a bare CI runner.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ttyrec  # noqa: E402
from verify import Bounds, verify_gif  # noqa: E402

logger = logging.getLogger("recorder")

RECORDER_DIR = Path(__file__).resolve().parent


@dataclass
class Spec:
    """One repo's demo, as declared in its ``demo_spec.py``."""

    kind: str  # "tty" | "page"
    steps: list

    # Filename within the site checkout. A clip is named by `make clip` from
    # its spec filename and writes outside the site, so it leaves this unset.
    gif: str = ""

    # terminal
    cmd: list[str] = field(default_factory=list)
    cast: str = ""
    cols: int = 140
    rows: int = 40
    title: str = ""
    require_alt_screen: bool = True
    cwd: str = ""  # "" -> a fresh temp dir
    env: dict = field(default_factory=dict)
    env_unset: list = field(default_factory=list)
    agg_flags: list | None = None

    # page
    url: str = ""
    width: int = 1280
    height: int = 800
    fps: int = 20
    scale: int = 1
    color_scheme: str = "dark"
    electron: dict | None = None
    ready: str = ""
    ready_timeout: int = 40
    prepare: list = field(default_factory=list)  # run to completion before capturing
    prepare_cwd: str = ""
    serve: list = field(default_factory=list)  # started, then left running
    serve_cwd: str = ""
    serve_ready: str = ""  # a URL to poll until it answers
    quality: int = 90  # screencast JPEG quality
    gif_width: int = 900  # delivery width; a README renders at ~800
    gif_fps: int = 12
    gif_colors: int = 128

    verify: dict = field(default_factory=dict)

    # Where the spec file lives. Relative paths in a spec are anchored here,
    # not to the process cwd, so `make demo` from a repo root and a one-off run
    # from anywhere else resolve a repo-relative path the same way.
    root: Path = Path(".")

    def _at(self, raw: str) -> Path:
        return (self.root / Path(os.path.expandvars(raw)).expanduser()).resolve()

    def resolve_cwd(self, tmp: Path) -> Path:
        return self._at(self.cwd) if self.cwd else tmp

    def resolve_serve_cwd(self) -> Path | None:
        return self._at(self.serve_cwd) if self.serve_cwd else None

    def resolve_prepare_cwd(self) -> Path:
        return self._at(self.prepare_cwd) if self.prepare_cwd else self.root.resolve()

    def resolve_electron(self) -> dict | None:
        """Anchor the Electron block's paths, which are repo-relative in a spec."""
        if not self.electron:
            return None
        block = dict(self.electron)
        for key in ("executable", "cwd"):
            if block.get(key):
                block[key] = str(self._at(block[key]))
        return block

    @property
    def bounds(self) -> Bounds:
        return Bounds.from_spec(self.verify)


def load_spec(path: Path, root: Path | None = None) -> Spec:
    """Load a spec. ``root`` overrides where its relative paths anchor.

    A repo's ``demo_spec.py`` sits at the repo root, so anchoring to the spec's
    own directory is the same thing. A clip sits at ``.demo/clips/<slug>.py``,
    where it is not — ``"cwd": "."`` there would mean the clips directory. The
    clip target passes the repo root so both kinds of spec read the same way.
    """
    import importlib.util

    if not path.is_file():
        sys.exit(f"no demo spec at {path} — every repo with a `demo` target needs one")
    module_spec = importlib.util.spec_from_file_location("demo_spec", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    raw = getattr(module, "SPEC", None)
    if raw is None:
        sys.exit(f"{path} defines no SPEC dict")
    known = {f.name for f in Spec.__dataclass_fields__.values()} - {"root"}
    unknown = set(raw) - known
    if unknown:
        sys.exit(f"{path}: unknown spec key(s) {sorted(unknown)}")
    return Spec(**raw, root=root or path.parent)


def site_root() -> Path:
    """The yeaboi-site checkout — every demo GIF lands there.

    Resolved through the workspace manifest rather than a second copy of the
    sibling-walk, so one repo list stays authoritative.
    """
    import workspace

    root = workspace.workspace_root(os.environ.get("YEABOI_WORKSPACE"))
    for repo in workspace.repos():
        if repo.name == "site":
            found = root / repo.dir
            if (found / "index.html").is_file():
                return found
            sys.exit(f"no yeaboi-site checkout at {found} — run `make workspace-setup`")
    sys.exit("workspace.toml declares no `site` repo")


# --- page backend ------------------------------------------------------------


def _wait_for(url: str, timeout: float = 45.0) -> None:
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2).read(1)
            return
        except urllib.error.HTTPError:
            return  # answered, even if not 200 — the server is up
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"nothing answered at {url} within {timeout}s")


def _npm_install_once() -> None:
    """Install Playwright into the tooling checkout, not into a consuming repo.

    Every repo's `make demo` runs from a pinned `.tooling/`, so the browser and
    its driver are installed once here and none of the five repos gains a
    devDependency for a task they run by hand a few times a year.
    """
    if (RECORDER_DIR / "node_modules" / "playwright").is_dir():
        return
    logger.info("installing the recorder's Playwright (first run only)")
    subprocess.run(["npm", "install", "--silent"], cwd=RECORDER_DIR, check=True)
    subprocess.run(["npx", "playwright", "install", "chromium"], cwd=RECORDER_DIR, check=True)


def capture_page(spec: Spec, frames_dir: Path) -> dict:
    _npm_install_once()
    if spec.prepare:
        cwd = spec.resolve_prepare_cwd()
        logger.info("preparing: %s (cwd=%s)", " ".join(spec.prepare), cwd)
        subprocess.run(spec.prepare, cwd=cwd, check=True, stdout=subprocess.DEVNULL)
    server = None
    if spec.serve:
        cwd = spec.resolve_serve_cwd()
        logger.info("starting: %s (cwd=%s)", " ".join(spec.serve), cwd)
        server = subprocess.Popen(spec.serve, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            _wait_for(spec.serve_ready or spec.url)
        except Exception:
            server.terminate()
            raise
    try:
        payload = {
            "steps": spec.steps,
            "width": spec.width,
            "height": spec.height,
            "fps": spec.fps,
            "scale": spec.scale,
            "color_scheme": spec.color_scheme,
            "electron": spec.resolve_electron(),
            "ready": spec.ready or None,
            "ready_timeout": spec.ready_timeout,
        }
        out = subprocess.run(
            ["node", str(RECORDER_DIR / "pagerec.mjs"), json.dumps(payload), str(frames_dir)],
            cwd=RECORDER_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
        if out.stderr.strip():
            logger.info("pagerec: %s", out.stderr.strip()[-2000:])
        return json.loads(out.stdout.strip().splitlines()[-1])
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()


def assemble_gif(frames_dir: Path, gif_path: Path, spec: Spec) -> None:
    """Frames -> GIF via ffmpeg, keeping the capture's own timing.

    Reads the concat list pagerec.mjs wrote rather than assuming a constant
    frame rate: the screencast delivers frames when the page paints, so a
    fixed -framerate would stretch quiet stretches and compress busy ones.

    palettegen/paletteuse rather than ffmpeg's default quantiser — a UI is
    mostly flat brand colour, and the default 256-colour cube bands the
    gradients while spending entries on colours the page never uses.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        sys.exit("ffmpeg not found — install it with: brew install ffmpeg")
    gif_path.parent.mkdir(parents=True, exist_ok=True)

    concat = frames_dir / "frames.txt"
    palette = frames_dir / "palette.png"
    # A README renders an image at ~800px, so capture width is not delivery
    # width. Scaling here rather than capturing small keeps text crisp.
    scale = f"fps={spec.gif_fps},scale={spec.gif_width}:-1:flags=lanczos"
    read = ["-f", "concat", "-safe", "0", "-i", str(concat)]

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            *read,
            "-vf",
            f"{scale},palettegen=max_colors={spec.gif_colors}:stats_mode=diff",
            str(palette),
        ],
        check=True,
    )
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            *read,
            "-i",
            str(palette),
            "-lavfi",
            f"{scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle",
            "-loop",
            "0",
            str(gif_path),
        ],
        check=True,
    )
    logger.info("gif written: %s (%d bytes)", gif_path, gif_path.stat().st_size)


# --- entry point -------------------------------------------------------------


def resolve_cast(spec: Spec, args) -> Path | None:
    """Where the terminal cast lands. ``None`` means a throwaway temp file.

    Only the last case needs the site checkout, so a clip naming its own
    destination and a replay writing nothing both stay independent of it.
    """
    if args.cast is not None:
        return args.cast
    if args.gif is not None:
        return args.gif.parent / f"{args.gif.stem}.cast.gz"
    if args.replay:
        return None
    return site_root() / (spec.cast or spec.gif.replace(".gif", ".cast.gz"))


def resolve_bounds(spec: Spec, args) -> Bounds:
    """A spec's own bounds win; otherwise a clip gets a lower floor than a demo."""
    if spec.verify:
        return spec.bounds
    return Bounds.for_clip() if args.clip else Bounds()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record/render/verify a repo's demo GIF.")
    parser.add_argument("--spec", type=Path, default=Path("demo_spec.py"))
    parser.add_argument("--gif", type=Path, default=None, help="override the output path")
    parser.add_argument("--cast", type=Path, default=None, help="override the cast path (terminal demos)")
    parser.add_argument("--render-only", action="store_true", help="re-render from the committed cast (tty only)")
    parser.add_argument("--check-only", action="store_true", help="verify what is committed and exit")
    parser.add_argument("--replay", action="store_true", help="drive the steps and assert they resolve; render nothing")
    parser.add_argument(
        "--clip", action="store_true", help="a feature clip: relax the verify floor a full demo assumes"
    )
    parser.add_argument(
        "--root", type=Path, default=None, help="anchor the spec's relative paths here (default: the spec's own dir)"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="[recorder] %(message)s")
    spec = load_spec(args.spec.resolve(), args.root.resolve() if args.root else None)

    # Resolved lazily: the site checkout is only needed when an artifact
    # actually lands in it.
    gif_path = args.gif
    if gif_path is None and not args.replay:
        if not spec.gif:
            sys.exit(f"{args.spec}: no `gif` key — a spec that names no output needs --gif or --replay")
        gif_path = site_root() / spec.gif

    if spec.kind == "tty":
        cast_path = resolve_cast(spec, args)
        if args.replay:
            with tempfile.TemporaryDirectory(prefix="yeaboi-replay-") as tmp:
                ttyrec.record(spec, cast_path or Path(tmp) / "replay.cast.gz")
            return _replayed(spec)
        if not args.check_only:
            if not args.render_only:
                ttyrec.record(spec, cast_path)
            ttyrec.render(cast_path, gif_path, spec.agg_flags)
    elif spec.kind == "page":
        if args.render_only:
            # Page demos commit only the GIF: keeping every PNG frame would add
            # hundreds of megabytes to the site repo. Re-rendering therefore
            # means re-recording, which needs the surface running.
            sys.exit("--render-only is terminal-only; page demos must be re-recorded (make demo)")
        if not args.check_only:
            with tempfile.TemporaryDirectory(prefix="yeaboi-frames-") as tmp:
                frames_dir = Path(tmp)
                result = capture_page(spec, frames_dir)
                if result["frames"] < 2:
                    sys.exit(f"captured only {result['frames']} frame(s) — the page never painted")
                logger.info("captured %d frames over %.1fs", result["frames"], result["seconds"])
                if args.replay:
                    return _replayed(spec)
                assemble_gif(frames_dir, gif_path, spec)
    else:
        sys.exit(f"unknown spec kind: {spec.kind!r} (expected 'tty' or 'page')")

    problems = verify_gif(gif_path, resolve_bounds(spec, args))
    if problems:
        for p in problems:
            logger.error("%s", p)
        return 1
    logger.info("ok — %s (%d bytes)", gif_path, gif_path.stat().st_size)
    return 0


def _replayed(spec: Spec) -> int:
    """Every step resolved. An ``await`` that did not would have raised."""
    logger.info("ok — replayed %d step(s), rendered nothing", len(spec.steps))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
