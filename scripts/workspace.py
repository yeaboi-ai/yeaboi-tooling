#!/usr/bin/env python3
"""workspace.py — the five yeaboi repos, side by side.

One product, five repos, and every seam between them a pin: a wheel on PyPI, a
package on npm, a vendored contract, a tooling sha. This is the local half of
that. It clones them all (`setup`), shows them all at once (`status`), prints
the environment that makes one checkout serve another (`env`), and cuts one
feature's worktree across several of them (`wt-set`).

Reached through `make workspace-*` and `make wt-set*` in mk/common.mk, so it
runs from any repo in the workspace, not only from this one.

No third-party imports, and no `tomllib` either: this must run on whatever
python3 a machine already has, and the system interpreter on macOS is 3.9. The
manifest reader below covers exactly the subset workspace.toml is written in
and raises on anything else; tests/test_workspace.py holds it to tomllib's
answer on the real file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "workspace.toml"

# The one repo that includes `mk/` in place instead of pinning a `.tooling/`
# clone of it — so an absent `.tooling-rev` is correct there and nowhere else.
TOOLING_SLUG = "yeaboi-ai/yeaboi-tooling"

# --- the manifest ------------------------------------------------------------

TABLE = re.compile(r"^\[\[(\w+)\]\]$")
PAIR = re.compile(r'^(\w+) = (".*"|true|false)$')


def _value(raw: str):
    if raw == "true":
        return True
    if raw == "false":
        return False
    body = raw[1:-1]
    if '"' in body or "\\" in body:
        raise ValueError(f"quotes and escapes are not supported in a value: {raw}")
    return body


def read_manifest(text: str, source: str = "workspace.toml") -> dict:
    """Parse the subset of TOML workspace.toml uses, and refuse the rest.

    Returns tomllib's shape: {"repo": [{...}, ...]}. A trailing comment after a
    value raises rather than being stripped — a reader that guesses is worse
    than one that stops.
    """
    rows: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        table = TABLE.match(stripped)
        if table:
            if table.group(1) != "repo":
                raise ValueError(f"{source}:{lineno}: only [[repo]] tables are understood")
            rows.append({})
            continue
        pair = PAIR.match(stripped)
        if pair is None:
            raise ValueError(f"{source}:{lineno}: not a line this reader understands: {stripped!r}")
        if not rows:
            raise ValueError(f"{source}:{lineno}: a key outside any [[repo]] table")
        rows[-1][pair.group(1)] = _value(pair.group(2))
    return {"repo": rows}


@dataclass(frozen=True)
class Repo:
    name: str
    dir: str
    url: str
    toolchain: str
    vendors: bool
    holds: str

    @property
    def slug(self) -> str:
        """owner/name — what actions/checkout wants for another repository."""
        return self.url[len("https://github.com/") :].removesuffix(".git")


def repos() -> list[Repo]:
    out = []
    for row in read_manifest(MANIFEST.read_text(), str(MANIFEST))["repo"]:
        try:
            out.append(Repo(**row))
        except TypeError as exc:  # a missing or unexpected key
            raise SystemExit(f"[workspace] {MANIFEST}: bad [[repo]] row {row!r} — {exc}") from exc
    return out


def select(names: list[str]) -> list[Repo]:
    """Resolve REPOS="yeaboi frontend" — by name or by directory."""
    known = repos()
    index = {r.name: r for r in known} | {r.dir: r for r in known}
    chosen, unknown = [], []
    for name in names:
        repo = index.get(name)
        if repo is None:
            unknown.append(name)
        elif repo not in chosen:
            chosen.append(repo)
    if unknown:
        raise SystemExit(
            f"[workspace] no such repo: {', '.join(unknown)}\n[workspace] known: {', '.join(r.name for r in known)}"
        )
    return chosen


# --- shelling out ------------------------------------------------------------


def git(args: list[str], cwd: Path, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"[workspace] git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}")
    return result.stdout.strip()


def run(args: list[str], cwd: Path | None = None, quiet: bool = False) -> bool:
    """Run a command, report failure, and let the caller decide what it means.

    MAKEFLAGS is dropped: a `make workspace-setup` that inherited `-j` would
    hand it to five nested makes, and two test runs in one worktree invent
    failures.
    """
    # A child writes straight to the terminal while this process buffers, so
    # without the flush every "[workspace] cloning…" line lands after the output
    # of the thing it was announcing.
    sys.stdout.flush()
    env = {k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MAKELEVEL")}
    result = subprocess.run(
        args,
        cwd=None if cwd is None else str(cwd),
        env=env,
        capture_output=quiet,
        text=True,
    )
    if result.returncode != 0 and quiet:
        sys.stdout.write(result.stdout or "")
        sys.stderr.write(result.stderr or "")
    return result.returncode == 0


# --- where the workspace is --------------------------------------------------


def workspace_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("YEABOI_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    return main_checkout(Path.cwd()).parent


def main_checkout(start: Path) -> Path:
    """The MAIN checkout of the repo `start` is in.

    Not `git rev-parse --show-toplevel`: run from a worktree that answers
    `<repo>/.claude/worktrees/<name>`, whose parent is not where the sibling
    repos live. The main worktree is the first `git worktree list` entry.
    """
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(start),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"[workspace] {start} is not inside a git repository — "
            "run this from a yeaboi repo, or pass --root / set YEABOI_WORKSPACE"
        )
    return Path(result.stdout.splitlines()[0].split(" ", 1)[1])


def short(path: Path, name: str) -> str:
    """The first 7 characters of a pin file, or an em dash when there is none."""
    pin = path / name
    if not pin.is_file():
        return "—"
    return pin.read_text().strip()[:7] or "—"


# --- commands ----------------------------------------------------------------


def cmd_setup(args: argparse.Namespace) -> int:
    root = workspace_root(args.root)
    root.mkdir(parents=True, exist_ok=True)
    print(f"[workspace] root: {root}")
    failed = []
    for repo in repos():
        path = root / repo.dir
        if (path / ".git").exists():
            print(f"[workspace] {repo.name}: present")
        else:
            print(f"[workspace] {repo.name}: cloning {repo.url}")
            if not run(["git", "clone", "--quiet", repo.url, str(path)]):
                failed.append(f"{repo.name} (clone)")
                continue
        provision = path / "scripts" / "provision.sh"
        if provision.is_file():
            print(f"[workspace] {repo.name}: provisioning…")
            if not run(["bash", "scripts/provision.sh"], cwd=path):
                failed.append(f"{repo.name} (provision)")
        else:
            print(f"[workspace] {repo.name}: no scripts/provision.sh — nothing to provision")
        # Also materialises `.tooling/` at the pinned sha, so the repo is ready
        # for the devkit plugin's commands and not only for its own toolchain.
        # Checked first, because a checkout old enough to predate the shared
        # tooling fails this with make's own "no rule to make target", which
        # says nothing about what is actually wrong.
        if repo.slug != TOOLING_SLUG and not (path / ".tooling-rev").is_file():
            print(f"[workspace] {repo.name}: no .tooling-rev — this checkout predates the shared tooling")
            print(f"[workspace] {repo.name}: `git -C {path} pull` and re-run")
            failed.append(f"{repo.name} (behind)")
        elif not run(["make", "tooling-check"], cwd=path, quiet=True):
            failed.append(f"{repo.name} (tooling-check)")
    print()
    if failed:
        print(f"[workspace] finished with problems: {', '.join(failed)}")
        print("[workspace] the checkouts that did land are usable; fix the above and re-run")
        return 1
    print("[workspace] every repo is cloned and provisioned.")
    print('[workspace] next: eval "$(make workspace-env)" to wire one checkout to another')
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = workspace_root(args.root)
    print(f"[workspace] root: {root}\n")
    rows, pins, missing, stale = [], set(), [], []
    for repo in repos():
        path = root / repo.dir
        if not (path / ".git").exists():
            rows.append((repo.name, repo.dir, "—", "not cloned", "—", "—"))
            missing.append(repo.name)
            continue
        branch = git(["branch", "--show-current"], path) or "(detached)"
        dirty = git(["status", "--porcelain"], path)
        state = f"{len(dirty.splitlines())} dirty" if dirty else "clean"
        # Local refs only — `status` must stay instant and work on a plane.
        gap = git(["rev-list", "--left-right", "--count", "HEAD...@{u}"], path, check=False)
        if gap:
            ahead, behind = gap.split()
            branch += ("" if ahead == "0" else f" ↑{ahead}") + ("" if behind == "0" else f" ↓{behind}")
        # "self" rather than "—": this repo IS the tooling, so an absent pin
        # here is correct, while an absent one anywhere else is a stale checkout.
        tooling = "self" if repo.slug == TOOLING_SLUG else short(path, ".tooling-rev")
        if tooling not in ("—", "self"):
            pins.add(tooling)
        elif tooling == "—":
            stale.append(repo.name)
        rows.append((repo.name, repo.dir, branch, state, tooling, short(path, ".contracts-rev")))

    head = ("repo", "dir", "branch", "state", "tooling", "contracts")
    widths = [max(len(str(r[i])) for r in [head, *rows]) for i in range(len(head))]
    for row in [head, *rows]:
        # By index rather than zip(): `strict=` is 3.10, and this file's whole
        # licence to be hand-rolled is that it runs on the 3.9 macOS ships.
        print("  " + "  ".join(str(row[i]).ljust(widths[i]) for i in range(len(head))).rstrip())

    print()
    if missing:
        print(f"[workspace] not cloned: {', '.join(missing)} — run: make workspace-setup")
    if stale:
        print(f"[workspace] no .tooling-rev in: {', '.join(stale)} — that checkout is behind its own main.")
    if len(pins) > 1:
        print(f"[workspace] the tooling pin differs across repos ({', '.join(sorted(pins))}).")
        print("[workspace] that is fine while one is being bumped, and a drift otherwise.")
    return 0


def cmd_env(args: argparse.Namespace) -> int:
    """The three cross-repo dev seams, as shell exports.

    Every one of them is a path that must exist: `assets.py` raises rather than
    falling back when YEABOI_WEB_STATIC points at nothing, and an absent
    interpreter turns into a sidecar that will not start. So a seam whose target
    is not built yet is emitted as a comment saying how to build it.
    """
    root = workspace_root(args.root)
    index = {r.name: root / r.dir for r in repos()}
    print('# The cross-repo dev seams. Use as:  eval "$(make workspace-env)"')
    print(f"export YEABOI_WORKSPACE={root}")

    yeaboi = index["yeaboi"]
    print("\n# The desktop shell's dev sidecar: which yeaboi checkout `yeaboi app` runs from.")
    print(f"export YEABOI_REPO={yeaboi}")

    venv = yeaboi / ".venv" / "bin" / "python"
    print("\n# Skips uv resolution on every desktop launch. Optional; YEABOI_REPO alone works.")
    if venv.is_file():
        print(f"export YEABOI_DESKTOP_PYTHON={venv}")
    else:
        print(f"# no {venv} — run `make install` in {yeaboi}")

    static = index["frontend"] / "yeaboi_web_assets" / "static"
    print("\n# Serve the front end's working build instead of the published wheel's.")
    if static.is_dir():
        print(f"export YEABOI_WEB_STATIC={static}")
    else:
        print(f"# no {static} — run `make build` in {index['frontend']}")
    return 0


def cmd_matrix(args: argparse.Namespace) -> int:
    """The nightly's matrix: every repo that vendors a contract from another."""
    print(
        json.dumps(
            [{"name": r.name, "dir": r.dir, "slug": r.slug, "toolchain": r.toolchain} for r in repos() if r.vendors]
        )
    )
    return 0


