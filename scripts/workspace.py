#!/usr/bin/env python3
"""workspace.py — the five yeaboi repos, side by side.

One product, five repos, and every seam between them a pin: a wheel on PyPI, a
package on npm, a vendored contract, a tooling sha. This is the local half of
that. It clones them all (`setup`), shows them all at once (`status`), prints
the environment that makes one checkout serve another (`env`), and cuts one
feature's worktree across all of them at once (`wt-set`, reached as `make wt-new`).

Reached through `make workspace-*` and `make wt-new` / `make wt-rm` in
mk/common.mk, so it runs from any repo in the workspace, not only from this one.

No third-party imports, and no `tomllib` either: this must run on whatever
python3 a machine already has, and the system interpreter on macOS is 3.9. The
manifest reader below covers exactly the subset workspace.toml is written in
and raises on anything else; tests/test_workspace.py holds it to tomllib's
answer on the real file.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Sibling script in this same directory, not an installed package — this file is
# run by path (`python3 .tooling/scripts/workspace.py`), so it is not importable
# any other way.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import wt_slots  # noqa: E402

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


def run_capture(args: list[str], cwd: Path | None = None) -> tuple[bool, str]:
    """`run`, but hand the output back instead of letting it reach the terminal.

    The fan-out below runs five makes at once. Five children writing to one
    terminal interleave line by line and the result is unreadable, so each one's
    output is held and printed in a block when it finishes.

    stderr is folded into stdout rather than appended after it: git narrates
    ("Preparing worktree…") on stderr and the scripts on stdout, and two
    concatenated streams put the narration after the conclusion it belongs to.
    """
    env = {k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MAKELEVEL")}
    result = subprocess.run(
        args,
        cwd=None if cwd is None else str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.returncode == 0, result.stdout or ""


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
    """Every worktree name under this repo, nested ones included.

    A branch-shaped name like ``desktop/tips-ui`` lands on disk as nested
    directories, so a single-level scan sees only the ``desktop`` parent — which
    holds no ``.git`` and is skipped, making the worktree invisible to wt-sets
    and wt-rm. Names come back relative to the worktrees root, so they match the
    NAME the wt- targets take. Each worktree carries a pinned ``.tooling``
    clone; that is a checkout, not a worktree of this repo, and is never a name.
    """
    home = path / ".claude" / "worktrees"
    if not home.is_dir():
        return []
    found = set()
    for git in home.rglob(".git"):
        name = git.parent.relative_to(home)
        if TOOLING_DIR in name.parts:
            continue
        found.add(name.as_posix())
    return sorted(found)


# --- one feature, every repo -------------------------------------------------
#
# A worktree "set" is the same branch name cut in several repos and opened as
# ONE editor window. Two things make that work, and both are deliberate.
#
# The per-repo cut always goes through that repo's `wt-headless`, never its
# `wt-new`: `wt-new` IS this command, so calling it would recurse — and
# `wt-headless` is also the one worktree target every repo already has at its
# current `.tooling` pin, so a set can be cut before the siblings bump.
#
# Because those cuts are headless, wt.sh writes no per-folder `.vscode/`. The
# multi-root window therefore has exactly one `folderOpen` task, and so exactly
# one claude session — not one per root, five of them racing for the terminal.

TOOLING_DIR = ".tooling"
WT_SETS_DIR = ".worktrees"


def code_workspace(root: Path, name: str) -> Path:
    """Where a set's multi-root VS Code workspace file lives.

    Beside the repos rather than inside one: it names paths in all of them, and
    no single repo should be carrying a file about its siblings.
    """
    return root / WT_SETS_DIR / f"{name}.code-workspace"


def write_code_workspace(root: Path, name: str, folders: list[tuple[str, Path]]) -> Path:
    """One window over every repo's worktree, with one claude session over the lot.

    `--add-dir` is what makes that session more than the folder it started in.
    The cwd is the first folder, which is workspace.toml order, which is the
    Python repo — the one whose contracts the others vendor.
    """
    primary = folders[0][1]
    others = [str(path) for _, path in folders[1:]]
    command = "claude"
    if others:
        command += " --add-dir " + " ".join(shlex.quote(path) for path in others)
    spec = {
        "folders": [{"name": label, "path": str(path)} for label, path in folders],
        # Workspace-scoped, exactly as wt.sh writes it per folder: this is what
        # skips VS Code's "allow automatic tasks?" prompt. Workspace Trust still
        # asks once per unseen folder, and there is no setting that answers it.
        "settings": {"task.allowAutomaticTasks": "on"},
        "tasks": {
            "version": "2.0.0",
            "tasks": [
                {
                    "label": "claude",
                    "type": "shell",
                    "command": command,
                    "options": {"cwd": str(primary)},
                    "presentation": {
                        "reveal": "always",
                        "panel": "new",
                        "focus": True,
                        "clear": True,
                        "showReuseMessage": False,
                    },
                    "runOptions": {"runOn": "folderOpen"},
                    "problemMatcher": [],
                }
            ],
        },
    }
    path = code_workspace(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2) + "\n")
    return path


def tidy(output: str) -> str:
    """Drop what only makes sense one repo at a time.

    Each cut is a `make wt-headless`, so every repo narrates make's recipe line
    and wt.sh's "drive it with a background agent" note. Neither is true of a set
    — the window opens right after — and five copies of both bury the five lines
    that matter. Only applied to a repo that succeeded; a failure keeps all of it.
    """
    return "\n".join(
        line
        for line in output.splitlines()
        if not line.startswith("WT_REPO_DIR=") and "no VS Code auto-launch" not in line
    )


def drop_folder_task(tree: Path) -> None:
    """Take a worktree's own auto-launch task away before it joins a set.

    A headless cut never writes one, so this only bites on a worktree that
    already existed from `make wt-one`: in a multi-root window its folderOpen
    task would start a second claude beside the workspace-level one. The file is
    generated and gitignored, so there is nothing here to lose.
    """
    tasks = tree / ".vscode" / "tasks.json"
    if tasks.is_file() and "folderOpen" in tasks.read_text():
        tasks.unlink()


def open_workspace(path: Path, name: str) -> bool:
    """Open the set in one editor window. A missing CLI is a note, not a failure:
    the worktrees are already cut, and the file can be opened by hand."""
    editor = os.environ.get("CODE") or "code"
    if shutil.which(editor) is None:
        print(f"[workspace] '{editor}' CLI not found on PATH — the worktrees are cut; open this by hand:")
        print(f"[workspace]   {path}")
        print("[workspace] in VS Code: Cmd-Shift-P → \"Shell Command: Install 'code' command in PATH\"")
        print(f"[workspace] or name another editor: CODE=cursor make wt-new NAME={name}")
        return False
    if not run([editor, "-n", str(path)]):
        return False
    print(f"[workspace] opened '{name}' in {editor}; claude auto-starts in the integrated terminal")
    return True


def cmd_wt_set(args: argparse.Namespace) -> int:
    root = workspace_root(args.root)
    # No --repos means the whole workspace. That is the common case and the
    # reason `make wt-new NAME=x` needs no second argument.
    everywhere = not args.repos
    chosen = repos() if everywhere else select(args.repos.split())

    present, missing = [], []
    for repo in chosen:
        (present if (root / repo.dir / ".git").exists() else missing).append(repo)
    for repo in missing:
        print(f"[workspace] {repo.name}: not cloned — skipped (`make workspace-setup` clones it)")
    if not present:
        print(f"[workspace] nothing to cut '{args.name}' in — no repo in {root} is cloned")
        return 1

    # Not being cloned is a fact about the machine when the whole workspace was
    # implied, and a mistake when the repo was named out loud.
    failed = [] if everywhere else [repo.name for repo in missing]

    # Claim the port/state slot once, here, rather than letting five parallel
    # wt.sh runs each race for it — they must all agree on one number, because
    # one feature's five worktrees are developed together.
    try:
        slot = wt_slots.allocate(args.name)
        print(f"[workspace] '{args.name}' is slot {slot} — its own ports and ~/.yeaboi in every repo")
    except Exception as exc:  # a shared machine resource; never block the cut on it
        print(f"[workspace] note: could not assign a slot ({exc}) — worktrees will share ports")

    print(f"[workspace] cutting '{args.name}' in {len(present)} repo(s), in parallel…")
    sys.stdout.flush()
    # Appended, never inserted: the per-repo argv is read positionally elsewhere
    # (the repo dir is [2], the target [3]), and REUSE is the rare case.
    extra = ["REUSE=1"] if args.reuse else []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(present)) as pool:
        pending = {
            pool.submit(
                run_capture,
                ["make", "-C", str(root / repo.dir), "wt-headless", f"NAME={args.name}", *extra],
            ): repo
            for repo in present
        }
        for future in concurrent.futures.as_completed(pending):
            repo = pending[future]
            ok, output = future.result()
            print()
            for line in (tidy(output) if ok else output).rstrip().splitlines():
                print(f"[{repo.name}] {line}")
            if not ok:
                failed.append(repo.name)

    # Manifest order, not completion order: the first folder is where the claude
    # session starts, and which repo that is must not depend on which npm ci won.
    cut = [repo for repo in present if repo.name not in failed]
    print()
    if failed:
        print(f"[workspace] could not cut '{args.name}' in: {', '.join(failed)}")
    if not cut:
        return 1

    folders = [(repo.name, root / repo.dir / ".claude" / "worktrees" / args.name) for repo in cut]
    for _, tree in folders:
        drop_folder_task(tree)
    path = write_code_workspace(root, args.name, folders)
    print(f"[workspace] '{args.name}' is cut in {len(cut)} repo(s): {', '.join(name for name, _ in folders)}")
    print(f"[workspace] one window over all of them: {path}")
    if args.headless:
        print("[workspace] headless — no editor; drive the worktrees with background agents")
    else:
        open_workspace(path, args.name)
    print("[workspace] ship upstream first — the downstream PR carries the new pin.")
    return 1 if failed else 0


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


def unshipped(path: Path) -> str:
    """What this worktree is carrying that origin/main does not, in a word.

    Commits ahead is the headline; a dirty tree counts too, because uncommitted
    work is the most easily forgotten kind. Best-effort — a worktree that cannot
    be read is reported as unknown rather than silently clean.
    """
    ok, _ = run_capture(["git", "-C", str(path), "fetch", "origin", "--quiet"])
    ok, ahead = run_capture(["git", "-C", str(path), "rev-list", "--count", "origin/main..HEAD"])
    if not ok:
        return "unknown"
    ok, dirty = run_capture(["git", "-C", str(path), "status", "--porcelain"])
    counts = []
    if ahead.strip().isdigit() and int(ahead.strip()):
        counts.append(f"{ahead.strip()} commit(s) ahead")
    if ok and dirty.strip():
        counts.append(f"{len(dirty.strip().splitlines())} uncommitted file(s)")
    return ", ".join(counts) if counts else "clean"


def cmd_wt_siblings(args: argparse.Namespace) -> int:
    """Every repo carrying this worktree name, and what each still owes.

    `make wt-new` cuts a feature in EVERY repo, so a feature is a set by
    construction while /ship works one repo at a time. Shipping the repo you
    happen to be sitting in leaves the rest of the set behind — which is how a
    generated contract lands in one repo describing an app whose code is still
    sitting in another repo's worktree. Exit 1 when a sibling still owes work,
    so a gate can refuse rather than advise.
    """
    root = workspace_root(args.root)
    name = args.name
    carrying = [r for r in repos() if name in worktrees(root / r.dir)]
    if not carrying:
        print(f"[workspace] no repo has a worktree named {name!r}")
        return 0
    print(f"[workspace] worktree {name!r} exists in {len(carrying)} repo(s):")
    owing = []
    for repo in carrying:
        state = unshipped(root / repo.dir / ".claude" / "worktrees" / name)
        print(f"  {repo.name:<16} {state}")
        if state not in ("clean", "unknown"):
            owing.append(repo.name)
    if owing:
        print(
            f"\n[workspace] {len(owing)} repo(s) still owe work: {', '.join(owing)}."
            "\n[workspace] Ship the set, not the repo you are standing in."
        )
        return 1
    return 0


def cmd_wt_set_rm(args: argparse.Namespace) -> int:
    root = workspace_root(args.root)
    chosen = repos() if not args.repos else select(args.repos.split())
    removed = []
    for repo in chosen:
        path = root / repo.dir
        if args.name not in worktrees(path):
            continue
        print(f"\n[workspace] {repo.name}: make wt-one-rm NAME={args.name}")
        # `wt-one-rm`, not `wt-rm`: `wt-rm` is this command, and calling it here
        # would recurse. A repo still on an older .tooling pin has no
        # `wt-one-rm` — there its `wt-rm` is the single-repo one, which is
        # exactly what is wanted. Drop this fallback once every pin is bumped.
        ok, output = run_capture(["make", "-C", str(path), "wt-one-rm", f"NAME={args.name}"])
        if not ok and "No rule to make target" in output:
            print(f"[workspace] {repo.name} is on an older .tooling pin — falling back to its wt-rm")
            ok, output = run_capture(["make", "-C", str(path), "wt-rm", f"NAME={args.name}"])
        print(output.rstrip())
        if ok:
            removed.append(repo.name)

    print()
    spec = code_workspace(root, args.name)
    if spec.is_file():
        spec.unlink()
        print(f"[workspace] removed {spec}")
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

    cut = sub.add_parser("wt-set", help="cut a same-named worktree in every repo and open them as one window")
    cut.add_argument("name")
    cut.add_argument("--repos", help='space-separated, e.g. "yeaboi frontend" (default: every repo)')
    cut.add_argument("--headless", action="store_true", help="cut the worktrees, open no editor window")
    cut.add_argument(
        "--reuse",
        action="store_true",
        help="continue branches of this name where they already exist, rebased onto origin/main "
        "(without it an existing branch is refused, because a cut means a fresh one)",
    )

    sub.add_parser("wt-sets", help="which worktree names exist in which repos")

    sibs = sub.add_parser("wt-siblings", help="which repos carry this worktree name, and what each still owes")
    sibs.add_argument("name")

    drop = sub.add_parser("wt-set-rm", help="remove a worktree name from every repo that has it")
    drop.add_argument("name")
    drop.add_argument("--repos", help="space-separated (default: every repo that has it)")

    args = parser.parse_args(argv)
    handlers = {
        "setup": cmd_setup,
        "status": cmd_status,
        "env": cmd_env,
        "matrix": cmd_matrix,
        "wt-set": cmd_wt_set,
        "wt-sets": cmd_wt_sets,
        "wt-siblings": cmd_wt_siblings,
        "wt-set-rm": cmd_wt_set_rm,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
