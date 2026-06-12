"""Tests for the dialog recording stack (#354).

Covers the dialog_recordings/dialog_turns schema in HarnessDatabase,
the DialogRecorder keyword library, the RFC_DATA emission from
``Ask LLM`` when a recording bracket is active, and the DialogListener
that persists captured turns.
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from rfc.dialog_listener import DialogListener
from rfc.dialog_recorder import RECORDING_ENV_VAR, DialogRecorder
from rfc.harness_db import HarnessDatabase
from rfc.harness_models import AgenticHarness, DialogRecording, DialogTurn
from rfc.keywords import LLMKeywords

T0 = "2026-06-11T00:00:00Z"
T1 = "2026-06-11T00:01:00Z"


@pytest.fixture()
def db(tmp_path):
    return HarnessDatabase(database_url=f"sqlite:///{tmp_path / 'h.db'}")


def _recording(**overrides) -> DialogRecording:
    base = dict(
        id="rec-1",
        source_type="live",
        started_at=T0,
        session_id="",
        tool_name="claude-code",
        model_id="llama3:latest",
    )
    base.update(overrides)
    return DialogRecording(**base)


def _turn(n: int, **overrides) -> DialogTurn:
    base = dict(
        recording_id="rec-1",
        turn_number=n,
        role="user" if n % 2 else "assistant",
        timestamp=T0,
        content=f"turn {n}",
    )
    base.update(overrides)
    return DialogTurn(**base)


class TestDialogRecordingCrud:
    def test_save_and_get_recording(self, db):
        db.save_recording(_recording())
        rec = db.get_recording("rec-1")
        assert rec is not None
        assert rec.source_type == "live"
        assert rec.tool_name == "claude-code"
        assert rec.session_id == ""

    def test_session_id_round_trips_when_harness_exists(self, db):
        db.save_harness(
            AgenticHarness(session_id="sess-1", tool_name="claude-code", started_at=T0)
        )
        db.save_recording(_recording(session_id="sess-1"))
        rec = db.get_recording("rec-1")
        assert rec is not None
        assert rec.session_id == "sess-1"

    def test_end_recording_sets_ended_at(self, db):
        db.save_recording(_recording())
        db.end_recording("rec-1", T1)
        rec = db.get_recording("rec-1")
        assert rec is not None
        assert rec.ended_at == T1

    def test_get_missing_recording_returns_none(self, db):
        assert db.get_recording("nope") is None


class TestDialogTurnCrud:
    def test_turns_round_trip_in_order(self, db):
        db.save_recording(_recording())
        db.save_turns([_turn(2), _turn(1), _turn(3)])
        turns = db.get_turns("rec-1")
        assert [t.turn_number for t in turns] == [1, 2, 3]
        assert turns[0].role == "user"
        assert turns[0].content == "turn 1"

    def test_token_and_latency_sentinels_round_trip(self, db):
        db.save_recording(_recording())
        db.save_turns(
            [
                _turn(1, prompt_tokens=12, completion_tokens=34, latency_ms=56.7),
                _turn(2),  # sentinels: -1 / -1 / -1.0
            ]
        )
        turns = db.get_turns("rec-1")
        assert turns[0].prompt_tokens == 12
        assert turns[0].completion_tokens == 34
        assert turns[0].latency_ms == 56.7
        assert turns[1].prompt_tokens == -1
        assert turns[1].latency_ms == -1.0

    def test_tool_call_payloads_round_trip(self, db):
        db.save_recording(_recording())
        db.save_turns(
            [_turn(1, role="tool", tool_calls_json='[{"name": "x"}]')]
        )
        assert db.get_turns("rec-1")[0].tool_calls_json == '[{"name": "x"}]'


def _init_repo(root) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


class TestDialogRecorderKeywords:
    @pytest.fixture()
    def recorder(self, tmp_path, monkeypatch):
        _init_repo(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(RECORDING_ENV_VAR, raising=False)
        return DialogRecorder()

    @patch("rfc.dialog_recorder.emit_rfc_data")
    def test_start_sets_env_and_emits_payload(self, mock_emit, recorder, monkeypatch):
        recording_id = recorder.start_dialog_recording(
            source_type="live", agent_id="claude-code"
        )
        import os

        assert os.environ[RECORDING_ENV_VAR] == recording_id
        key, payload = mock_emit.call_args[0]
        assert key == "dialog_recording"
        data = json.loads(payload)
        assert data["id"] == recording_id
        assert data["source_type"] == "live"
        assert data["tool_name"] == "claude-code"
        assert data["session_id"] == ""
        assert data["started_at"]

    @patch("rfc.dialog_recorder.emit_rfc_data")
    def test_start_picks_up_active_harness_session(
        self, mock_emit, recorder, tmp_path
    ):
        sidecar = tmp_path / ".git" / "rfc-harness-session.json"
        sidecar.write_text(json.dumps({"session_id": "sess-9"}))
        recorder.start_dialog_recording(source_type="live", agent_id="claude-code")
        data = json.loads(mock_emit.call_args[0][1])
        assert data["session_id"] == "sess-9"

    @patch("rfc.dialog_recorder.emit_rfc_data")
    def test_end_clears_env_and_emits_end(self, mock_emit, recorder):
        import os

        recording_id = recorder.start_dialog_recording(
            source_type="live", agent_id="claude-code"
        )
        recorder.end_dialog_recording()
        assert RECORDING_ENV_VAR not in os.environ
        key, payload = mock_emit.call_args[0]
        assert key == "dialog_recording_end"
        data = json.loads(payload)
        assert data["recording_id"] == recording_id
        assert data["ended_at"]

    def test_end_without_active_recording_raises(self, recorder):
        with pytest.raises(RuntimeError):
            recorder.end_dialog_recording()


class TestAskLlmEmission:
    @patch("rfc.keywords.emit_rfc_data")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_emits_turns_when_bracket_active(
        self, MockGrader, mock_create, mock_emit, monkeypatch
    ):
        monkeypatch.setenv(RECORDING_ENV_VAR, "rec-7")
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.num_ctx = None
        kw.client.max_tokens = 256
        kw.client.last_metrics = {
            "prompt_eval_count": 10,
            "eval_count": 5,
            "total_duration_ns": 2_000_000_000,
        }
        kw.ask_llm("What is 6 * 7?")
        dialog_payloads = [
            json.loads(c.args[1])
            for c in mock_emit.call_args_list
            if c.args[0] == "dialog_turn"
        ]
        assert [p["role"] for p in dialog_payloads] == ["user", "assistant"]
        user, assistant = dialog_payloads
        assert user["recording_id"] == "rec-7"
        assert user["content"] == "What is 6 * 7?"
        assert assistant["content"] == "42"
        assert assistant["prompt_tokens"] == 10
        assert assistant["completion_tokens"] == 5
        assert assistant["latency_ms"] == 2000.0

    @patch("rfc.keywords.emit_rfc_data")
    @patch("rfc.keywords.create_provider")
    @patch("rfc.keywords.Grader")
    def test_ask_llm_emits_no_turns_without_bracket(
        self, MockGrader, mock_create, mock_emit, monkeypatch
    ):
        monkeypatch.delenv(RECORDING_ENV_VAR, raising=False)
        kw = LLMKeywords()
        kw.client.generate.return_value = "42"
        kw.client.last_metrics = None
        kw.ask_llm("What is 6 * 7?")
        assert not [c for c in mock_emit.call_args_list if c.args[0] == "dialog_turn"]


class _FakeMessage:
    def __init__(self, message: str) -> None:
        self.message = message


def _feed(listener: DialogListener, key: str, payload: dict) -> None:
    listener.log_message(_FakeMessage(f"RFC_DATA:{key}:{json.dumps(payload)}"))


class TestDialogListener:
    def _run_test_cycle(self, listener: DialogListener, events) -> None:
        listener.start_test(MagicMock(), MagicMock())
        for key, payload in events:
            _feed(listener, key, payload)
        listener.end_test(MagicMock(), MagicMock())

    def test_persists_recording_and_numbered_turns(self, tmp_path):
        url = f"sqlite:///{tmp_path / 'h.db'}"
        listener = DialogListener(database_url=url)
        self._run_test_cycle(
            listener,
            [
                (
                    "dialog_recording",
                    {
                        "id": "rec-1",
                        "session_id": "",
                        "source_type": "live",
                        "tool_name": "claude-code",
                        "model_id": "llama3",
                        "started_at": T0,
                    },
                ),
                ("dialog_turn", {"recording_id": "rec-1", "role": "user", "content": "q", "timestamp": T0}),
                ("dialog_turn", {"recording_id": "rec-1", "role": "assistant", "content": "a", "timestamp": T1}),
                ("dialog_recording_end", {"recording_id": "rec-1", "ended_at": T1}),
            ],
        )
        db = HarnessDatabase(database_url=url)
        rec = db.get_recording("rec-1")
        assert rec is not None
        assert rec.ended_at == T1
        turns = db.get_turns("rec-1")
        assert [(t.turn_number, t.role) for t in turns] == [(1, "user"), (2, "assistant")]

    def test_turn_numbering_continues_across_tests(self, tmp_path):
        url = f"sqlite:///{tmp_path / 'h.db'}"
        listener = DialogListener(database_url=url)
        self._run_test_cycle(
            listener,
            [
                (
                    "dialog_recording",
                    {"id": "rec-1", "session_id": "", "source_type": "live", "tool_name": "t", "model_id": "", "started_at": T0},
                ),
                ("dialog_turn", {"recording_id": "rec-1", "role": "user", "content": "q1", "timestamp": T0}),
            ],
        )
        self._run_test_cycle(
            listener,
            [("dialog_turn", {"recording_id": "rec-1", "role": "assistant", "content": "a1", "timestamp": T1})],
        )
        db = HarnessDatabase(database_url=url)
        assert [t.turn_number for t in db.get_turns("rec-1")] == [1, 2]

    def test_no_database_url_skips_quietly(self, monkeypatch):
        monkeypatch.delenv("DIALOG_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        listener = DialogListener()
        self._run_test_cycle(
            listener,
            [("dialog_turn", {"recording_id": "rec-1", "role": "user", "content": "q", "timestamp": T0})],
        )
        assert listener.persisted_turn_count == 0

    def test_malformed_payload_is_skipped(self, tmp_path):
        url = f"sqlite:///{tmp_path / 'h.db'}"
        listener = DialogListener(database_url=url)
        listener.start_test(MagicMock(), MagicMock())
        listener.log_message(_FakeMessage("RFC_DATA:dialog_turn:{not json"))
        listener.end_test(MagicMock(), MagicMock())
        assert listener.persisted_turn_count == 0
