"""Record a terminal session into an asciinema v2 cast, then render it with agg.

Lifted from the yeaboi repo's ``scripts/record_demo.py``, with the one
generalisation that repo did not need: the alternate screen buffer is now
opt-in. A full-screen TUI enters it and the cast is truncated when it leaves;
a plain shell session never enters it at all, and requiring it there would
fail every take.

Needs a POSIX pty to record and ``agg`` to render (``brew install agg``).
"""

from __future__ import annotations

import codecs
import gzip
import json
import logging
import os
import re
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_ANSI_RE = re.compile(rb"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()][B0]|\x1b[=>]")
_ALT_SCREEN = b"\x1b[?1049h"
_ALT_SCREEN_EXIT = "\x1b[?1049l"

AGG_FLAGS = [
    "--theme",
    "github-dark",
    "--font-size",
    "14",
    "--fps-cap",
    "24",
    "--idle-time-limit",
    "2",
    "--last-frame-duration",
    "2",
]


class CastWriter:
    """Incrementally write an asciinema v2 cast from raw pty bytes.

    Three transforms, all safe because a cast is a replayed byte stream (frame
    boundaries carry no meaning):

    - timestamps are rebased so the first output lands at ~0.1s — process
      startup dead air never reaches the GIF;
    - chunks are coalesced (flush after 25ms or 64KiB) to cut JSON overhead
      without touching payload bytes;
    - decoding is incremental, so a multibyte glyph split across two
      ``os.read()`` calls can never inject U+FFFD mid-escape-sequence.
    """

    FLUSH_AFTER_S = 0.025
    FLUSH_AFTER_BYTES = 64 * 1024
    LEAD_IN_S = 0.1

    def __init__(self, path: Path, cols: int, rows: int, title: str = "", watch_alt_screen: bool = True) -> None:
        self.path = path
        self._fh = gzip.open(path, "wt", encoding="utf-8") if path.suffix == ".gz" else path.open("w", encoding="utf-8")
        header = {
            "version": 2,
            "width": cols,
            "height": rows,
            "timestamp": int(time.time()),
            "env": {"TERM": "xterm-256color", "SHELL": "/bin/sh"},
            "title": title,
        }
        self._fh.write(json.dumps(header) + "\n")
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._t0: float | None = None
        self._buffer = ""
        self._buffer_bytes = 0
        self._buffer_start = 0.0
        self.events = 0
        self.last_t = 0.0
        # Alt-screen entry is the strongest signal a TUI's live terminal path
        # (not a fallback print) is running. Watched here — with a carry across
        # feeds — because the caller's bounded tail may have dropped the early
        # bytes. A shell session never enters it, so watching is opt-out.
        self._watch_alt_screen = watch_alt_screen
        self.saw_alt_screen = False
        self._watch_carry = ""
        # Once a TUI leaves the alt screen (quit), the cast is over: recording
        # the restored bare terminal would hold a blank final GIF frame for
        # --last-frame-duration on every README loop.
        self._ended = False
        self._end_carry = ""

    def feed(self, chunk: bytes, now: float) -> None:
        if self._ended:
            return
        if self._t0 is None:
            self._t0 = now - self.LEAD_IN_S
        text = self._decoder.decode(chunk)
        if not text:
            return

        if self._watch_alt_screen:
            if not self.saw_alt_screen:
                watch = _ALT_SCREEN.decode()
                probe = self._watch_carry + text
                self.saw_alt_screen = watch in probe
                self._watch_carry = probe[-(len(watch) - 1) :]
            probe = self._end_carry + text
            idx = probe.find(_ALT_SCREEN_EXIT)
            if idx >= 0:
                self._ended = True
                # Keep only what precedes the exit sequence. If its head was
                # already written in an earlier feed (idx < carry length), a
                # dangling escape prefix stays in the cast — agg renders
                # nothing for it.
                text = text[: max(idx - len(self._end_carry), 0)]
                if not text:
                    return
            else:
                self._end_carry = probe[-(len(_ALT_SCREEN_EXIT) - 1) :]

        # Flush a stale buffer BEFORE appending: text arriving after a quiet gap
        # must start a fresh event stamped at its own time, or it replays early.
        if self._buffer and now - self._buffer_start >= self.FLUSH_AFTER_S:
            self._flush()
        if not self._buffer:
            self._buffer_start = now
        self._buffer += text
        self._buffer_bytes += len(chunk)
        if self._buffer_bytes >= self.FLUSH_AFTER_BYTES:
            self._flush()

    def _flush(self) -> None:
        if not self._buffer or self._t0 is None:
            return
        t = max(self._buffer_start - self._t0, self.last_t)
        self._fh.write(json.dumps([round(t, 4), "o", self._buffer], ensure_ascii=False) + "\n")
        self.events += 1
        self.last_t = t
        self._buffer = ""
        self._buffer_bytes = 0

    def close(self) -> None:
        self._buffer += self._decoder.decode(b"", final=True)
        self._flush()
        self._fh.close()


def strip_ansi(raw: bytes) -> str:
    return _ANSI_RE.sub(b"", raw).decode("utf-8", errors="replace")


