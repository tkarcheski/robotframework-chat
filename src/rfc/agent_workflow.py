"""Agent workflow: complete session with all interactions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agent_interaction import AgentInteraction
from .agent_memory import AgentMemory
from .agent_state import ExecutionState
from .agent_tool import ToolCall, ToolResult


@dataclass(frozen=True)
class AgentWorkflow:
    """Complete agent session: many interactions, unified state, and memory."""

    workflow_id: str
    agent_id: str
    task_description: str
    started_at: float
    ended_at: float | None
    status: str
    interactions: tuple[AgentInteraction, ...] = field(default_factory=tuple)
    memory: AgentMemory = field(default_factory=AgentMemory)
    initial_state: ExecutionState | None = None
    final_state: ExecutionState | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def interaction_count(self) -> int:
        """Return number of interactions (turns) in this workflow."""
        return len(self.interactions)

    def tool_calls_by_name(self) -> dict[str, list[ToolCall]]:
        """Return all tool calls grouped by tool name."""
        result: dict[str, list[ToolCall]] = {}
        for interaction in self.interactions:
            for call in interaction.tool_calls:
                result.setdefault(call.tool_name, []).append(call)
        return result

    def successful_tool_calls(self) -> list[tuple[ToolCall, ToolResult]]:
        """Return all (ToolCall, ToolResult) pairs that succeeded."""
        result = []
        for interaction in self.interactions:
            result_map = {r.tool_call_id: r for r in interaction.tool_results}
            for call in interaction.tool_calls:
                if call.id in result_map:
                    r = result_map[call.id]
                    if r.success:
                        result.append((call, r))
        return result
