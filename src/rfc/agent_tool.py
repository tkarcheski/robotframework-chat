"""Tool definitions and call/result tracking for agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSchema:
    """Declarative tool definition with JSON Schema parameters."""

    name: str
    description: str
    parameters: dict[str, Any]
    required: list[str]


@dataclass(frozen=True)
class ToolCall:
    """One invocation of a tool by an agent."""

    id: str
    tool_name: str
    arguments: dict[str, Any]
    timestamp: float
    call_number: int


@dataclass(frozen=True)
class ToolResult:
    """Outcome of one tool execution."""

    tool_call_id: str
    success: bool
    output: str
    error: str | None = None
    execution_time_ms: float = 0.0