def _spawn(cmd: list[str], cwd: Path | None, env: dict[str, str], cols: int, rows: int):
    """Launch a command attached to a fresh pty; return (proc, master_fd)."""
    import fcntl
    import termios

    master_fd, slave_fd = os.openpty()
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=str(cwd) if cwd else None,
        env=env,
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave_fd)
    return proc, master_fd


def _pump(master_fd, proc, cast, seconds, predicate=None, tail_limit=262_144) -> tuple[bytes, bool]:
    """Drain the pty into the cast for up to ``seconds``.

    Returns (bounded tail of raw bytes, predicate matched?). With a predicate,
    returns as soon as it matches the ANSI-stripped tail; without one, drains
    for the full duration — this is how scripted pauses stay flood-safe, since
    a full-screen child repaints continuously and blocks the moment we stop
    reading. Only the last ``tail_limit`` bytes are kept: re-stripping an
    unbounded buffer every poll throttles the drain quadratically.
    """
    deadline = time.monotonic() + seconds
    tail = b""
    while True:
        now = time.monotonic()
        if now >= deadline:
            return tail, False
        ready, _, _ = select.select([master_fd], [], [], min(0.025, deadline - now))
        if ready:
            try:
                chunk = os.read(master_fd, 65536)
            except OSError:  # pty closed — process exited
                return tail, False
            if not chunk:
                return tail, False
            cast.feed(chunk, time.monotonic())
            tail = (tail + chunk)[-tail_limit:]
            if predicate is not None and predicate(strip_ansi(tail)):
                return tail, True
        elif proc.poll() is not None:
            return tail, False


def record(spec, cast_path: Path) -> None:
    """Run the spec's step script against a fresh pty and write the cast."""
    if sys.platform == "win32":
        sys.exit("the terminal backend needs a POSIX pty; record on macOS or Linux")

    cast_path.parent.mkdir(parents=True, exist_ok=True)
    cast = CastWriter(
        cast_path,
        cols=spec.cols,
        rows=spec.rows,
        title=spec.title,
        watch_alt_screen=spec.require_alt_screen,
    )
    env = {**os.environ, "TERM": "xterm-256color", **spec.env}
    for key in spec.env_unset:
        env.pop(key, None)

    with tempfile.TemporaryDirectory(prefix="yeaboi-demo-") as tmp:
        cwd = spec.resolve_cwd(Path(tmp))
        proc, master_fd = _spawn(spec.cmd, cwd, env, spec.cols, spec.rows)
        try:
            for step in spec.steps:
                kind = step[0]
                if kind == "await":
                    _, markers, timeout = step
                    tail, matched = _pump(
                        master_fd,
                        proc,
                        cast,
                        timeout,
                        predicate=lambda text, _m=markers: any(m in text for m in _m),
                    )
                    if not matched:
                        raise RuntimeError(
                            f"markers {markers} never rendered (exit={proc.poll()}); "
                            f"last output:\n{strip_ansi(tail)[-2000:]}"
                        )
                elif kind == "pause":
                    _pump(master_fd, proc, cast, step[1])
                elif kind == "key":
                    logger.info("key: %r", step[1])
                    os.write(master_fd, step[1])
                elif kind == "type":
                    # Feed a line a character at a time, draining between each.
                    # A shell echoes what it receives, so this is what puts
                    # motion in the cast: writing the whole line at once emits
                    # one event and agg renders it as a single frame.
                    _, text, cps = step
                    delay = 1.0 / cps
                    for ch in text:
                        os.write(master_fd, ch.encode())
                        _pump(master_fd, proc, cast, delay)
                else:
                    raise ValueError(f"unknown script step: {step!r}")

            if spec.require_alt_screen and not cast.saw_alt_screen:
                raise RuntimeError("never entered the alternate screen buffer — not the live terminal path")

            # Drain until EOF so the pty can't block the child's final writes.
            _pump(master_fd, proc, cast, 15.0)
            returncode = proc.wait(timeout=15)
            if returncode != 0:
                raise RuntimeError(f"child did not exit cleanly (returncode={returncode})")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
            os.close(master_fd)
            cast.close()

    logger.info(
        "cast written: %s (%d events, %.1fs, %d bytes)",
        cast_path,
        cast.events,
        cast.last_t,
        cast_path.stat().st_size,
    )


def render(cast_path: Path, gif_path: Path, agg_flags: list[str] | None = None) -> None:
    """Render the GIF from the cast with pinned agg flags."""
    agg = shutil.which("agg")
    if agg is None:
        sys.exit("agg not found — install it with: brew install agg")
    src = cast_path
    if cast_path.suffix == ".gz":
        # agg reads plain casts; inflate the committed .gz to a temp path.
        fd, name = tempfile.mkstemp(suffix=".cast")
        os.close(fd)
        src = Path(name)
        src.write_bytes(gzip.decompress(cast_path.read_bytes()))
    try:
        gif_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [agg, str(src), str(gif_path), *(agg_flags or AGG_FLAGS)]
        logger.info("rendering: %s", " ".join(cmd))
        subprocess.run(cmd, check=True)
    finally:
        if src is not cast_path:
            src.unlink(missing_ok=True)
    logger.info("gif written: %s (%d bytes)", gif_path, gif_path.stat().st_size)

# (throwaway: exercising the clip nudge)
