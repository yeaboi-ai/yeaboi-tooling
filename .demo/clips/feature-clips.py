"""The clip lane itself: the targets a repo gains, and the spec behind a clip.

A shell session like this repo's demo, and read-only for the same reason — a
take can be re-run against a real checkout without touching it.

Deliberately never runs `make clip-replay`: that target replays every spec in
`.demo/clips/`, which includes this one, and a clip that replays itself does
not terminate.
"""

_ENV = {
    "PS1": "$ ",
    "PS2": "> ",
    "TERM": "xterm-256color",
    "CLICOLOR_FORCE": "1",
    "BASH_SILENCE_DEPRECATION_WARNING": "1",
}


def _type(text: str, cps: int = 22) -> list:
    return [("type", text, cps), ("pause", 0.35), ("key", b"\n")]


SPEC = {
    "kind": "tty",
    "cmd": ["bash", "--noprofile", "--norc"],
    "cols": 100,
    "rows": 22,
    "title": "feature clips — a recording of the one thing a PR changes",
    "require_alt_screen": False,
    "cwd": ".",
    "env": _ENV,
    "steps": [
        ("await", ("$ ",), 10.0),
        ("pause", 0.9),
        # What a repo gains by bumping the pin.
        *_type("make help | grep clip"),
        ("await", ("clip-list",), 30.0),
        ("pause", 2.8),
        *_type("clear"),
        ("pause", 0.4),
        # The point of committing the spec: the walkthrough is reviewable, and
        # CI can replay it later to prove the feature still works.
        *_type("make clip-list"),
        ("await", (".demo/clips",), 20.0),
        ("pause", 2.6),
        *_type("exit"),
    ],
    "verify": {
        "min_distinct_colors": 8,
        "duration_s": (4.0, 45.0),
        "frames": (20, 1500),
    },
}
