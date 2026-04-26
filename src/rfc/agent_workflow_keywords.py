"""Robot Framework keywords for OpenClaw-style agent workflow testing.

Pairs with :mod:`rfc.agent_workflow_listener` — keywords build a workflow
in-memory via :class:`AgentInteractionTracker` and emit it as a single
``RFC_DATA: agent_workflow`` payload at end of workflow.  The listener
deserialises and persists it.

Example usage in a Robot test::

    Library  rfc.agent_workflow_keywords.AgentWorkflowKeywords  WITH NAME  Agent

    Agent.Start Agent Workflow    wf-1    claude    Resolve issue
    Agent.Start Interaction       1
    Agent.Agent Message           user      Please clone the repo
    ${cid}=  Agent.Agent Calls Tool      git    {"cmd": "clone"}
    Agent.Agent Receives Tool Result    ${cid}    ${True}    cloned
    Agent.End Interaction         ${True}
    Agent.End Agent Workflow      ${True}
"""

from __future__ import annotations

import json
from typing import Any, Optional

from robot.api import logger  # type: ignore
from robot.api.deco import keyword  # type: ignore

from .agent_interaction_tracker import AgentInteractionTracker
from .agent_tool import ToolCall, ToolSchema
from .agent_workflow_db import workflow_to_dict
from .agent_workflow_listener import AGENT_WORKFLOW_DATA_KEY
from .rfc_data import emit_rfc_data
from .tool_call_validator import ToolCallValidator


