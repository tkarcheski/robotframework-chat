"""Execution state snapshots for agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .agent_memory import AgentMemory


@dataclass(frozen=True)
class ExecutionState:
    """Snapshot of agent execution state at a point in time."""

    timestamp: float
    variables: dict[str, Any]
    memory: AgentMemory
    completed_tasks: list[str]
    failed_tasks: list[str]
    next_action: str | None
    context_usage: dict[str, int]
