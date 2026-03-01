#!/usr/bin/env python3
"""Auto-increment version based on conventional commit messages.

Reads the current version from pyproject.toml, scans commit messages
to determine the bump type, and updates both pyproject.toml and
src/rfc/__init__.py.

Bump rules:
  - 'release' in commit message  → major bump (0.133.0 → 1.0.0)
  - 'breaking' or '!' in commit  → minor bump (0.133.0 → 0.134.0)
  - 'feat:' or 'fix:' prefix     → patch bump (0.133.0 → 0.133.1)
  - everything else               → no bump

Usage:
  uv run python scripts/bump_version.py              # auto-detect from git log
  uv run python scripts/bump_version.py --dry-run    # preview only
  uv run python scripts/bump_version.py --bump patch # force bump type
  uv run python scripts/bump_version.py --bump minor
  uv run python scripts/bump_version.py --bump major
  uv run python scripts/bump_version.py --from-commit HEAD~5
"""

from __future__ import annotations

import argparse
import enum
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PYPROJECT = ROOT / "pyproject.toml"
DEFAULT_INIT = ROOT / "src" / "rfc" / "__init__.py"


class BumpType(enum.Enum):
    """Version bump types, ordered by precedence (highest first)."""

    MAJOR = 3
    MINOR = 2
    PATCH = 1


def determine_bump(commits: list[str]) -> BumpType | None:
    """Determine the highest bump type from a list of commit messages.

    Args:
        commits: List of commit message strings (first line only is fine).

    Returns:
        The highest BumpType found, or None if no bump-worthy commits.
    """
    highest: BumpType | None = None

    for msg in commits:
        bump = _classify_commit(msg)
        if bump is not None:
            if highest is None or bump.value > highest.value:
                highest = bump

    return highest


def _classify_commit(msg: str) -> BumpType | None:
    """Classify a single commit message into a bump type.

    Priority: release (major) > breaking/! (minor) > feat/fix (patch).
    """
    lower = msg.lower()

    # Major: "release" anywhere in the message
    if "release" in lower:
        return BumpType.MAJOR

    # Minor: "breaking" anywhere, or "!" after the type prefix
    if "breaking" in lower:
        return BumpType.MINOR
    # Match conventional commit with ! (e.g., "feat!:", "refactor(core)!:")
    if re.match(r"^[a-z]+(\([^)]*\))?!:", msg, re.IGNORECASE):
        return BumpType.MINOR

    # Patch: "feat:" or "fix:" prefix (with optional scope)
    if re.match(r"^(feat|fix)(\([^)]*\))?:", msg, re.IGNORECASE):
        return BumpType.PATCH

    return None


def bump_version(current: str, bump_type: BumpType) -> str:
    """Compute the new version string after applying a bump.

    Args:
        current: Current version string (e.g., "0.133.0").
        bump_type: The type of bump to apply.

    Returns:
        New version string.
    """
    parts = current.split(".")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    if bump_type == BumpType.MAJOR:
        return f"{major + 1}.0.0"
    elif bump_type == BumpType.MINOR:
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


def read_current_version(pyproject_path: Path = DEFAULT_PYPROJECT) -> str:
    """Read the current version from pyproject.toml.

    Args:
        pyproject_path: Path to pyproject.toml.

    Returns:
        Current version string.
    """
    data = tomllib.loads(pyproject_path.read_text())
    return data["project"]["version"]


def get_commits_since_tag(from_ref: str | None = None) -> list[str]:
    """Get commit messages since the last version tag (or a given ref).

    Args:
        from_ref: Git ref to start from (e.g., "HEAD~5"). If None,
                  finds the last version tag automatically.

    Returns:
        List of commit message first lines.
    """
    if from_ref is None:
        # Find the last version tag
        try:
            result = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0", "--match", "v*"],
                capture_output=True,
                text=True,
                check=True,
            )
            from_ref = result.stdout.strip()
            log_range = f"{from_ref}..HEAD"
        except subprocess.CalledProcessError:
            # No tags found — use all commits
            log_range = "HEAD"
    else:
        log_range = f"{from_ref}..HEAD"

    result = subprocess.run(
        ["git", "log", "--format=%s", log_range],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]


def run_quality_gates() -> bool:
    """Run quality gates (tests + linting).

    Returns:
        True if all gates pass, False otherwise.
    """
    gates = [
        (["uv", "run", "pytest"], "pytest"),
        (["make", "code-quality-check"], "code-quality-check"),
    ]

    all_passed = True
    for cmd, name in gates:
        print(f"  Running {name}...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  FAILED: {name}")
            if result.stdout:
                # Show last few lines for context
                lines = result.stdout.strip().splitlines()
                for line in lines[-10:]:
                    print(f"    {line}")
            all_passed = False
        else:
            print(f"  PASSED: {name}")

    return all_passed


def detect_repo_platform() -> str:
    """Detect whether the repo is hosted on GitHub, GitLab, or unknown.

    Checks the git remote URL first, then falls back to CI environment
    variables for self-hosted instances.

    Returns:
        ``"github"``, ``"gitlab"``, or ``"unknown"``.
    """
    # Try remote URL first
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
        url = result.stdout.strip().lower()
        if "github.com" in url:
            return "github"
        if "gitlab.com" in url:
            return "gitlab"
    except subprocess.CalledProcessError:
        pass

    # Fall back to CI environment variables (for self-hosted instances)
    if os.getenv("GITHUB_ACTIONS") == "true":
        return "github"
    if os.getenv("GITLAB_CI") == "true":
        return "gitlab"

    return "unknown"


