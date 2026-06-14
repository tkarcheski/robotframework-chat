#!/usr/bin/env python3
"""CI guard: agent commits must be signed off and name their model.

Per ai/GIT.md, every agent-authored commit (author email *@agents.rfc) must
carry BOTH trailers:

  Signed-off-by: rfc-<role>-agent <<role>@agents.rfc>
  Model: <model-id>            (e.g. claude-opus-4-8)

so the history records which role *and* which model produced each change.
Human-authored commits (any non-@agents.rfc author) are exempt. CI only
requires the trailers to exist with agent identities; author/sign-off
mismatches are judged by project-management's sweep, not auto-failed.

Usage:
  uv run python scripts/check_agent_signoffs.py --base origin/claude-code-staging
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass

AGENT_EMAIL_DOMAIN = "@agents.rfc"
COMMIT_SEPARATOR = "\x1e"  # ASCII record separator between commits
SIGNOFF_RE = re.compile(r"^Signed-off-by:.*<([^>]+)>", re.MULTILINE)
MODEL_RE = re.compile(r"^Model:\s*(\S.*)$", re.MULTILINE)


@dataclass(frozen=True)
class CommitMeta:
    commit: str
    author_email: str
    signoff_emails: list[str]
    models: list[str]


def evaluate_commits(commits: list[CommitMeta]) -> list[str]:
    """One human-readable violation per non-compliant agent commit."""
    violations: list[str] = []
    for c in commits:
        if not c.author_email.endswith(AGENT_EMAIL_DOMAIN):
            continue  # humans are exempt
        missing: list[str] = []
        if not any(e.endswith(AGENT_EMAIL_DOMAIN) for e in c.signoff_emails):
            missing.append("Signed-off-by (agent identity)")
        if not c.models:
            missing.append("Model")
        if missing:
            violations.append(
                f"{c.commit[:7]}: agent commit by '{c.author_email}' is missing "
                f"trailer(s): {', '.join(missing)} — see ai/GIT.md "
                "(commit -s --trailer 'Model:<model-id>')"
            )
    return violations


def collect_commits(base: str) -> list[CommitMeta]:
    out = subprocess.run(
        [
            "git",
            "log",
            f"--format=%H %ae%n%B{COMMIT_SEPARATOR}",
            f"{base}..HEAD",
            "--no-merges",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    commits: list[CommitMeta] = []
    for record in out.split(COMMIT_SEPARATOR):
        record = record.strip()
        if not record:
            continue
        header, _, body = record.partition("\n")
        commit, _, author_email = header.partition(" ")
        commits.append(
            CommitMeta(
                commit=commit,
                author_email=author_email,
                signoff_emails=SIGNOFF_RE.findall(body),
                models=[m.strip() for m in MODEL_RE.findall(body)],
            )
        )
    return commits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="origin/claude-code-staging",
        help="Base ref to diff against (default: origin/claude-code-staging)",
    )
    args = parser.parse_args(argv)

    commits = collect_commits(args.base)
    violations = evaluate_commits(commits)
    if violations:
        print("Agent sign-off violations (see ai/GIT.md):", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1

    agent_count = sum(1 for c in commits if c.author_email.endswith(AGENT_EMAIL_DOMAIN))
    print(
        f"agent sign-offs: ok ({agent_count} agent commit(s) of {len(commits)} checked)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
