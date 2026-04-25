"""Agent interaction (conversation turn) tracking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .agent_tool import ToolCall, ToolResult


@dataclass(frozen=True)
class AgentMessage:
    """One message in a multi-turn conversation."""

    role: str
    content: str
    timestamp: float


@dataclass(frozen=True)
class AgentInteraction:
    """One complete turn: messages, reasoning, tool calls, and state changes."""

    turn_number: int
    messages: tuple[AgentMessage, ...]
    tool_calls: tuple[ToolCall, ...]
    tool_results: tuple[ToolResult, ...]
    state_before: dict[str, Any]
    state_after: dict[str, Any]
    reasoning: str
    duration_ms: float
    success: bool
    error: str | None = None
