#!/usr/bin/env python3
"""Per-worktree port/state slots — what keeps two worktrees off each other's toes.

Worktrees share a machine, so they share every fixed port and every path under
~/.yeaboi. A *slot* is a small integer owned by one worktree NAME, from which a
block of ports and a private data home are derived. The same name gets the same
slot in all five repos, because `make wt-new` cuts one name across all of them.

Slot 0 is the main checkout: it derives nothing and every variable stays unset,
so a checkout without a .worktree.env behaves exactly as it did before slots
existed.

Used by scripts/wt.sh (which writes the values into <worktree>/.worktree.env)
and by scripts/workspace.py, which allocates once up front so a five-way
parallel fan-out reads one slot instead of racing for five.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

# Ports start clear of the usual dev range and end clear of the ephemeral range
# (Linux allocates those from 32768, macOS from 49152). Slot 63 tops out at
# 26380, which is under both.
PORT_ORIGIN = 20000
BLOCK = 100
MAX_SLOT = 63

# Offset within the block, the variable each consumer reads, and the literal
# that consumer falls back to when the variable is unset. The literal is kept
# here so a test can assert the two never drift apart.
#
# The gaps are load-bearing: retro walks upward by 20 when its port is busy and
# poker does the same, so retro's walk ends at +20 and poker starts at +25.
# Packing these one apart would send retro's first retry straight through
# poker, the deck and the planning range.
LAYOUT = (
    (0, "RETRO_PORT", 5173),  # walks +0..+20
    (25, "POKER_PORT", 5273),  # walks +25..+45
    (50, "DECK_PORT", 5373),
    (55, "SHIP_PORT", 5473),
    (60, "YEABOI_WEB_DEV_PORT", 5399),
    (62, "YEABOI_DESKTOP_DEV_PORT", 5173),
    (65, "YEABOI_PLANNING_PORT", 8000),  # probes +65..+69
    (80, "YEABOI_SITE_PORT", 8899),
)
# +70..+79 and +81..+99 are free. LiveKit is deliberately NOT here: it binds
# 7880/7881/7882 machine-wide, adopts an already-running server on purpose
# (livekit.ts), and keys its config off one shared ~/.yeaboi/livekit.yaml.
PLANNING_RANGE = 5

LOCK_STALE_S = 30.0
_LOCK_DEADLINE_S = 10.0
_LOCK_POLL_S = 0.05


def registry_path() -> Path:
    """Where the name -> slot map lives (overridable so tests never touch ~)."""
    raw = os.getenv("YEABOI_WT_SLOTS_FILE", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".yeaboi" / "worktree-slots.json"


def slug(name: str) -> str:
    """Filesystem-safe form of a worktree name ('desktop/settings' -> 'desktop-settings')."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "wt"


def home_for(name: str) -> Path:
    """The private data home this worktree's runs read and write.

    A SIBLING of ~/.yeaboi, never a child. paths.move_data_tree() relocates
    every child of the root when the user changes their Data Dir, so a worktree
    home nested inside it would be silently swept along and every worktree
    would then point at nothing. ~/.yeaboi/ship/worktrees also already exists
    and means something else entirely.

    Credentials are unaffected either way: ~/.yeaboi/.env is pinned outside
    YEABOI_HOME, so one set of API keys still serves every worktree.
    """
    return Path.home() / ".yeaboi-worktrees" / slug(name)


def port_base(slot: int) -> int:
    return PORT_ORIGIN + slot * BLOCK


def ports_for(slot: int) -> list[tuple[str, int]]:
    """This slot's ports, in layout order."""
    base = port_base(slot)
    return [(key, base + off) for off, key, _default in LAYOUT]


