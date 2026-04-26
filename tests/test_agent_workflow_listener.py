"""Tests for src/rfc/agent_workflow_listener.py."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rfc.agent_interaction_tracker import AgentInteractionTracker
from rfc.agent_workflow_db import AgentWorkflowDatabase, workflow_to_dict
from rfc.agent_workflow_listener import (
    AGENT_WORKFLOW_DATA_KEY,
    AgentWorkflowListener,
    workflow_from_dict,
)


def _build_workflow(workflow_id: str = "wf-list") -> dict:
    tracker = AgentInteractionTracker(workflow_id, "claude", "Listener test")
    tracker.start_interaction(1)
    tracker.add_message("user", "ping")
    tracker.add_message("assistant", "pong")
    cid = tracker.add_tool_call("echo", {"text": "ping"})
    tracker.add_tool_result(cid, success=True, output="ping")
    tracker.set_interaction_state(
        reasoning="echo", state_before={"a": 1}, state_after={"a": 2}
    )
    tracker.end_interaction(success=True)
    wf = tracker.end_workflow(success=True)
    return workflow_to_dict(wf)


class TestRoundTripDictConversion:
    def test_workflow_from_dict_round_trips_via_workflow_to_dict(self) -> None:
        original = _build_workflow("wf-round-trip")
        wf = workflow_from_dict(original)
        again = workflow_to_dict(wf)
        # Compare via JSON for a deep, ordering-stable check.
        assert json.dumps(again, sort_keys=True) == json.dumps(
            original, sort_keys=True
        )


class TestListenerPersist:
    def test_persists_emitted_workflow(self, tmp_path: Path) -> None:
        db_path = tmp_path / "agent.db"
        listener = AgentWorkflowListener(
            database_url=f"sqlite:///{db_path}"
        )
        listener.start_suite(SimpleNamespace(name="root"), SimpleNamespace())
        listener.start_test(SimpleNamespace(name="t1"), SimpleNamespace())

        payload = json.dumps(_build_workflow("wf-emit"))
        listener._current_test_data[AGENT_WORKFLOW_DATA_KEY] = payload

        listener.end_test(SimpleNamespace(name="t1"), SimpleNamespace())
        listener.end_suite(SimpleNamespace(name="root"), SimpleNamespace())

        assert listener.persisted_count == 1
        db = AgentWorkflowDatabase(database_url=f"sqlite:///{db_path}")
        loaded = db.get_workflow("wf-emit")
        assert loaded is not None
        assert loaded["agent_id"] == "claude"

    def test_no_payload_does_not_persist(self, tmp_path: Path) -> None:
        listener = AgentWorkflowListener(
            database_url=f"sqlite:///{tmp_path / 'a.db'}"
        )
        listener.start_test(SimpleNamespace(name="t1"), SimpleNamespace())
        listener.end_test(SimpleNamespace(name="t1"), SimpleNamespace())
        assert listener.persisted_count == 0

    def test_invalid_json_payload_logged_and_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        listener = AgentWorkflowListener(
            database_url=f"sqlite:///{tmp_path / 'a.db'}"
        )
        listener.start_test(SimpleNamespace(name="t1"), SimpleNamespace())
        listener._current_test_data[AGENT_WORKFLOW_DATA_KEY] = "{not valid json"
        with caplog.at_level("WARNING"):
            listener.end_test(SimpleNamespace(name="t1"), SimpleNamespace())
        assert listener.persisted_count == 0
        assert any("decode" in rec.message for rec in caplog.records)

    def test_missing_required_field_logged_and_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        listener = AgentWorkflowListener(
            database_url=f"sqlite:///{tmp_path / 'a.db'}"
        )
        listener.start_test(SimpleNamespace(name="t1"), SimpleNamespace())
        listener._current_test_data[AGENT_WORKFLOW_DATA_KEY] = json.dumps(
            {"workflow_id": "wf-bad"}  # missing agent_id, task, etc.
        )
        with caplog.at_level("WARNING"):
            listener.end_test(SimpleNamespace(name="t1"), SimpleNamespace())
        assert listener.persisted_count == 0
        assert any("Invalid agent workflow" in rec.message for rec in caplog.records)

    def test_no_database_url_skips_silently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENT_WORKFLOW_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        listener = AgentWorkflowListener()
        listener.start_test(SimpleNamespace(name="t1"), SimpleNamespace())
        listener._current_test_data[AGENT_WORKFLOW_DATA_KEY] = json.dumps(
            _build_workflow()
        )
        listener.end_test(SimpleNamespace(name="t1"), SimpleNamespace())
        assert listener.persisted_count == 0

    def test_constructor_arg_overrides_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "sqlite:///wrong.db")
        ctor_url = f"sqlite:///{tmp_path / 'right.db'}"
        listener = AgentWorkflowListener(database_url=ctor_url)
        assert listener._database_url == ctor_url


class TestEnvVarPriority:
    def test_agent_specific_var_takes_precedence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "AGENT_WORKFLOW_DATABASE_URL", f"sqlite:///{tmp_path / 'agent.db'}"
        )
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'main.db'}")
        listener = AgentWorkflowListener()
        assert "agent.db" in (listener._database_url or "")

    def test_falls_back_to_database_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENT_WORKFLOW_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'main.db'}")
        listener = AgentWorkflowListener()
        assert "main.db" in (listener._database_url or "")
