"""Read the repository's feedback gate, or raw reviews when it has no gate."""

import argparse
import json
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", default="")
    args = parser.parse_args()
    if Path("scripts/pr_feedback.py").is_file():
        return subprocess.call(["make", "pr-feedback", f"PR={args.pr}"])
    info = subprocess.run(
        ["gh", "pr", "view", *([args.pr] if args.pr else []), "--json", "number,comments,reviews,statusCheckRollup"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(info.stdout)
    print(json.dumps(data, indent=2), flush=True)
    return subprocess.call(["gh", "api", f"repos/{{owner}}/{{repo}}/pulls/{data['number']}/comments", "--paginate"])


if __name__ == "__main__":
    raise SystemExit(main())