class _Lock:
    """O_EXCL lockfile with stale takeover; guards every registry mutation."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._held = False

    def __enter__(self) -> _Lock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + _LOCK_DEADLINE_S
        while True:
            try:
                fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(fd, str(os.getpid()).encode("ascii"))
                os.close(fd)
                self._held = True
                return self
            except FileExistsError:
                try:
                    age = time.time() - self._path.stat().st_mtime
                except OSError:
                    age = 0.0  # vanished between attempts — retry immediately
                if age > LOCK_STALE_S:
                    self._path.unlink(missing_ok=True)
                    continue
                if time.monotonic() > deadline:
                    raise TimeoutError(f"worktree slot lock is held: {self._path}") from None
                time.sleep(_LOCK_POLL_S)

    def __exit__(self, *exc: object) -> None:
        if self._held:
            self._path.unlink(missing_ok=True)
            self._held = False


def _read(path: Path) -> dict[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): int(v) for k, v in data.items() if isinstance(v, int) and v > 0}


def _write(path: Path, table: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def allocate(name: str) -> int:
    """Return this name's slot, assigning the lowest free one on first sight."""
    path = registry_path()
    with _Lock(path.with_suffix(".lock")):
        table = _read(path)
        if name in table:
            return table[name]
        taken = set(table.values())
        slot = next((n for n in range(1, MAX_SLOT + 1) if n not in taken), 0)
        if slot == 0:
            raise RuntimeError(f"no free worktree slot below {MAX_SLOT}; run `make wt-list` and clean up")
        table[name] = slot
        _write(path, table)
        return slot


def release(name: str) -> None:
    path = registry_path()
    with _Lock(path.with_suffix(".lock")):
        table = _read(path)
        if table.pop(name, None) is not None:
            _write(path, table)


def purge_home(name: str) -> bool:
    """Delete this name's data home; True if something was removed.

    NOT part of release(): the home is shared by the whole set (same name, five
    repos), so a per-repo `wt-one-rm` must never take it — workspace.py calls
    this once, after confirming NO repo still carries the name. Guarded to only
    ever touch a direct child of ~/.yeaboi-worktrees, whatever slug() returns.
    """
    home = home_for(name)
    if home.parent != Path.home() / ".yeaboi-worktrees" or not home.is_dir():
        return False
    shutil.rmtree(home, ignore_errors=True)
    return True


def get(name: str) -> int | None:
    return _read(registry_path()).get(name)


def prune(live: list[str]) -> list[str]:
    """Drop slots whose worktree is gone; returns the names dropped."""
    path = registry_path()
    with _Lock(path.with_suffix(".lock")):
        table = _read(path)
        dead = [n for n in table if n not in set(live)]
        for n in dead:
            del table[n]
        if dead:
            _write(path, table)
        return dead


def env_lines(name: str, slot: int) -> list[str]:
    """The body of <worktree>/.worktree.env.

    `export K=v` is the intersection of two grammars: GNU make reads it as an
    export directive (so every recipe inherits it) and `sh` reads it as an
    export (so `. ./.worktree.env` works for anything not started by make).
    No quotes, no spaces around `=`, and no trailing comments — make strips the
    `#` but keeps the whitespace before it, so a commented line would hand make
    "20300   " where sh sees "20300".
    """
    base = port_base(slot)
    lines = [
        "# GENERATED by .tooling/scripts/wt.sh — this worktree's private ports and",
        "# data home. Gitignored. Regenerate with `make wt-repair NAME=<name>`.",
        "#",
        "# Read by make (-include, in mk/common.mk) and by sh (. ./.worktree.env).",
        f"#   worktree  {name}",
        f"#   slot      {slot}  (this worktree owns {base}-{base + BLOCK - 1})",
        "",
        f"export YEABOI_WT_NAME={name}",
        f"export YEABOI_WT_SLOT={slot}",
        f"export YEABOI_WT_PORT_BASE={base}",
        "",
        "# Credentials stay in ~/.yeaboi/.env, which is pinned outside YEABOI_HOME.",
        f"export YEABOI_HOME={home_for(name)}",
        "",
    ]
    lines += [f"export {key}={port}" for key, port in ports_for(slot)]
    lines.append(f"export YEABOI_PLANNING_PORT_COUNT={PLANNING_RANGE}")
    # YEABOI_DEV_API is deliberately absent: it is the human's override for
    # which board the front end proxies to, and a make variable set from an
    # included file beats one exported in their shell. vite.config.ts defaults
    # it from RETRO_PORT instead.
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for cmd in ("allocate", "get", "release", "env"):
        p = sub.add_parser(cmd)
        p.add_argument("name")
    p_prune = sub.add_parser("prune")
    p_prune.add_argument("live", nargs="*")

    args = parser.parse_args(argv)

    if args.cmd == "allocate":
        print(allocate(args.name))
    elif args.cmd == "get":
        slot = get(args.name)
        if slot is None:
            return 1
        print(slot)
    elif args.cmd == "release":
        release(args.name)
    elif args.cmd == "env":
        print("\n".join(env_lines(args.name, allocate(args.name))))
    elif args.cmd == "prune":
        for name in prune(args.live):
            print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
