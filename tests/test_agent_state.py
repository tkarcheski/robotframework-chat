"""Tests for agent execution state snapshots."""

import pytest

from rfc.agent_memory import AgentMemory
from rfc.agent_state import ExecutionState


class TestExecutionState:
    """ExecutionState: Snapshot of agent execution context at a point in time."""

    def test_creates_execution_state(self):
        state = ExecutionState(
            timestamp=1234567890.0,
            variables={"issue_id": 123, "repo_path": "/tmp/repo"},
            memory=AgentMemory(),
            completed_tasks=["fetch_issue"],
            failed_tasks=[],
            next_action="analyze_issue",
            context_usage={"tokens_used": 1500, "memory_mb": 512},
        )
        assert state.timestamp == 1234567890.0
        assert state.variables["issue_id"] == 123
        assert state.completed_tasks == ["fetch_issue"]
        assert state.next_action == "analyze_issue"

    def test_state_tracks_completed_tasks(self):
        """Track which tasks have completed successfully."""
        state = ExecutionState(
            timestamp=1.0,
            variables={},
            memory=AgentMemory(),
            completed_tasks=["fetch_issue", "analyze", "create_branch"],
            failed_tasks=[],
            next_action=None,
            context_usage={},
        )
        assert len(state.completed_tasks) == 3
        assert "analyze" in state.completed_tasks

    def test_state_tracks_failed_tasks(self):
        """Track which tasks have failed."""
        state = ExecutionState(
            timestamp=1.0,
            variables={},
            memory=AgentMemory(),
            completed_tasks=["fetch_issue"],
            failed_tasks=["push_changes"],
            next_action="retry_push",
            context_usage={},
        )
        assert len(state.failed_tasks) == 1
        assert "push_changes" in state.failed_tasks

    def test_state_with_variables(self):
        """Store current execution variables."""
        variables = {
            "current_branch": "main",
            "files_modified": ["src/main.py", "tests/test_main.py"],
            "pr_number": None,
            "attempt_count": 2,
        }
        state = ExecutionState(
            timestamp=1.0,
            variables=variables,
            memory=AgentMemory(),
            completed_tasks=[],
            failed_tasks=[],
            next_action=None,
            context_usage={},
        )
        assert state.variables["current_branch"] == "main"
        assert state.variables["files_modified"][0] == "src/main.py"
        assert state.variables["pr_number"] is None
        assert state.variables["attempt_count"] == 2

    def test_state_with_memory(self):
        """Include memory snapshot in state."""
        memory = AgentMemory(
            short_term=["Analyzed issue #123"],
            persistent_facts={"issue_id": 123},
            execution_ledger=[{"action": "fetch"}],
        )
        state = ExecutionState(
            timestamp=1.0,
            variables={},
            memory=memory,
            completed_tasks=[],
            failed_tasks=[],
            next_action=None,
            context_usage={},
        )
        assert len(state.memory.short_term) == 1
        assert state.memory.persistent_facts["issue_id"] == 123

    def test_state_context_usage_tracking(self):
        """Track resource usage (tokens, memory, etc.)."""
        context_usage = {
            "tokens_used": 2500,
            "tokens_remaining": 4500,
            "memory_mb": 256,
            "execution_time_ms": 1500,
        }
        state = ExecutionState(
            timestamp=1.0,
            variables={},
            memory=AgentMemory(),
            completed_tasks=[],
            failed_tasks=[],
            next_action=None,
            context_usage=context_usage,
        )
        assert state.context_usage["tokens_used"] == 2500
        assert state.context_usage["memory_mb"] == 256

    def test_state_is_frozen(self):
        """ExecutionState is immutable once created."""
        state = ExecutionState(
            timestamp=1.0,
            variables={},
            memory=AgentMemory(),
            completed_tasks=[],
            failed_tasks=[],
            next_action=None,
            context_usage={},
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            state.next_action = "changed"

    def test_state_with_pending_action(self):
        """next_action can be None (terminal) or a string (pending)."""
        pending = ExecutionState(
            timestamp=1.0,
            variables={},
            memory=AgentMemory(),
            completed_tasks=[],
            failed_tasks=[],
            next_action="create_pr",
            context_usage={},
        )
        terminal = ExecutionState(
            timestamp=2.0,
            variables={},
            memory=AgentMemory(),
            completed_tasks=["create_pr"],
            failed_tasks=[],
            next_action=None,
            context_usage={},
        )
        assert pending.next_action == "create_pr"
        assert terminal.next_action is None
