"""Tests for agent workflows (complete sessions)."""

import pytest

from rfc.agent_interaction import AgentInteraction
from rfc.agent_memory import AgentMemory
from rfc.agent_state import ExecutionState
from rfc.agent_tool import ToolCall, ToolResult
from rfc.agent_workflow import AgentWorkflow


class TestAgentWorkflow:
    """AgentWorkflow: Complete agent session with all interactions and state."""

    def test_creates_workflow(self):
        workflow = AgentWorkflow(
            workflow_id="wf-001",
            agent_id="claude-agent",
            task_description="Resolve GitHub issue by creating PR",
            started_at=1234567890.0,
            ended_at=1234567900.0,
            status="completed",
        )
        assert workflow.workflow_id == "wf-001"
        assert workflow.agent_id == "claude-agent"
        assert workflow.status == "completed"

    def test_workflow_tracks_multiple_interactions(self):
        """A workflow contains many interactions (turns)."""
        interaction1 = AgentInteraction(
            turn_number=1,
            messages=(),
            tool_calls=(),
            tool_results=(),
            state_before={},
            state_after={},
            reasoning="Analyzing issue",
            duration_ms=1000.0,
            success=True,
        )
        interaction2 = AgentInteraction(
            turn_number=2,
            messages=(),
            tool_calls=(),
            tool_results=(),
            state_before={},
            state_after={},
            reasoning="Creating branch",
            duration_ms=500.0,
            success=True,
        )
        workflow = AgentWorkflow(
            workflow_id="wf-001",
            agent_id="test-agent",
            task_description="Test",
            started_at=1.0,
            ended_at=2.0,
            status="completed",
            interactions=(interaction1, interaction2),
        )
        assert workflow.interaction_count() == 2

    def test_workflow_status_values(self):
        """Workflow can be running, completed, failed, or paused."""
        for status in ["running", "completed", "failed", "paused"]:
            workflow = AgentWorkflow(
                workflow_id="wf-001",
                agent_id="agent",
                task_description="",
                started_at=1.0,
                ended_at=None if status == "running" else 2.0,
                status=status,
            )
            assert workflow.status == status

    def test_workflow_with_error(self):
        """Workflow can record errors from execution."""
        workflow = AgentWorkflow(
            workflow_id="wf-001",
            agent_id="agent",
            task_description="",
            started_at=1.0,
            ended_at=2.0,
            status="failed",
            error="API rate limit exceeded",
        )
        assert workflow.status == "failed"
        assert workflow.error == "API rate limit exceeded"

    def test_workflow_with_memory(self):
        """Workflow includes memory from all interactions."""
        memory = AgentMemory(
            short_term=["Issue #123 analyzed"],
            persistent_facts={"issue_id": 123, "repo": "foo/bar"},
            execution_ledger=[{"action": "fetch"}],
        )
        workflow = AgentWorkflow(
            workflow_id="wf-001",
            agent_id="agent",
            task_description="",
            started_at=1.0,
            ended_at=2.0,
            status="completed",
            memory=memory,
        )
        assert len(workflow.memory.short_term) == 1
        assert workflow.memory.persistent_facts["issue_id"] == 123

    def test_workflow_with_initial_and_final_state(self):
        """Workflow can capture initial and final execution states."""
        initial = ExecutionState(
            timestamp=1.0,
            variables={"attempt": 0},
            memory=AgentMemory(),
            completed_tasks=[],
            failed_tasks=[],
            next_action="start",
            context_usage={},
        )
        final = ExecutionState(
            timestamp=2.0,
            variables={"attempt": 3},
            memory=AgentMemory(persistent_facts={"pr_number": 456}),
            completed_tasks=["create_pr"],
            failed_tasks=[],
            next_action=None,
            context_usage={"tokens_used": 5000},
        )
        workflow = AgentWorkflow(
            workflow_id="wf-001",
            agent_id="agent",
            task_description="",
            started_at=1.0,
            ended_at=2.0,
            status="completed",
            initial_state=initial,
            final_state=final,
        )
        assert workflow.initial_state.variables["attempt"] == 0
        assert workflow.final_state.variables["attempt"] == 3
        assert workflow.final_state.memory.persistent_facts["pr_number"] == 456

    def test_workflow_metadata(self):
        """Workflow can store arbitrary metadata."""
        metadata = {
            "model": "claude-opus",
            "temperature": 0.7,
            "tags": ["test", "prod"],
        }
        workflow = AgentWorkflow(
            workflow_id="wf-001",
            agent_id="agent",
            task_description="",
            started_at=1.0,
            ended_at=2.0,
            status="completed",
            metadata=metadata,
        )
        assert workflow.metadata["model"] == "claude-opus"
        assert "test" in workflow.metadata["tags"]

    def test_tool_calls_by_name(self):
        """Query all tool calls by name across all interactions."""
        git_call = ToolCall(
            id="c1",
            tool_name="git_clone",
            arguments={"url": "https://github.com/foo/bar.git"},
            timestamp=1.0,
            call_number=0,
        )
        fs_call = ToolCall(
            id="c2",
            tool_name="filesystem",
            arguments={"cmd": "write"},
            timestamp=2.0,
            call_number=1,
        )
        git_call2 = ToolCall(
            id="c3",
            tool_name="git_clone",
            arguments={"url": "https://github.com/baz/qux.git"},
            timestamp=3.0,
            call_number=2,
        )
        interaction = AgentInteraction(
            turn_number=1,
            messages=(),
            tool_calls=(git_call, fs_call, git_call2),
            tool_results=(),
            state_before={},
            state_after={},
            reasoning="",
            duration_ms=0.0,
            success=True,
        )
        workflow = AgentWorkflow(
            workflow_id="wf-001",
            agent_id="agent",
            task_description="",
            started_at=1.0,
            ended_at=2.0,
            status="completed",
            interactions=(interaction,),
        )
        by_name = workflow.tool_calls_by_name()
        assert len(by_name["git_clone"]) == 2
        assert len(by_name["filesystem"]) == 1

    def test_successful_tool_calls(self):
        """Query all successful tool call + result pairs."""
        call1 = ToolCall("c1", "tool_a", {}, 1.0, 0)
        result1 = ToolResult("c1", True, "Success 1")

        call2 = ToolCall("c2", "tool_b", {}, 2.0, 1)
        result2 = ToolResult("c2", False, "", "Failed")

        call3 = ToolCall("c3", "tool_a", {}, 3.0, 2)
        result3 = ToolResult("c3", True, "Success 2")

        interaction = AgentInteraction(
            turn_number=1,
            messages=(),
            tool_calls=(call1, call2, call3),
            tool_results=(result1, result2, result3),
            state_before={},
            state_after={},
            reasoning="",
            duration_ms=0.0,
            success=True,
        )
        workflow = AgentWorkflow(
            workflow_id="wf-001",
            agent_id="agent",
            task_description="",
            started_at=1.0,
            ended_at=2.0,
            status="completed",
            interactions=(interaction,),
        )
        successful = workflow.successful_tool_calls()
        assert len(successful) == 2
        assert successful[0][0].id == "c1"
        assert successful[1][0].id == "c3"

    def test_workflow_is_frozen(self):
        """AgentWorkflow is frozen/immutable."""
        workflow = AgentWorkflow(
            workflow_id="wf-001",
            agent_id="agent",
            task_description="",
            started_at=1.0,
            ended_at=None,
            status="running",
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            workflow.status = "completed"

    def test_workflow_defaults(self):
        """Workflow has sensible defaults for optional fields."""
        workflow = AgentWorkflow(
            workflow_id="wf-001",
            agent_id="agent",
            task_description="",
            started_at=1.0,
            ended_at=2.0,
            status="completed",
        )
        assert workflow.interactions == ()
        assert isinstance(workflow.memory, AgentMemory)
        assert workflow.initial_state is None
        assert workflow.final_state is None
        assert workflow.error is None
        assert workflow.metadata == {}
