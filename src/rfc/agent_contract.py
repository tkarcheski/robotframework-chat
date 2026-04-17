"""Machine-readable workflow contract for AI coding agents.

The ``config/agent_contract.yaml`` file is the single source of truth for each
agent's workflow rules. Tests and verifiers load it through ``load_agent_contract``
so that prose updates to ``CLAUDE.md`` and the PR template cannot drift silently
away from what the agentic-coding suite actually enforces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONTRACT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "agent_contract.yaml"
)


@dataclass(frozen=True)
class AgentContract:
    """Frozen workflow contract for a single agent id."""

    agent_id: str
    base_branch: str
    branch_regex: str
    startup_checks: tuple[str, ...]
    pr_template_path: str
    pr_required_sections: tuple[str, ...]
    commit_types: tuple[str, ...]
    commit_subject_regex: str
    min_clarifying_questions: int
    max_clarifying_questions: int
    forbidden_commands: tuple[str, ...] = field(default_factory=tuple)

    def branch_matches(self, branch: str) -> bool:
        return re.match(self.branch_regex, branch) is not None

    def commit_subject_matches(self, subject: str) -> bool:
        return re.match(self.commit_subject_regex, subject) is not None


def _coerce_contract(agent_id: str, raw: dict[str, Any]) -> AgentContract:
    required_keys = [
        "base_branch",
        "branch_regex",
        "startup_checks",
        "pr_template_path",
        "pr_required_sections",
        "commit_types",
        "commit_subject_regex",
        "min_clarifying_questions",
        "max_clarifying_questions",
    ]
    missing = [k for k in required_keys if k not in raw]
    if missing:
        raise ValueError(f"Agent contract for {agent_id!r} missing keys: {missing}")

    return AgentContract(
        agent_id=agent_id,
        base_branch=str(raw["base_branch"]),
        branch_regex=str(raw["branch_regex"]),
        startup_checks=tuple(raw["startup_checks"]),
        pr_template_path=str(raw["pr_template_path"]),
        pr_required_sections=tuple(raw["pr_required_sections"]),
        commit_types=tuple(raw["commit_types"]),
        commit_subject_regex=str(raw["commit_subject_regex"]),
        min_clarifying_questions=int(raw["min_clarifying_questions"]),
        max_clarifying_questions=int(raw["max_clarifying_questions"]),
        forbidden_commands=tuple(raw.get("forbidden_commands", [])),
    )


def load_agent_contract(agent_id: str, *, path: Path | None = None) -> AgentContract:
    """Load an agent's workflow contract by id.

    Raises :class:`KeyError` if ``agent_id`` is not defined in the contract file.
    """
    contract_path = path or DEFAULT_CONTRACT_PATH
    data = yaml.safe_load(contract_path.read_text()) or {}
    if agent_id not in data:
        raise KeyError(f"{agent_id!r} not defined in {contract_path}")
    return _coerce_contract(agent_id, data[agent_id])
