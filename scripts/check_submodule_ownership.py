#!/usr/bin/env python3
"""CI guard: submodule pointer bumps must come from the owning role.

The role contract (ai/GIT.md) assigns each git submodule an owning role.
Agents commit with worktree-scoped identities (<role>@agents.rfc), which makes
every commit attributable; this script turns the ownership table from an
advisory prompt rule into a merge-blocking check:

  - A gitlink (mode 160000) change authored by the owning role's identity passes.
  - A gitlink change authored by any other agent identity fails the build.
  - A gitlink change authored by a human (any non-@agents.rfc email) always
    passes — humans outrank agents.

Usage:
  uv run python scripts/check_submodule_ownership.py --base origin/claude-code-staging
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass

# Mirrors the ownership table in ai/GIT.md. Update both together.
SUBMODULE_OWNERS: dict[str, str] = {
    "results": "test-design@agents.rfc",
    "monitoring/logs": "project-management@agents.rfc",
    ".claude/skills/elons-algorithm": "design@agents.rfc",
}

AGENT_EMAIL_DOMAIN = "@agents.rfc"
GITLINK_MODE = "160000"


@dataclass(frozen=True)
class GitlinkChange:
    """One commit that moved one submodule pointer."""

    path: str
    commit: str
    author_email: str


def is_agent_email(email: str) -> bool:
    """Agent identities are <role>@agents.rfc; everything else is human."""
    return email.endswith(AGENT_EMAIL_DOMAIN)


def evaluate_changes(changes: list[GitlinkChange]) -> list[str]:
    """Return one human-readable violation per disallowed pointer bump."""
    violations: list[str] = []
    for change in changes:
        if not is_agent_email(change.author_email):
            continue  # humans outrank agents
        owner = SUBMODULE_OWNERS.get(change.path)
        if owner is None:
            violations.append(
                f"{change.commit[:7]}: submodule '{change.path}' has no owner in "
                f"ai/GIT.md, so agent '{change.author_email}' may not bump it — "
                "add it to the ownership table or let a human commit the bump"
            )
        elif change.author_email != owner:
            violations.append(
                f"{change.commit[:7]}: submodule '{change.path}' pointer bumped by "
                f"'{change.author_email}' but is owned by '{owner}' (ai/GIT.md) — "
                "file an issue for the owning role instead"
            )
    return violations


def _git(args: list[str]) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def changed_gitlink_paths(base: str) -> list[str]:
    """Submodule paths whose pointer differs between merge-base(base, HEAD) and HEAD."""
    raw = _git(["diff", "--raw", f"{base}...HEAD"])
    paths: list[str] = []
    for line in raw.splitlines():
        # :<old mode> <new mode> <old sha> <new sha> <status>\t<path>
        meta, _, path = line.partition("\t")
        fields = meta.split()
        if len(fields) >= 2 and GITLINK_MODE in (fields[0].lstrip(":"), fields[1]):
            paths.append(path)
    return paths


def _commit_touches_gitlink(commit: str, path: str) -> bool:
    """True if this commit's diff changes the gitlink itself (mode 160000) at path.

    `git log -- <path>` also lists commits that only changed ordinary files
    under <path> (e.g. while converting a directory to/from a submodule);
    those must not be attributed as pointer bumps.
    """
    # -r is required: without it diff-tree reports a nested gitlink (e.g.
    # monitoring/logs) as its parent tree (mode 040000) and the match fails.
    raw = _git(["diff-tree", "-r", "--raw", "--no-commit-id", commit, "--", path])
    for line in raw.splitlines():
        meta, _, raw_path = line.partition("\t")
        fields = meta.split()
        if (
            raw_path == path
            and len(fields) >= 2
            and GITLINK_MODE in (fields[0].lstrip(":"), fields[1])
        ):
            return True
    return False


def collect_changes(base: str) -> list[GitlinkChange]:
    """Every commit in base..HEAD that moved a changed gitlink, with its author."""
    changes: list[GitlinkChange] = []
    for path in changed_gitlink_paths(base):
        log = _git(["log", "--format=%H %ae", f"{base}..HEAD", "--", path])
        for line in log.splitlines():
            commit, _, author_email = line.partition(" ")
            if not _commit_touches_gitlink(commit, path):
                continue
            changes.append(
                GitlinkChange(path=path, commit=commit, author_email=author_email)
            )
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="origin/claude-code-staging",
        help="Base ref to diff against (default: origin/claude-code-staging)",
    )
    args = parser.parse_args(argv)

    changes = collect_changes(args.base)
    violations = evaluate_changes(changes)
    if violations:
        print("Submodule ownership violations (see ai/GIT.md):", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1

    print(f"submodule ownership: ok ({len(changes)} pointer change(s) checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
