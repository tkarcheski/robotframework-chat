"""Real-time tracking of agent interactions."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from .agent_interaction import AgentInteraction, AgentMessage
from .agent_memory import AgentMemory
from .agent_tool import ToolCall, ToolResult
from .agent_workflow import AgentWorkflow, WorkflowStatus


@dataclass
class _InteractionBuilder:
    turn_number: int
    messages: list[AgentMessage] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    state_before: dict[str, Any] = field(default_factory=dict)
    state_after: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""

    def build(self, success: bool, error: str | None, duration_ms: float) -> AgentInteraction:
        return AgentInteraction(
            turn_number=self.turn_number,
            messages=tuple(self.messages),
            tool_calls=tuple(self.tool_calls),
            tool_results=tuple(self.tool_results),
            state_before=self.state_before,
            state_after=self.state_after,
            reasoning=self.reasoning,
            duration_ms=duration_ms,
            success=success,
            error=error,
        )


class AgentInteractionTracker:
    """Capture multi-turn agent interactions in real-time."""

    def __init__(self, workflow_id: str, agent_id: str, task: str) -> None:
        self._workflow_id = workflow_id
        self._agent_id = agent_id
        self._task = task
        self._started_at = time.time()
        self._interactions: list[AgentInteraction] = []
        self._memory = AgentMemory()
        self._builder: _InteractionBuilder | None = None
        self._final_workflow: AgentWorkflow | None = None

    @property
    def workflow(self) -> AgentWorkflow:
        if self._final_workflow is not None:
            return self._final_workflow
        return AgentWorkflow(
            workflow_id=self._workflow_id,
            agent_id=self._agent_id,
            task_description=self._task,
            started_at=self._started_at,
            ended_at=None,
            status=WorkflowStatus.RUNNING,
            interactions=tuple(self._interactions),
            memory=self._memory,
        )

    def is_interaction_active(self) -> bool:
        return self._builder is not None

    def start_interaction(self, turn_number: int) -> None:
        if self._builder is not None:
            raise RuntimeError(
                f"Cannot start interaction {turn_number}: "
                f"interaction {self._builder.turn_number} is already active. "
                f"Call end_interaction() first."
            )
        self._builder = _InteractionBuilder(turn_number=turn_number)

    def add_message(self, role: str, content: str) -> None:
        builder = self._require_builder()
        builder.messages.append(AgentMessage(role=role, content=content, timestamp=time.time()))

    def add_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        builder = self._require_builder()
        call_id = str(uuid.uuid4())
        builder.tool_calls.append(
            ToolCall(
                id=call_id,
                tool_name=tool_name,
                arguments=arguments,
                timestamp=time.time(),
                call_number=len(builder.tool_calls),
            )
        )
        return call_id

    def add_tool_result(
        self,
        call_id: str,
        success: bool,
        output: str = "",
        error: str | None = None,
        execution_time_ms: float = 0.0,
    ) -> None:
        builder = self._require_builder()
        builder.tool_results.append(
            ToolResult(
                tool_call_id=call_id,
                success=success,
                output=output,
                error=error,
                execution_time_ms=execution_time_ms,
            )
        )

    def set_interaction_state(
        self,
        reasoning: str,
        state_before: dict[str, Any],
        state_after: dict[str, Any],
    ) -> None:
        builder = self._require_builder()
        builder.reasoning = reasoning
        builder.state_before = state_before
        builder.state_after = state_after

    def end_interaction(self, success: bool, error: str | None = None) -> AgentInteraction:
        builder = self._require_builder()
        duration_ms = 0.0
        if builder.messages:
            duration_ms = (builder.messages[-1].timestamp - builder.messages[0].timestamp) * 1000
        interaction = builder.build(success=success, error=error, duration_ms=duration_ms)
        self._interactions.append(interaction)
        self._builder = None
        return interaction

    def end_workflow(self, success: bool, error: str | None = None) -> AgentWorkflow:
        self._final_workflow = replace(
            self.workflow,
            ended_at=time.time(),
            status=WorkflowStatus.COMPLETED if success else WorkflowStatus.FAILED,
            error=error,
        )
        return self._final_workflow

    def _require_builder(self) -> _InteractionBuilder:
        if self._builder is None:
            raise RuntimeError("No active interaction; call start_interaction() first")
        return self._builder
