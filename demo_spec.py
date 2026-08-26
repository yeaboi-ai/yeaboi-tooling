"""What this repo's README GIF shows: five checkouts treated as one.

A shell session, not a TUI — which is why ``require_alt_screen`` is off. Every
command is read-only, so the take can be re-run against a real workspace
without touching it.
"""

# A prompt that renders the same on every machine, so a take does not carry
# whoever recorded it. Exported into the shell rather than typed, so the
# assignment itself never appears on screen.
_ENV = {
    "PS1": "$ ",
    "PS2": "> ",
    "TERM": "xterm-256color",
    # `make` colourises nothing, but the scripts underneath check for a tty.
    "CLICOLOR_FORCE": "1",
    # macOS ships bash 3.2 and prints a three-line "use zsh" notice on every
    # interactive start. It is the first thing in frame otherwise.
    "BASH_SILENCE_DEPRECATION_WARNING": "1",
}


# Typed rather than written whole: a shell echoes each character back, and that
# echo is what puts motion in the cast. Writing a line at once emits one event,
# which agg renders as a single static frame.
def _type(text: str, cps: int = 22) -> list:
    return [("type", text, cps), ("pause", 0.35), ("key", b"\n")]


SPEC = {
    "kind": "tty",
    "gif": "demo-tooling.gif",
    "cast": "demo-tooling.cast.gz",
    "cmd": ["bash", "--noprofile", "--norc"],
    "cols": 100,
    "rows": 26,
    "title": "yeaboi-tooling — one workflow, five repos",
    # A shell never enters the alternate screen buffer. Requiring it would fail
    # every take, and truncating the cast on its exit would end it immediately.
    "require_alt_screen": False,
    "cwd": ".",
    "env": _ENV,
    "steps": [
        ("await", ("$ ",), 10.0),
        ("pause", 0.9),
        # The headline feature: one command, the state of all five repos.
        *_type("make workspace-status"),
        ("await", ("tooling",), 30.0),
        ("pause", 3.2),
        *_type("clear"),
        ("pause", 0.4),
        # The other half — worktrees, cut and listed the same way in every repo.
        *_type("make wt-list"),
        ("pause", 3.0),
        *_type("exit"),
    ],
    # A shell transcript is mostly one foreground colour on one background, so
    # the TUI-tuned floor of 64 distinct colours would reject a good take.
    "verify": {
        "min_distinct_colors": 8,
        "duration_s": (4.0, 45.0),
        "frames": (20, 1500),
    },
}
