"""Tests for src/rfc/agent_workflow_db.py (SQLite backend round-trip)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfc.agent_interaction_tracker import AgentInteractionTracker
from rfc.agent_workflow import AgentWorkflow, WorkflowStatus
from rfc.agent_workflow_db import (
    AgentWorkflowDatabase,
    workflow_to_dict,
)


def _build_minimal_workflow(workflow_id: str = "wf-1") -> AgentWorkflow:
    tracker = AgentInteractionTracker(workflow_id, "claude", "Test task")
    tracker.start_interaction(1)
    tracker.add_message("user", "do thing")
    tracker.add_message("assistant", "ok")
    cid = tracker.add_tool_call("git", {"cmd": "status"})
    tracker.add_tool_result(cid, success=True, output="clean", execution_time_ms=12.5)
    tracker.set_interaction_state(
        reasoning="run git status",
        state_before={"branch": "main"},
        state_after={"branch": "main", "dirty": False},
    )
    tracker.end_interaction(success=True)
    return tracker.end_workflow(success=True)


@pytest.fixture
def db(tmp_path: Path) -> AgentWorkflowDatabase:
    return AgentWorkflowDatabase(db_path=str(tmp_path / "agent.db"))


class TestSerialisation:
    def test_workflow_to_dict_includes_interactions(self) -> None:
        wf = _build_minimal_workflow()
        d = workflow_to_dict(wf)
        assert d["workflow_id"] == "wf-1"
        assert d["status"] == WorkflowStatus.COMPLETED
        assert len(d["interactions"]) == 1
        assert d["interactions"][0]["tool_calls"][0]["tool_name"] == "git"

    def test_workflow_to_dict_is_json_serialisable(self) -> None:
        wf = _build_minimal_workflow()
        # Round-trip through json to confirm no non-serialisable values leaked.
        encoded = json.dumps(workflow_to_dict(wf), default=str)
        decoded = json.loads(encoded)
        assert decoded["agent_id"] == "claude"


class TestPersist:
    def test_persist_then_get(self, db: AgentWorkflowDatabase) -> None:
        wf = _build_minimal_workflow()
        pk = db.persist_workflow(wf)
        assert pk > 0
        loaded = db.get_workflow("wf-1")
        assert loaded is not None
        assert loaded["agent_id"] == "claude"
        assert loaded["status"] == "completed"
        assert len(loaded["interactions"]) == 1
        assert loaded["interactions"][0]["tool_calls"][0]["tool_name"] == "git"
        assert loaded["interactions"][0]["tool_results"][0]["success"] is True

    def test_get_returns_none_for_unknown(self, db: AgentWorkflowDatabase) -> None:
        assert db.get_workflow("does-not-exist") is None

    def test_idempotent_persist_does_not_duplicate(
        self, db: AgentWorkflowDatabase
    ) -> None:
        wf = _build_minimal_workflow()
        db.persist_workflow(wf)
        db.persist_workflow(wf)  # Persist twice
        assert db.get_table_row_count("agent_workflows") == 1
        assert db.get_table_row_count("agent_interactions") == 1
        assert db.get_table_row_count("agent_tool_calls") == 1

    def test_persist_workflow_with_multiple_turns(
        self, db: AgentWorkflowDatabase
    ) -> None:
        tracker = AgentInteractionTracker("wf-multi", "claude", "Multi-turn")
        for turn in (1, 2, 3):
            tracker.start_interaction(turn)
            tracker.add_message("user", f"turn {turn}")
            cid = tracker.add_tool_call("calc", {"expr": str(turn)})
            tracker.add_tool_result(cid, success=True, output=str(turn))
            tracker.end_interaction(success=True)
        wf = tracker.end_workflow(success=True)

        db.persist_workflow(wf)
        loaded = db.get_workflow("wf-multi")
        assert loaded is not None
        assert len(loaded["interactions"]) == 3
        assert [i["turn_number"] for i in loaded["interactions"]] == [1, 2, 3]
        assert db.get_table_row_count("agent_tool_calls") == 3
        assert db.get_table_row_count("agent_tool_results") == 3

    def test_persist_workflow_with_failed_tool_call(
        self, db: AgentWorkflowDatabase
    ) -> None:
        tracker = AgentInteractionTracker("wf-fail", "claude", "Failure case")
        tracker.start_interaction(1)
        cid = tracker.add_tool_call("api", {"url": "/broken"})
        tracker.add_tool_result(
            cid, success=False, output="", error="500 Internal Server Error"
        )
        tracker.end_interaction(success=False, error="API call failed")
        wf = tracker.end_workflow(success=False, error="Workflow aborted")

        db.persist_workflow(wf)
        loaded = db.get_workflow("wf-fail")
        assert loaded is not None
        assert loaded["status"] == "failed"
        assert loaded["error"] == "Workflow aborted"
        assert loaded["interactions"][0]["success"] is False
        assert loaded["interactions"][0]["tool_results"][0]["success"] is False
        assert loaded["interactions"][0]["tool_results"][0]["error"] == (
            "500 Internal Server Error"
        )

    def test_messages_round_trip_via_json_column(
        self, db: AgentWorkflowDatabase
    ) -> None:
        wf = _build_minimal_workflow()
        db.persist_workflow(wf)
        loaded = db.get_workflow("wf-1")
        assert loaded is not None
        messages = loaded["interactions"][0]["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert [m["content"] for m in messages] == ["do thing", "ok"]

    def test_state_snapshots_round_trip(self, db: AgentWorkflowDatabase) -> None:
        wf = _build_minimal_workflow()
        db.persist_workflow(wf)
        loaded = db.get_workflow("wf-1")
        assert loaded is not None
        assert loaded["interactions"][0]["state_before"] == {"branch": "main"}
        assert loaded["interactions"][0]["state_after"] == {
            "branch": "main",
            "dirty": False,
        }


class TestConstruction:
    def test_url_with_sqlite_prefix(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'x.db'}"
        db = AgentWorkflowDatabase(database_url=url)
        wf = _build_minimal_workflow("wf-url")
        db.persist_workflow(wf)
        assert db.get_table_row_count("agent_workflows") == 1

    def test_no_path_no_env_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENT_WORKFLOW_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(Exception, match="DATABASE_URL"):
            AgentWorkflowDatabase()

    def test_env_var_picked_up(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(
            "AGENT_WORKFLOW_DATABASE_URL", f"sqlite:///{tmp_path / 'env.db'}"
        )
        db = AgentWorkflowDatabase()
        assert db.get_table_row_count("agent_workflows") == 0