def worktrees(path: Path) -> list[str]:
    home = path / ".claude" / "worktrees"
    if not home.is_dir():
        return []
    return sorted(p.name for p in home.iterdir() if (p / ".git").exists())


def cmd_wt_set(args: argparse.Namespace) -> int:
    root = workspace_root(args.root)
    chosen = select(args.repos.split())
    target = "wt-headless" if args.headless else "wt-new"
    failed = []
    for repo in chosen:
        path = root / repo.dir
        if not (path / ".git").exists():
            failed.append(f"{repo.name} (not cloned)")
            continue
        print(f"\n[workspace] {repo.name}: make {target} NAME={args.name}")
        if not run(["make", "-C", str(path), target, f"NAME={args.name}"]):
            failed.append(repo.name)
    print()
    if failed:
        print(f"[workspace] could not cut '{args.name}' in: {', '.join(failed)}")
        return 1
    print(f"[workspace] '{args.name}' is cut in {len(chosen)} repo(s).")
    print("[workspace] ship upstream first — the downstream PR carries the new pin.")
    return 0


def cmd_wt_sets(args: argparse.Namespace) -> int:
    """What is cut where, read off disk.

    Nothing records a "set": a recorded one goes stale the moment somebody
    removes a worktree by hand, and the truth is a directory listing.
    """
    root = workspace_root(args.root)
    found: dict[str, list[str]] = {}
    for repo in repos():
        for name in worktrees(root / repo.dir):
            found.setdefault(name, []).append(repo.name)
    if not found:
        print("[workspace] no worktrees in any repo")
        return 0
    width = max(len(n) for n in found)
    for name, where in sorted(found.items()):
        across = " (a set)" if len(where) > 1 else ""
        print(f"  {name.ljust(width)}  {', '.join(where)}{across}")
    return 0


