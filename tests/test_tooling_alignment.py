"""Guard against ruff version skew between pyproject and pre-commit (#478).

The drift in issue #478 recurred because two formatters ran at different
versions: the ``ruff-pre-commit`` hook was pinned while the ``ruff`` dev
dependency floated. PR #481 aligned them; these tests fail loudly if either
side is ever bumped without the other, or if the CI format gate is removed.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_ruff_pin() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    dev_deps = data["project"]["optional-dependencies"]["dev"]
    ruff_specs = [d for d in dev_deps if re.match(r"ruff\s*(==|$)", d)]
    assert ruff_specs, "no 'ruff' entry in [project.optional-dependencies].dev"
    spec = ruff_specs[0]
    match = re.fullmatch(r"ruff\s*==\s*([\d.]+)", spec)
    assert match, f"ruff dev dependency is not exact-pinned: {spec!r} (see #478)"
    return match.group(1)


def _precommit_ruff_rev() -> str:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text())
    revs = [
        repo["rev"]
        for repo in config["repos"]
        if "ruff-pre-commit" in repo.get("repo", "")
    ]
    assert revs, "no ruff-pre-commit repo in .pre-commit-config.yaml"
    return revs[0].lstrip("v")


def test_ruff_pin_matches_precommit_hook() -> None:
    """pyproject's ruff pin and the pre-commit hook rev must be identical."""
    assert _pyproject_ruff_pin() == _precommit_ruff_rev(), (
        "ruff version skew: pyproject and .pre-commit-config.yaml disagree — "
        "bump both together or format drift recurs (#478)"
    )


def test_ci_runs_ruff_format_check() -> None:
    """The lint workflow must keep the `ruff format --check .` gate (#478)."""
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "robot-tests.yml").read_text()
    )
    commands = [
        step.get("run", "")
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
    ]
    assert any(re.search(r"ruff format --check", cmd) for cmd in commands), (
        "CI no longer runs 'ruff format --check' — the #478 drift gate was removed"
    )
