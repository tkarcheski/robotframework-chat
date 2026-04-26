"""Robot Framework listener that persists captured agent workflows.

The keyword library emits the finalised workflow via
``emit_rfc_data("agent_workflow", json_payload)`` during
``End Agent Workflow``.  This listener reads that payload from
``BaseListener._current_test_data`` at end-of-test and writes it to the
:class:`AgentWorkflowDatabase`.

Usage::

    robot --listener rfc.agent_workflow_listener.AgentWorkflowListener tests/
    robot --listener rfc.agent_workflow_listener.AgentWorkflowListener:database_url=<URL> tests/

Environment:
    AGENT_WORKFLOW_DATABASE_URL  Preferred — isolates agent rows from
                                 the main test-results DB.
    DATABASE_URL                 Fallback if AGENT_WORKFLOW_DATABASE_URL is
                                 unset.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from .agent_interaction import AgentInteraction, AgentMessage
from .agent_tool import ToolCall, ToolResult
from .agent_workflow import AgentWorkflow
from .agent_workflow_db import AgentWorkflowDatabase
from .base_listener import BaseListener

logger = logging.getLogger(__name__)

AGENT_WORKFLOW_DATA_KEY = "agent_workflow"


class AgentWorkflowListener(BaseListener):
    """Persist agent workflows captured via RFC_DATA at end-of-test."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        super().__init__()
        self._database_url = (
            database_url
            or os.getenv("AGENT_WORKFLOW_DATABASE_URL")
            or os.getenv("DATABASE_URL")
        )
        self._db: Optional[AgentWorkflowDatabase] = None
        self._persisted_count = 0

    @property
    def persisted_count(self) -> int:
        return self._persisted_count

    def _get_db(self) -> Optional[AgentWorkflowDatabase]:
        if self._db is not None:
            return self._db
        if not self._database_url:
            return None
        try:
            self._db = AgentWorkflowDatabase(database_url=self._database_url)
        except Exception as exc:
            logger.warning("AgentWorkflowDatabase init failed: %s", exc)
            return None
        return self._db

    def on_test_end(self, data: Any, result: Any) -> None:
        payload = self._current_test_data.get(AGENT_WORKFLOW_DATA_KEY)
        if not payload:
            return

        try:
            workflow_dict = json.loads(payload)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to decode agent workflow payload: %s", exc)
            return

        try:
            workflow = workflow_from_dict(workflow_dict)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Invalid agent workflow payload: %s", exc)
            return

        db = self._get_db()
        if db is None:
            logger.info(
                "AgentWorkflowListener: no DATABASE_URL configured, skipping persist"
            )
            return

        try:
            db.persist_workflow(workflow)
            self._persisted_count += 1
        except Exception as exc:
            logger.warning(
                "Failed to persist agent workflow %s: %s",
                workflow.workflow_id,
                exc,
            )


def workflow_from_dict(payload: dict[str, Any]) -> AgentWorkflow:
    """Inverse of :func:`agent_workflow_db.workflow_to_dict`."""
    interactions = tuple(
        _interaction_from_dict(i) for i in payload.get("interactions", [])
    )
    return AgentWorkflow(
        workflow_id=payload["workflow_id"],
        agent_id=payload["agent_id"],
        task_description=payload["task_description"],
        started_at=float(payload["started_at"]),
        ended_at=(
            float(payload["ended_at"]) if payload.get("ended_at") is not None else None
        ),
        status=payload["status"],
        interactions=interactions,
        error=payload.get("error"),
        metadata=dict(payload.get("metadata", {})),
    )


def _interaction_from_dict(payload: dict[str, Any]) -> AgentInteraction:
    messages = tuple(
        AgentMessage(
            role=m["role"], content=m["content"], timestamp=float(m["timestamp"])
        )
        for m in payload.get("messages", [])
    )
    tool_calls = tuple(
        ToolCall(
            id=c["id"],
            tool_name=c["tool_name"],
            arguments=dict(c.get("arguments", {})),
            timestamp=float(c["timestamp"]),
            call_number=int(c["call_number"]),
        )
        for c in payload.get("tool_calls", [])
    )
    tool_results = tuple(
        ToolResult(
            tool_call_id=r["tool_call_id"],
            success=bool(r["success"]),
            output=r.get("output", ""),
            error=r.get("error"),
            execution_time_ms=float(r.get("execution_time_ms", 0.0)),
        )
        for r in payload.get("tool_results", [])
    )
    return AgentInteraction(
        turn_number=int(payload["turn_number"]),
        messages=messages,
        tool_calls=tool_calls,
        tool_results=tool_results,
        state_before=dict(payload.get("state_before", {})),
        state_after=dict(payload.get("state_after", {})),
        reasoning=payload.get("reasoning", ""),
        duration_ms=float(payload.get("duration_ms", 0.0)),
        success=bool(payload.get("success", True)),
        error=payload.get("error"),
    )