def cmd_wt_set_rm(args: argparse.Namespace) -> int:
    root = workspace_root(args.root)
    removed = []
    for repo in repos():
        path = root / repo.dir
        if args.name in worktrees(path):
            print(f"\n[workspace] {repo.name}: make wt-rm NAME={args.name}")
            if run(["make", "-C", str(path), "wt-rm", f"NAME={args.name}"]):
                removed.append(repo.name)
    print()
    if not removed:
        print(f"[workspace] no repo has a worktree named '{args.name}'")
        return 1
    print(f"[workspace] removed '{args.name}' from: {', '.join(removed)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="workspace.py", description=__doc__.splitlines()[0])
    parser.add_argument("--root", help="the directory the repos sit in (default: the parent of this checkout)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="clone every repo side by side and provision each")
    sub.add_parser("status", help="branch, state and pins across the workspace")
    sub.add_parser("env", help="print the cross-repo dev exports")
    sub.add_parser("matrix", help="JSON of the repos that vendor a contract")

    cut = sub.add_parser("wt-set", help="cut a same-named worktree in several repos")
    cut.add_argument("name")
    cut.add_argument("--repos", required=True, help='space-separated, e.g. "yeaboi frontend"')
    cut.add_argument("--headless", action="store_true", help="no editor window per repo")

    sub.add_parser("wt-sets", help="which worktree names exist in which repos")

    drop = sub.add_parser("wt-set-rm", help="remove a worktree name from every repo that has it")
    drop.add_argument("name")

    args = parser.parse_args(argv)
    handlers = {
        "setup": cmd_setup,
        "status": cmd_status,
        "env": cmd_env,
        "matrix": cmd_matrix,
        "wt-set": cmd_wt_set,
        "wt-sets": cmd_wt_sets,
        "wt-set-rm": cmd_wt_set_rm,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
