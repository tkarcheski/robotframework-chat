"""Real-time tracking of agent interactions."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .agent_interaction import AgentInteraction, AgentMessage
from .agent_memory import AgentMemory
from .agent_workflow import AgentWorkflow


class _InteractionBuilder:
    """Mutable builder for AgentInteraction (internal use only)."""

    def __init__(self, turn_number: int) -> None:
        self.turn_number = turn_number
        self.messages: list[AgentMessage] = []
        self.tool_calls: list[Any] = []
        self.tool_results: list[Any] = []
        self.state_before: dict[str, Any] = {}
        self.state_after: dict[str, Any] = {}
        self.reasoning: str = ""
        self.duration_ms: float = 0.0
        self.success: bool = True
        self.error: str | None = None

    def build(self) -> AgentInteraction:
        """Create frozen AgentInteraction from builder state."""
        return AgentInteraction(
            turn_number=self.turn_number,
            messages=tuple(self.messages),
            tool_calls=tuple(self.tool_calls),
            tool_results=tuple(self.tool_results),
            state_before=self.state_before,
            state_after=self.state_after,
            reasoning=self.reasoning,
            duration_ms=self.duration_ms,
            success=self.success,
            error=self.error,
        )


class AgentInteractionTracker:
    """Capture multi-turn agent interactions in real-time."""

    def __init__(self, workflow_id: str, agent_id: str, task: str) -> None:
        self.workflow = AgentWorkflow(
            workflow_id=workflow_id,
            agent_id=agent_id,
            task_description=task,
            started_at=time.time(),
            ended_at=None,
            status="running",
            memory=AgentMemory(),
        )
        self._builder: _InteractionBuilder | None = None

    def start_interaction(self, turn_number: int) -> None:
        """Begin tracking a new conversation turn."""
        self._builder = _InteractionBuilder(turn_number)

    def add_message(self, role: str, content: str) -> None:
        """Log a message (user/assistant/system)."""
        assert self._builder is not None, "Call start_interaction() first"
        msg = AgentMessage(role=role, content=content, timestamp=time.time())
        self._builder.messages.append(msg)

    def add_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Log a tool call, return call ID."""
        from .agent_tool import ToolCall

        assert self._builder is not None, "Call start_interaction() first"
        call_id = str(uuid.uuid4())
        call = ToolCall(
            id=call_id,
            tool_name=tool_name,
            arguments=arguments,
            timestamp=time.time(),
            call_number=len(self._builder.tool_calls),
        )
        self._builder.tool_calls.append(call)
        return call_id

    def add_tool_result(
        self,
        call_id: str,
        success: bool,
        output: str = "",
        error: str | None = None,
        execution_time_ms: float = 0.0,
    ) -> None:
        """Log result from tool execution."""
        from .agent_tool import ToolResult

        assert self._builder is not None, "Call start_interaction() first"
        result = ToolResult(
            tool_call_id=call_id,
            success=success,
            output=output,
            error=error,
            execution_time_ms=execution_time_ms,
        )
        self._builder.tool_results.append(result)

    def set_interaction_state(
        self,
        reasoning: str,
        state_before: dict[str, Any],
        state_after: dict[str, Any],
    ) -> None:
        """Capture reasoning and state snapshots."""
        assert self._builder is not None, "Call start_interaction() first"
        self._builder.reasoning = reasoning
        self._builder.state_before = state_before
        self._builder.state_after = state_after

    def end_interaction(self, success: bool, error: str | None = None) -> AgentInteraction:
        """Finalize current turn and add to workflow."""
        assert self._builder is not None, "Call start_interaction() first"

        # Calculate duration based on message timestamps
        duration = 0.0
        if self._builder.messages:
            first_msg_time = self._builder.messages[0].timestamp
            last_msg_time = self._builder.messages[-1].timestamp
            duration = (last_msg_time - first_msg_time) * 1000  # Convert to ms

        self._builder.success = success
        self._builder.error = error
        self._builder.duration_ms = duration

        # Build frozen interaction
        interaction = self._builder.build()

        # Add to workflow
        updated_workflow = AgentWorkflow(
            workflow_id=self.workflow.workflow_id,
            agent_id=self.workflow.agent_id,
            task_description=self.workflow.task_description,
            started_at=self.workflow.started_at,
            ended_at=self.workflow.ended_at,
            status=self.workflow.status,
            interactions=self.workflow.interactions + (interaction,),
            memory=self.workflow.memory,
            initial_state=self.workflow.initial_state,
            final_state=self.workflow.final_state,
            error=self.workflow.error,
            metadata=self.workflow.metadata,
        )
        object.__setattr__(self, "workflow", updated_workflow)
        return interaction

    def end_workflow(self, success: bool, error: str | None = None) -> AgentWorkflow:
        """Finalize entire agent session."""
        status = "completed" if success else "failed"
        updated_workflow = AgentWorkflow(
            workflow_id=self.workflow.workflow_id,
            agent_id=self.workflow.agent_id,
            task_description=self.workflow.task_description,
            started_at=self.workflow.started_at,
            ended_at=time.time(),
            status=status,
            interactions=self.workflow.interactions,
            memory=self.workflow.memory,
            initial_state=self.workflow.initial_state,
            final_state=self.workflow.final_state,
            error=error,
            metadata=self.workflow.metadata,
        )
        object.__setattr__(self, "workflow", updated_workflow)
        return self.workflow
