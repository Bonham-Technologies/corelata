"""Assert what keeps CI safe once the repository is public (CRL-105).

- Every actions/checkout in ci.yml and hosted.yml sets `persist-credentials: false`, so no later
  step can reuse the job's token from .git/config.
- A job on the self-hosted runner (`vars.RUNS_ON`) falls back to the hosted runner when the pull
  request comes from a fork, so a fork's code never runs on the org's own machine.

Reads the workflow files as text, so it needs nothing beyond Python's standard library."""

import re
import sys
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
CHECKED = ("ci.yml", "hosted.yml")
FORK_GUARD = "!github.event.pull_request.head.repo.fork"


def indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def checkout_steps(lines: list[str]) -> list[tuple[int, list[str]]]:
    """Each checkout step's first line number and its lines, up to the next step or job."""
    steps = []
    for i, line in enumerate(lines):
        if not re.search(r"uses:\s*[\"']?actions/checkout@", line):
            continue
        # The step starts at the nearest line at or above it that opens a list item.
        start = i
        while not lines[start].lstrip().startswith("- "):
            start -= 1
        dash = indent(lines[start])
        end = start + 1
        while end < len(lines) and (not lines[end].strip() or indent(lines[end]) > dash):
            end += 1
        steps.append((start + 1, lines[start:end]))
    return steps


def check(name: str) -> list[str]:
    lines = (WORKFLOWS / name).read_text().splitlines()
    errors = []
    steps = checkout_steps(lines)
    if not steps:
        errors.append(f"{name}: no actions/checkout step found")
    for lineno, step in steps:
        if not any(re.fullmatch(r"\s*persist-credentials:\s*false\s*", s) for s in step):
            errors.append(f"{name}:{lineno}: checkout without persist-credentials: false")
    # Any line that reads vars.RUNS_ON (a runs-on, folded or not) carries the guard outside a comment.
    for lineno, line in enumerate(lines, 1):
        code = re.sub(r"(^|\s)#.*", "", line)
        if "vars.RUNS_ON" in code and FORK_GUARD not in code:
            errors.append(f"{name}:{lineno}: vars.RUNS_ON without {FORK_GUARD}")
    return errors


def main() -> None:
    errors = [e for name in CHECKED for e in check(name)]
    for e in errors:
        print(f"check_workflows: {e}", file=sys.stderr)
    if errors:
        sys.exit(1)
    print(f"check_workflows: {', '.join(CHECKED)} ok")


if __name__ == "__main__":
    main()