def create_version_tag(
    version: str,
    *,
    push: bool = False,
    dry_run: bool = False,
) -> None:
    """Create an annotated git tag for the version.

    Args:
        version: Version string (e.g., "1.2.3"). The ``v`` prefix is
                 added automatically.
        push: If True, push the tag to origin after creation.
        dry_run: If True, print what would happen without doing anything.
    """
    tag = f"v{version}"

    if dry_run:
        print(f"[dry-run] Would create tag: {tag}")
        if push:
            print(f"[dry-run] Would push tag: {tag}")
        return

    print(f"Creating tag: {tag}")
    subprocess.run(
        ["git", "tag", "-a", tag, "-m", tag],
        check=True,
    )

    if push:
        print(f"Pushing tag: {tag}")
        subprocess.run(
            ["git", "push", "origin", tag],
            check=True,
        )


def apply_version(
    new_version: str,
    *,
    pyproject_path: Path = DEFAULT_PYPROJECT,
    init_path: Path = DEFAULT_INIT,
    dry_run: bool = False,
    bump_type: BumpType | None = None,
    known_issues: bool = False,
) -> None:
    """Apply a new version to both pyproject.toml and __init__.py.

    For major bumps, quality gates are enforced unless --known-issues
    is set.

    Args:
        new_version: The new version string to write.
        pyproject_path: Path to pyproject.toml.
        init_path: Path to src/rfc/__init__.py.
        dry_run: If True, print what would change but don't write.
        bump_type: The bump type (used to enforce quality gates for major).
        known_issues: If True, bypass quality gates for major bumps.
    """
    # Enforce quality gates for major bumps
    if bump_type == BumpType.MAJOR and not known_issues:
        print("Major version bump — running quality gates...")
        if not run_quality_gates():
            print(
                "\nQuality gates FAILED. Major bump aborted."
                "\nUse --known-issues to bypass (issues must be documented)."
            )
            sys.exit(1)
        print("Quality gates PASSED.\n")

    if dry_run:
        print(f'[dry-run] Would update pyproject.toml: version = "{new_version}"')
        print(f'[dry-run] Would update __init__.py: __version__ = "{new_version}"')
        return

    # Update pyproject.toml
    pyproject_text = pyproject_path.read_text()
    pyproject_text = re.sub(
        r'version\s*=\s*"[^"]+"',
        f'version = "{new_version}"',
        pyproject_text,
        count=1,
    )
    pyproject_path.write_text(pyproject_text)

    # Update __init__.py
    init_text = init_path.read_text()
    init_text = re.sub(
        r'__version__\s*=\s*"[^"]+"',
        f'__version__ = "{new_version}"',
        init_text,
        count=1,
    )
    init_path.write_text(init_text)


def main() -> None:
    """CLI entry point for version bumping."""
    parser = argparse.ArgumentParser(
        description="Auto-increment version based on conventional commit messages.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without modifying files.",
    )
    parser.add_argument(
        "--bump",
        choices=["patch", "minor", "major"],
        help="Force a specific bump type (overrides commit detection).",
    )
    parser.add_argument(
        "--from-commit",
        help="Git ref to scan commits from (default: last version tag).",
    )
    parser.add_argument(
        "--known-issues",
        action="store_true",
        help="Bypass quality gates for major bumps (issues must be documented).",
    )
    parser.add_argument(
        "--push-tag",
        action="store_true",
        help="Push the created tag to origin.",
    )
    parser.add_argument(
        "--no-tag",
        action="store_true",
        help="Skip tag creation (only update version files).",
    )
    args = parser.parse_args()

    # Detect repo platform
    platform = detect_repo_platform()
    print(f"Repository platform: {platform}")

    current = read_current_version()
    print(f"Current version: {current}")

    # Determine bump type
    if args.bump:
        bump_type = BumpType[args.bump.upper()]
        print(f"Forced bump type: {bump_type.name.lower()}")
    else:
        commits = get_commits_since_tag(args.from_commit)
        if not commits:
            print("No commits found since last tag. Nothing to bump.")
            return

        print(f"\nCommits since last tag ({len(commits)}):")
        for c in commits:
            print(f"  - {c}")

        bump_type = determine_bump(commits)
        if bump_type is None:
            print("\nNo bump-worthy commits (only docs/chore/test/refactor). Skipping.")
            return

        print(f"\nDetected bump type: {bump_type.name.lower()}")

    new_version = bump_version(current, bump_type)
    print(f"New version: {current} → {new_version}")

    if args.dry_run:
        print("\n[dry-run] No files modified.")
        apply_version(new_version, dry_run=True, bump_type=bump_type)
        if not args.no_tag:
            create_version_tag(new_version, push=args.push_tag, dry_run=True)
        return

    apply_version(
        new_version,
        bump_type=bump_type,
        known_issues=args.known_issues,
    )
    print(f"\nVersion updated to {new_version} in:")
    print("  - pyproject.toml")
    print("  - src/rfc/__init__.py")

    if not args.no_tag:
        print()
        create_version_tag(new_version, push=args.push_tag)


if __name__ == "__main__":
    main()