def _coerce_bool(value: Any) -> bool:
    """Robot passes booleans as Python bool when ${True} is used; tolerate strings too."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


class AgentWorkflowKeywords:
    """Drive an :class:`AgentInteractionTracker` from Robot Framework keywords."""

    def __init__(self) -> None:
        self._tracker: Optional[AgentInteractionTracker] = None
        self._validator = ToolCallValidator()

    # ------------------------------------------------------------------
    # Workflow lifecycle
    # ------------------------------------------------------------------

    @keyword("Start Agent Workflow")
    def start_agent_workflow(
        self, workflow_id: str, agent_id: str, task: str
    ) -> None:
        """Initialise tracking for a new agent workflow."""
        self._tracker = AgentInteractionTracker(workflow_id, agent_id, task)
        logger.info(f"Started workflow {workflow_id} for agent {agent_id}")

    @keyword("End Agent Workflow")
    def end_agent_workflow(
        self, success: Any = True, error: str = ""
    ) -> dict[str, Any]:
        """Finalise the workflow and emit it for the listener."""
        tracker = self._require_tracker()
        workflow = tracker.end_workflow(
            success=_coerce_bool(success),
            error=error or None,
        )
        payload = workflow_to_dict(workflow)
        emit_rfc_data(AGENT_WORKFLOW_DATA_KEY, json.dumps(payload, default=str))
        return payload

    @keyword("Get Workflow Summary")
    def get_workflow_summary(self) -> dict[str, Any]:
        """Return a small dict describing the in-flight workflow."""
        tracker = self._require_tracker()
        wf = tracker.workflow
        total_calls = sum(len(i.tool_calls) for i in wf.interactions)
        return {
            "workflow_id": wf.workflow_id,
            "agent_id": wf.agent_id,
            "turns": len(wf.interactions),
            "tool_calls": total_calls,
            "successful_calls": len(wf.successful_tool_calls()),
            "status": str(wf.status),
        }

    # ------------------------------------------------------------------
    # Interaction (turn) lifecycle
    # ------------------------------------------------------------------

    @keyword("Start Interaction")
    def start_interaction(self, turn_number: Any) -> None:
        """Begin a new conversation turn."""
        tracker = self._require_tracker()
        tracker.start_interaction(int(turn_number))

    @keyword("End Interaction")
    def end_interaction(self, success: Any = True, error: str = "") -> None:
        """Finalise the current turn."""
        tracker = self._require_tracker()
        tracker.end_interaction(
            success=_coerce_bool(success), error=error or None
        )

    @keyword("Set Interaction State")
    def set_interaction_state(
        self, reasoning: str, state_before: str = "{}", state_after: str = "{}"
    ) -> None:
        """Capture reasoning and JSON state snapshots for the current turn."""
        tracker = self._require_tracker()
        tracker.set_interaction_state(
            reasoning=reasoning,
            state_before=json.loads(state_before),
            state_after=json.loads(state_after),
        )

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    @keyword("Agent Message")
    def agent_message(self, role: str, content: str) -> None:
        """Append a message (user/assistant/system) to the current turn."""
        if role not in ("user", "assistant", "system"):
            raise ValueError(
                f"role must be one of user|assistant|system, got {role!r}"
            )
        tracker = self._require_tracker()
        tracker.add_message(role, content)

    # ------------------------------------------------------------------
    # Tool calls and results
    # ------------------------------------------------------------------

    @keyword("Agent Calls Tool")
    def agent_calls_tool(self, tool_name: str, arguments_json: str = "{}") -> str:
        """Log a tool call (arguments as JSON string).  Returns the call id."""
        tracker = self._require_tracker()
        try:
            args = json.loads(arguments_json)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"arguments_json must be valid JSON: {exc}"
            ) from exc
        if not isinstance(args, dict):
            raise ValueError("arguments_json must decode to an object")
        return tracker.add_tool_call(tool_name, args)

    @keyword("Agent Receives Tool Result")
    def agent_receives_tool_result(
        self,
        call_id: str,
        success: Any = True,
        output: str = "",
        error: str = "",
        execution_time_ms: Any = 0.0,
    ) -> None:
        """Record the result of the most recent tool call."""
        tracker = self._require_tracker()
        tracker.add_tool_result(
            call_id=call_id,
            success=_coerce_bool(success),
            output=output,
            error=error or None,
            execution_time_ms=float(execution_time_ms),
        )

    # ------------------------------------------------------------------
    # Tool schema validation
    # ------------------------------------------------------------------

    @keyword("Register Tool Schema")
    def register_tool_schema(
        self, tool_name: str, schema_json: str
    ) -> None:
        """Register the expected schema for a tool (JSON string)."""
        schema_dict = json.loads(schema_json)
        self._validator.register_tool(
            ToolSchema(
                name=tool_name,
                description=schema_dict.get("description", ""),
                parameters=schema_dict.get("parameters", {}),
                required=schema_dict.get("required", []),
            )
        )

    @keyword("Validate Tool Call Schema")
    def validate_tool_call_schema(
        self, tool_name: str, arguments_json: str
    ) -> None:
        """Assert that the given tool call satisfies the registered schema."""
        call = ToolCall(
            id="validation-check",
            tool_name=tool_name,
            arguments=json.loads(arguments_json),
            timestamp=0.0,
            call_number=0,
        )
        ok, msg = self._validator.validate_call_schema(call)
        if not ok:
            raise AssertionError(f"Tool call validation failed: {msg}")

    # ------------------------------------------------------------------
    # Assertions across the captured workflow
    # ------------------------------------------------------------------

    @keyword("Assert Tool Was Called")
    def assert_tool_was_called(
        self, tool_name: str, count: Any = 1
    ) -> None:
        """Assert ``tool_name`` was called exactly ``count`` times across all turns."""
        tracker = self._require_tracker()
        actual = len(
            tracker.workflow.tool_calls_by_name().get(tool_name, [])
        )
        expected = int(count)
        if actual != expected:
            raise AssertionError(
                f"Expected {expected} call(s) to {tool_name!r}, got {actual}"
            )

    @keyword("Assert Tool Calls In Order")
    def assert_tool_calls_in_order(self, *tool_names: str) -> None:
        """Assert all tool calls appeared in the given order across all turns."""
        tracker = self._require_tracker()
        all_calls = [
            c for i in tracker.workflow.interactions for c in i.tool_calls
        ]
        ok, msg = self._validator.validate_call_sequence(
            all_calls, list(tool_names)
        )
        if not ok:
            raise AssertionError(msg)

    @keyword("Assert All Tool Calls Succeeded")
    def assert_all_tool_calls_succeeded(self) -> None:
        """Assert every tool result captured so far reports success."""
        tracker = self._require_tracker()
        for interaction in tracker.workflow.interactions:
            for result in interaction.tool_results:
                if not result.success:
                    raise AssertionError(
                        f"Tool call {result.tool_call_id} failed: {result.error}"
                    )

    # ------------------------------------------------------------------

    def _require_tracker(self) -> AgentInteractionTracker:
        if self._tracker is None:
            raise AssertionError(
                "No active agent workflow; call 'Start Agent Workflow' first"
            )
        return self._tracker
