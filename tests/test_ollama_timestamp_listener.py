"""Tests for OllamaTimestampListener."""

import json
import os
import tempfile
from unittest.mock import patch

from rfc.ollama_timestamp_listener import OllamaTimestampListener


class TestOllamaTimestampListener:
    """Unit tests for the Ollama timestamp listener."""

    def test_robot_listener_api_version(self):
        listener = OllamaTimestampListener()
        assert listener.ROBOT_LISTENER_API_VERSION == 2

    def test_initial_state(self):
        listener = OllamaTimestampListener()
        assert listener._chats == []
        assert listener._current_keyword is None

    def test_start_keyword_tracks_ask_llm(self):
        listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {"args": ["What is 2+2?"]})
        assert listener._current_keyword is not None
        assert listener._current_keyword["keyword"] == "Ask LLM"
        assert listener._current_keyword["prompt"] == "What is 2+2?"
        assert "start_time" in listener._current_keyword

    def test_start_keyword_ignores_non_ollama(self):
        listener = OllamaTimestampListener()
        listener.start_keyword("Should Be Equal", {"args": ["a", "b"]})
        assert listener._current_keyword is None

    def test_end_keyword_records_chat(self):
        listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {"args": ["What is 2+2?"]})
        listener.end_keyword("Ask LLM", {"args": ["What is 2+2?"]})
        assert len(listener._chats) == 1
        chat = listener._chats[0]
        assert chat["keyword"] == "Ask LLM"
        assert chat["prompt"] == "What is 2+2?"
        assert "start_time" in chat
        assert "end_time" in chat
        assert "duration_seconds" in chat
        assert chat["duration_seconds"] >= 0

    def test_end_keyword_ignores_untracked(self):
        listener = OllamaTimestampListener()
        listener.end_keyword("Should Be Equal", {"args": ["a", "b"]})
        assert len(listener._chats) == 0

    def test_multiple_chats_recorded(self):
        listener = OllamaTimestampListener()
        for i in range(3):
            listener.start_keyword("Ask LLM", {"args": [f"Question {i}"]})
            listener.end_keyword("Ask LLM", {"args": [f"Question {i}"]})
        assert len(listener._chats) == 3
        assert listener._chats[0]["prompt"] == "Question 0"
        assert listener._chats[2]["prompt"] == "Question 2"

    def test_end_suite_saves_json(self):
        listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        listener.end_keyword("Ask LLM", {"args": ["Hello"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("My Suite", {"totaltests": 1})

            output_file = os.path.join(tmpdir, "ollama_timestamps.json")
            assert os.path.exists(output_file)

            with open(output_file) as f:
                data = json.load(f)

            assert data["suite"] == "My Suite"
            assert data["total_chats"] == 1
            assert len(data["chats"]) == 1
            assert data["chats"][0]["prompt"] == "Hello"

    def test_end_suite_no_chats_no_file(self):
        listener = OllamaTimestampListener()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("My Suite", {"totaltests": 0})

            output_file = os.path.join(tmpdir, "ollama_timestamps.json")
            assert not os.path.exists(output_file)

    def test_tracks_set_llm_model(self):
        listener = OllamaTimestampListener()
        listener.start_keyword("Set LLM Model", {"args": ["mistral"]})
        assert listener._current_keyword is not None
        assert listener._current_keyword["keyword"] == "Set LLM Model"

    def test_tracks_wait_for_llm(self):
        listener = OllamaTimestampListener()
        listener.start_keyword("Wait For LLM", {"args": []})
        assert listener._current_keyword is not None
        assert listener._current_keyword["keyword"] == "Wait For LLM"

    def test_suite_depth_only_saves_at_top_level(self):
        listener = OllamaTimestampListener()
        listener.start_suite("Top", {})
        listener.start_suite("Nested", {})
        listener.start_keyword("Ask LLM", {"args": ["test"]})
        listener.end_keyword("Ask LLM", {"args": ["test"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                # End nested suite — should not save
                listener.end_suite("Nested", {"totaltests": 1})
                output_file = os.path.join(tmpdir, "ollama_timestamps.json")
                assert not os.path.exists(output_file)

                # End top-level suite — should save
                listener.end_suite("Top", {"totaltests": 1})
                assert os.path.exists(output_file)

    def test_start_keyword_with_empty_args(self):
        listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {"args": []})
        assert listener._current_keyword is not None
        assert listener._current_keyword["prompt"] == ""

    def test_start_keyword_with_no_args_key(self):
        listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {})
        assert listener._current_keyword is not None
        assert listener._current_keyword["prompt"] == ""

    def test_end_keyword_mismatched_name_ignored(self):
        """end_keyword for a different tracked keyword should not consume _current_keyword."""
        listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        # End with a different tracked keyword name
        listener.end_keyword("Wait For LLM", {"args": []})
        # _current_keyword should still be set (not consumed)
        assert listener._current_keyword is not None
        assert listener._current_keyword["keyword"] == "Ask LLM"
        assert len(listener._chats) == 0

    def test_end_keyword_matching_name_consumed(self):
        listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        listener.end_keyword("Ask LLM", {"args": ["Hello"]})
        assert listener._current_keyword is None
        assert len(listener._chats) == 1

    def test_all_tracked_keywords(self):
        """Verify all documented tracked keywords are accepted."""
        tracked = [
            "Ask LLM",
            "Set LLM Endpoint",
            "Set LLM Model",
            "Set LLM Parameters",
            "Wait For LLM",
            "Get Running Models",
            "LLM Is Busy",
        ]
        for kw in tracked:
            listener = OllamaTimestampListener()
            listener.start_keyword(kw, {"args": ["test"]})
            assert listener._current_keyword is not None, f"{kw} not tracked"
            assert listener._current_keyword["keyword"] == kw

    def test_duration_is_non_negative(self):
        listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {"args": ["test"]})
        listener.end_keyword("Ask LLM", {"args": ["test"]})
        assert listener._chats[0]["duration_seconds"] >= 0

    def test_timestamps_are_iso_format(self):
        listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {"args": ["test"]})
        listener.end_keyword("Ask LLM", {"args": ["test"]})
        chat = listener._chats[0]
        assert chat["start_time"].endswith("Z")
        assert chat["end_time"].endswith("Z")

    def test_json_output_structure(self):
        listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        listener.end_keyword("Ask LLM", {"args": ["Hello"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("My Suite", {"totaltests": 1})

            output_file = os.path.join(tmpdir, "ollama_timestamps.json")
            with open(output_file) as f:
                data = json.load(f)

            assert "suite" in data
            assert "total_chats" in data
            assert "chats" in data
            assert isinstance(data["chats"], list)
            chat = data["chats"][0]
            assert set(chat.keys()) == {
                "keyword",
                "prompt",
                "start_time",
                "end_time",
                "duration_seconds",
                "model",
                "endpoint",
            }


class TestOllamaAuditLog:
    """Tests for the auditable ollama_audit.log file."""

    def test_initial_model_from_env(self):
        """Listener picks up DEFAULT_MODEL from environment."""
        with patch.dict(os.environ, {"DEFAULT_MODEL": "gemma2"}):
            listener = OllamaTimestampListener()
        assert listener._model == "gemma2"

    def test_initial_model_default(self):
        """Falls back to 'unknown' when DEFAULT_MODEL is unset."""
        with patch.dict(os.environ, {}, clear=True):
            listener = OllamaTimestampListener()
        assert listener._model == "unknown"

    def test_initial_endpoint_from_env(self):
        """Listener picks up OLLAMA_ENDPOINT from environment."""
        with patch.dict(
            os.environ, {"OLLAMA_ENDPOINT": "http://ai1:11434"}
        ):
            listener = OllamaTimestampListener()
        assert listener._endpoint == "http://ai1:11434"

    def test_initial_endpoint_default(self):
        """Falls back to 'http://localhost:11434' when unset."""
        with patch.dict(os.environ, {}, clear=True):
            listener = OllamaTimestampListener()
        assert listener._endpoint == "http://localhost:11434"

    def test_set_llm_model_updates_model(self):
        """Set LLM Model keyword updates the tracked model."""
        listener = OllamaTimestampListener()
        listener.start_keyword("Set LLM Model", {"args": ["mistral"]})
        listener.end_keyword("Set LLM Model", {"args": ["mistral"]})
        assert listener._model == "mistral"

    def test_set_llm_endpoint_updates_endpoint(self):
        """Set LLM Endpoint keyword updates the tracked endpoint."""
        listener = OllamaTimestampListener()
        listener.start_keyword(
            "Set LLM Endpoint", {"args": ["http://gpu-box:11434"]}
        )
        listener.end_keyword(
            "Set LLM Endpoint", {"args": ["http://gpu-box:11434"]}
        )
        assert listener._endpoint == "http://gpu-box:11434"

    def test_chat_records_model_and_endpoint(self):
        """Each completed chat entry includes model and endpoint."""
        with patch.dict(
            os.environ,
            {
                "DEFAULT_MODEL": "llama3",
                "OLLAMA_ENDPOINT": "http://localhost:11434",
            },
        ):
            listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {"args": ["Hi"]})
        listener.end_keyword("Ask LLM", {"args": ["Hi"]})
        chat = listener._chats[0]
        assert chat["model"] == "llama3"
        assert chat["endpoint"] == "http://localhost:11434"

    def test_audit_log_file_created(self):
        """end_suite writes ollama_audit.log alongside the JSON."""
        listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        listener.end_keyword("Ask LLM", {"args": ["Hello"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("My Suite", {"totaltests": 1})

            audit_file = os.path.join(tmpdir, "ollama_audit.log")
            assert os.path.exists(audit_file)

    def test_audit_log_not_created_when_no_chats(self):
        """No audit log when there are no Ollama interactions."""
        listener = OllamaTimestampListener()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("My Suite", {"totaltests": 0})

            audit_file = os.path.join(tmpdir, "ollama_audit.log")
            assert not os.path.exists(audit_file)

    def test_audit_log_header(self):
        """Audit log starts with a comment header."""
        listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        listener.end_keyword("Ask LLM", {"args": ["Hello"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("My Suite", {"totaltests": 1})

            audit_file = os.path.join(tmpdir, "ollama_audit.log")
            with open(audit_file) as f:
                lines = f.readlines()

            assert lines[0].startswith("# ollama_audit.log")
            assert "My Suite" in lines[1]

    def test_audit_log_tab_separated_entries(self):
        """Each entry is tab-separated with expected fields."""
        with patch.dict(
            os.environ,
            {
                "DEFAULT_MODEL": "llama3",
                "OLLAMA_ENDPOINT": "http://localhost:11434",
            },
        ):
            listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {"args": ["What is 2+2?"]})
        listener.end_keyword("Ask LLM", {"args": ["What is 2+2?"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("Suite", {"totaltests": 1})

            audit_file = os.path.join(tmpdir, "ollama_audit.log")
            with open(audit_file) as f:
                lines = [line for line in f.readlines() if not line.startswith("#")]

            assert len(lines) == 1
            parts = lines[0].strip().split("\t")
            # TIMESTAMP  ENDPOINT  MODEL  KEYWORD  DURATION_S  PROMPT
            assert len(parts) == 6
            assert parts[0].endswith("Z")  # ISO timestamp
            assert parts[1] == "http://localhost:11434"
            assert parts[2] == "llama3"
            assert parts[3] == "Ask LLM"
            assert float(parts[4]) >= 0  # duration
            assert parts[5] == "What is 2+2?"

    def test_audit_log_multiple_entries(self):
        """Multiple interactions produce multiple log lines."""
        listener = OllamaTimestampListener()
        for i in range(3):
            listener.start_keyword("Ask LLM", {"args": [f"Q{i}"]})
            listener.end_keyword("Ask LLM", {"args": [f"Q{i}"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("Suite", {"totaltests": 3})

            audit_file = os.path.join(tmpdir, "ollama_audit.log")
            with open(audit_file) as f:
                data_lines = [line for line in f.readlines() if not line.startswith("#")]

            assert len(data_lines) == 3

    def test_audit_log_reflects_model_change(self):
        """Log entries reflect model changes mid-session."""
        listener = OllamaTimestampListener()
        listener.start_keyword("Set LLM Model", {"args": ["llama3"]})
        listener.end_keyword("Set LLM Model", {"args": ["llama3"]})

        listener.start_keyword("Ask LLM", {"args": ["Q1"]})
        listener.end_keyword("Ask LLM", {"args": ["Q1"]})

        listener.start_keyword("Set LLM Model", {"args": ["mistral"]})
        listener.end_keyword("Set LLM Model", {"args": ["mistral"]})

        listener.start_keyword("Ask LLM", {"args": ["Q2"]})
        listener.end_keyword("Ask LLM", {"args": ["Q2"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("Suite", {"totaltests": 2})

            audit_file = os.path.join(tmpdir, "ollama_audit.log")
            with open(audit_file) as f:
                data_lines = [line for line in f.readlines() if not line.startswith("#")]

        # 4 entries: Set LLM Model, Ask LLM, Set LLM Model, Ask LLM
        assert len(data_lines) == 4
        # First Ask LLM should use llama3
        ask1_parts = data_lines[1].strip().split("\t")
        assert ask1_parts[2] == "llama3"
        # Second Ask LLM should use mistral
        ask2_parts = data_lines[3].strip().split("\t")
        assert ask2_parts[2] == "mistral"

    def test_json_output_includes_model_and_endpoint(self):
        """JSON output also includes model and endpoint per chat entry."""
        with patch.dict(os.environ, {"DEFAULT_MODEL": "phi3"}):
            listener = OllamaTimestampListener()
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        listener.end_keyword("Ask LLM", {"args": ["Hello"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("Suite", {"totaltests": 1})

            with open(os.path.join(tmpdir, "ollama_timestamps.json")) as f:
                data = json.load(f)

            chat = data["chats"][0]
            assert chat["model"] == "phi3"
            assert "endpoint" in chat
