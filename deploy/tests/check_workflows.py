"""Assert what keeps CI safe once the repository is public (CRL-105).

- Every actions/checkout in ci.yml and hosted.yml sets `persist-credentials: false`, so no later
  step can reuse the job's token from .git/config.
- A job on the self-hosted runner (`vars.RUNS_ON`) falls back to the hosted runner when the pull
  request comes from a fork, so a fork's code never runs on the org's own machine.
- Every job has a `timeout-minutes`, so a hung job cannot hold a runner for six hours (CRL-115).
- release.yml reads only by default; the `publish` job alone may write, it checks out nothing,
  and the `build` job runs the tag gate `deploy/check-release-tag.sh` (CRL-115).
- Every Postgres service image in ci.yml is bundle.sh's digest-pinned POSTGRES_IMAGE (CRL-115).

Reads the workflow files as text, so it needs nothing beyond Python's standard library."""

import re
import sys
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
CHECKED = ("ci.yml", "hosted.yml", "release.yml")
BUNDLE = Path(__file__).resolve().parents[1] / "bundle.sh"
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


def jobs(lines: list[str]) -> dict[str, list[str]]:
    """Each job's lines under `jobs:` (two-space keys), by name."""
    found: dict[str, list[str]] = {}
    current = None
    inside = False
    for line in lines:
        if re.fullmatch(r"jobs:\s*", line):
            inside = True
            continue
        if not inside:
            continue
        if line.strip() and indent(line) == 0:
            break
        m = re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*", line)
        if m:
            current = m.group(1)
            found[current] = []
        elif current is not None:
            found[current].append(line)
    return found


def top_level(lines: list[str], key: str) -> list[str]:
    """The lines of a top-level mapping such as `permissions:`."""
    out: list[str] = []
    for i, line in enumerate(lines):
        if re.fullmatch(rf"{key}:\s*(\S.*)?", line):
            out.append(line)
            for following in lines[i + 1 :]:
                if following.strip() and indent(following) == 0:
                    break
                out.append(following)
    return out


def postgres_pin() -> str:
    text = BUNDLE.read_text()
    tag = re.search(r"^POSTGRES_TAG=(\S+)$", text, re.M)
    digest = re.search(r"^POSTGRES_IMAGE=\$POSTGRES_TAG@(sha256:[0-9a-f]{64})$", text, re.M)
    return f"{tag.group(1)}@{digest.group(1)}" if tag and digest else "(no pin in bundle.sh)"


def check_release(lines: list[str]) -> list[str]:
    errors = []
    perms = "\n".join(top_level(lines, "permissions"))
    if not re.search(r"^permissions:\s*$\n\s+contents:\s*read\s*$", perms, re.M) or "write" in perms:
        errors.append("release.yml: top-level permissions must be exactly contents: read")
    found = jobs(lines)
    for job, body in found.items():
        writes = any(re.search(r":\s*write\b", line) for line in body)
        if writes and job != "publish":
            errors.append(f"release.yml: job {job} asks for write permission; only publish may")
        if job == "publish" and any("actions/checkout@" in line for line in body):
            errors.append("release.yml: publish checks out the repository; it must run no repo code")
    if "publish" not in found:
        errors.append("release.yml: no publish job")
    if not any("deploy/check-release-tag.sh" in line for line in found.get("build", [])):
        errors.append("release.yml: the build job does not run deploy/check-release-tag.sh")
    return errors


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
    for job, body in jobs(lines).items():
        if not any(re.match(r"\s{4}timeout-minutes:\s*\d+", line) for line in body):
            errors.append(f"{name}: job {job} has no timeout-minutes")
    for lineno, line in enumerate(lines, 1):
        m = re.search(r"image:\s*(postgres:\S+)", line)
        if m and m.group(1) != postgres_pin():
            errors.append(f"{name}:{lineno}: postgres image {m.group(1)} is not {postgres_pin()}")
    if name == "release.yml":
        errors += check_release(lines)
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
