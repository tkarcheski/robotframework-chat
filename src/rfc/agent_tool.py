"""Tool definitions and call/result tracking for agents."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4


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


def new_tool_call(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    call_number: int = 0,
    call_id: str | None = None,
    timestamp: float | None = None,
) -> ToolCall:
    """Build a ``ToolCall`` with a generated id and timestamp.

    Additive convenience factory so callers that dispatch tools (the ReAct
    runtime, the MCP server, the computer-use dispatcher) do not each
    re-implement id/timestamp boilerplate. Existing ``ToolCall`` construction
    is unaffected; this only wraps it.
    """
    return ToolCall(
        id=call_id or f"call-{uuid4().hex[:12]}",
        tool_name=tool_name,
        arguments=dict(arguments or {}),
        timestamp=time.time() if timestamp is None else timestamp,
        call_number=call_number,
    )
