"""Typed dataclasses for SWE-bench integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


def _require_non_empty_str(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


@dataclass
class SWEBenchInstance:
    """A single SWE-bench task instance."""

    instance_id: str
    repo: str
    problem_statement: str
    patch: str
    test_patch: str
    base_commit: str
    version: str
    # Difficulty annotation from SWE-bench Verified (e.g. "<15 min fix").
    # Empty for datasets without difficulty data (base SWE-bench). Concrete
    # default rather than Optional per the dataclass-fields rule.
    difficulty: str = ""

    def __post_init__(self) -> None:
        _require_non_empty_str(self.instance_id, "instance_id")
        _require_non_empty_str(self.repo, "repo")
        _require_non_empty_str(self.problem_statement, "problem_statement")

    def to_dict(self) -> Dict[str, str]:
        return {
            "instance_id": self.instance_id,
            "repo": self.repo,
            "problem_statement": self.problem_statement,
            "patch": self.patch,
            "test_patch": self.test_patch,
            "base_commit": self.base_commit,
            "version": self.version,
            "difficulty": self.difficulty,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SWEBenchInstance:
        return cls(
            instance_id=d["instance_id"],
            repo=d["repo"],
            problem_statement=d["problem_statement"],
            patch=d["patch"],
            test_patch=d["test_patch"],
            base_commit=d["base_commit"],
            version=d["version"],
            difficulty=str(d.get("difficulty") or ""),
        )


@dataclass
class PatchResult:
    """Result of applying and testing a patch in a sandbox."""

    passed: bool
    test_output: str
    exit_code: int

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise TypeError(f"passed must be a bool, got {type(self.passed).__name__}")
        if not isinstance(self.exit_code, int):
            raise TypeError(
                f"exit_code must be an int, got {type(self.exit_code).__name__}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "test_output": self.test_output,
            "exit_code": self.exit_code,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PatchResult:
        return cls(
            passed=d["passed"],
            test_output=d["test_output"],
            exit_code=d["exit_code"],
        )
