"""Tests for OllamaTimestampListener (Listener API v3)."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

from rfc.ollama_timestamp_listener import OllamaTimestampListener


def _mock_suite_data(name: str = "Suite") -> MagicMock:
    """Create a mock running.TestSuite (data) object."""
    data = MagicMock()
    data.name = name
    return data


def _mock_suite_result() -> MagicMock:
    """Create a mock result.TestSuite (result) object."""
    result = MagicMock()
    result.metadata = {}
    return result


def _mock_keyword_data(name: str, args: list | None = None) -> MagicMock:
    """Create a mock running.Keyword (data) object."""
    data = MagicMock()
    data.name = name
    data.args = tuple(args) if args is not None else ()
    return data


def _mock_keyword_result() -> MagicMock:
    """Create a mock result.Keyword (result) object."""
    return MagicMock()


class TestOllamaTimestampListener:
    """Unit tests for the Ollama timestamp listener."""

    def test_robot_listener_api_version(self) -> None:
        listener = OllamaTimestampListener()
        assert listener.ROBOT_LISTENER_API_VERSION == 3

    def test_initial_state(self) -> None:
        listener = OllamaTimestampListener()
        assert listener._chats == []
        assert listener._current_keyword is None

    def test_start_keyword_tracks_ask_llm(self) -> None:
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["What is 2+2?"]),
            _mock_keyword_result(),
        )
        assert listener._current_keyword is not None
        assert listener._current_keyword["keyword"] == "Ask LLM"
        assert listener._current_keyword["prompt"] == "What is 2+2?"
        assert "start_time" in listener._current_keyword

    def test_start_keyword_ignores_non_ollama(self) -> None:
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Should Be Equal", ["a", "b"]),
            _mock_keyword_result(),
        )
        assert listener._current_keyword is None

    def test_end_keyword_records_chat(self) -> None:
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["What is 2+2?"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )
        assert len(listener._chats) == 1
        chat = listener._chats[0]
        assert chat["keyword"] == "Ask LLM"
        assert chat["prompt"] == "What is 2+2?"
        assert "start_time" in chat
        assert "end_time" in chat
        assert "duration_seconds" in chat
        assert chat["duration_seconds"] >= 0

    def test_end_keyword_ignores_untracked(self) -> None:
        listener = OllamaTimestampListener()
        listener.end_keyword(
            _mock_keyword_data("Should Be Equal"),
            _mock_keyword_result(),
        )
        assert len(listener._chats) == 0

    def test_multiple_chats_recorded(self) -> None:
        listener = OllamaTimestampListener()
        for i in range(3):
            listener.start_keyword(
                _mock_keyword_data("Ask LLM", [f"Question {i}"]),
                _mock_keyword_result(),
            )
            listener.end_keyword(
                _mock_keyword_data("Ask LLM"),
                _mock_keyword_result(),
            )
        assert len(listener._chats) == 3
        assert listener._chats[0]["prompt"] == "Question 0"
        assert listener._chats[2]["prompt"] == "Question 2"

    def test_end_suite_saves_json(self) -> None:
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["Hello"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(
                    _mock_suite_data("My Suite"), _mock_suite_result()
                )

            output_file = os.path.join(tmpdir, "ollama_timestamps.json")
            assert os.path.exists(output_file)

            with open(output_file) as f:
                data = json.load(f)

            assert data["suite"] == "My Suite"
            assert data["total_chats"] == 1
            assert len(data["chats"]) == 1
            assert data["chats"][0]["prompt"] == "Hello"

    def test_end_suite_no_chats_no_file(self) -> None:
        listener = OllamaTimestampListener()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(
                    _mock_suite_data("My Suite"), _mock_suite_result()
                )

            output_file = os.path.join(tmpdir, "ollama_timestamps.json")
            assert not os.path.exists(output_file)

    def test_tracks_set_llm_model(self) -> None:
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Set LLM Model", ["mistral"]),
            _mock_keyword_result(),
        )
        assert listener._current_keyword is not None
        assert listener._current_keyword["keyword"] == "Set LLM Model"

    def test_tracks_wait_for_llm(self) -> None:
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Wait For LLM"),
            _mock_keyword_result(),
        )
        assert listener._current_keyword is not None
        assert listener._current_keyword["keyword"] == "Wait For LLM"

    def test_suite_depth_only_saves_at_top_level(self) -> None:
        listener = OllamaTimestampListener()
        listener.start_suite(_mock_suite_data("Top"), _mock_suite_result())
        listener.start_suite(_mock_suite_data("Nested"), _mock_suite_result())
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["test"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                # End nested suite — should not save
                listener.end_suite(
                    _mock_suite_data("Nested"), _mock_suite_result()
                )
                output_file = os.path.join(tmpdir, "ollama_timestamps.json")
                assert not os.path.exists(output_file)

                # End top-level suite — should save
                listener.end_suite(
                    _mock_suite_data("Top"), _mock_suite_result()
                )
                assert os.path.exists(output_file)

    def test_start_keyword_with_empty_args(self) -> None:
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", []),
            _mock_keyword_result(),
        )
        assert listener._current_keyword is not None
        assert listener._current_keyword["prompt"] == ""

    def test_start_keyword_with_no_args(self) -> None:
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )
        assert listener._current_keyword is not None
        assert listener._current_keyword["prompt"] == ""

    def test_end_keyword_mismatched_name_ignored(self) -> None:
        """end_keyword for a different tracked keyword should not consume _current_keyword."""
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["Hello"]),
            _mock_keyword_result(),
        )
        # End with a different tracked keyword name
        listener.end_keyword(
            _mock_keyword_data("Wait For LLM"),
            _mock_keyword_result(),
        )
        # _current_keyword should still be set (not consumed)
        assert listener._current_keyword is not None
        assert listener._current_keyword["keyword"] == "Ask LLM"
        assert len(listener._chats) == 0

    def test_end_keyword_matching_name_consumed(self) -> None:
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["Hello"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )
        assert listener._current_keyword is None
        assert len(listener._chats) == 1

    def test_all_tracked_keywords(self) -> None:
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
            listener.start_keyword(
                _mock_keyword_data(kw, ["test"]),
                _mock_keyword_result(),
            )
            assert listener._current_keyword is not None, f"{kw} not tracked"
            assert listener._current_keyword["keyword"] == kw

    def test_duration_is_non_negative(self) -> None:
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["test"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )
        assert listener._chats[0]["duration_seconds"] >= 0

    def test_timestamps_are_iso_format(self) -> None:
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["test"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )
        chat = listener._chats[0]
        assert chat["start_time"].endswith("Z")
        assert chat["end_time"].endswith("Z")

    def test_json_output_structure(self) -> None:
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["Hello"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(
                    _mock_suite_data("My Suite"), _mock_suite_result()
                )

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

    def test_initial_model_from_env(self) -> None:
        """Listener picks up DEFAULT_MODEL from environment."""
        with patch.dict(os.environ, {"DEFAULT_MODEL": "gemma2"}):
            listener = OllamaTimestampListener()
        assert listener._model == "gemma2"

    def test_initial_model_default(self) -> None:
        """Falls back to 'unknown' when DEFAULT_MODEL is unset."""
        with patch.dict(os.environ, {}, clear=True):
            listener = OllamaTimestampListener()
        assert listener._model == "unknown"

    def test_initial_endpoint_from_env(self) -> None:
        """Listener picks up OLLAMA_ENDPOINT from environment."""
        with patch.dict(os.environ, {"OLLAMA_ENDPOINT": "http://ai1:11434"}):
            listener = OllamaTimestampListener()
        assert listener._endpoint == "http://ai1:11434"

    def test_initial_endpoint_default(self) -> None:
        """Falls back to 'http://localhost:11434' when unset."""
        with patch.dict(os.environ, {}, clear=True):
            listener = OllamaTimestampListener()
        assert listener._endpoint == "http://localhost:11434"

    def test_set_llm_model_updates_model(self) -> None:
        """Set LLM Model keyword updates the tracked model."""
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Set LLM Model", ["mistral"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Set LLM Model"),
            _mock_keyword_result(),
        )
        assert listener._model == "mistral"

    def test_set_llm_endpoint_updates_endpoint(self) -> None:
        """Set LLM Endpoint keyword updates the tracked endpoint."""
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Set LLM Endpoint", ["http://gpu-box:11434"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Set LLM Endpoint"),
            _mock_keyword_result(),
        )
        assert listener._endpoint == "http://gpu-box:11434"

    def test_chat_records_model_and_endpoint(self) -> None:
        """Each completed chat entry includes model and endpoint."""
        with patch.dict(
            os.environ,
            {
                "DEFAULT_MODEL": "llama3",
                "OLLAMA_ENDPOINT": "http://localhost:11434",
            },
        ):
            listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["Hi"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )
        chat = listener._chats[0]
        assert chat["model"] == "llama3"
        assert chat["endpoint"] == "http://localhost:11434"

    def test_audit_log_file_created(self) -> None:
        """end_suite writes ollama_audit.log alongside the JSON."""
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["Hello"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(
                    _mock_suite_data("My Suite"), _mock_suite_result()
                )

            audit_file = os.path.join(tmpdir, "ollama_audit.log")
            assert os.path.exists(audit_file)

    def test_audit_log_not_created_when_no_chats(self) -> None:
        """No audit log when there are no Ollama interactions."""
        listener = OllamaTimestampListener()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(
                    _mock_suite_data("My Suite"), _mock_suite_result()
                )

            audit_file = os.path.join(tmpdir, "ollama_audit.log")
            assert not os.path.exists(audit_file)

    def test_audit_log_header(self) -> None:
        """Audit log starts with a comment header."""
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["Hello"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(
                    _mock_suite_data("My Suite"), _mock_suite_result()
                )

            audit_file = os.path.join(tmpdir, "ollama_audit.log")
            with open(audit_file) as f:
                lines = f.readlines()

            assert lines[0].startswith("# ollama_audit.log")
            assert "My Suite" in lines[1]

    def test_audit_log_tab_separated_entries(self) -> None:
        """Each entry is tab-separated with expected fields."""
        with patch.dict(
            os.environ,
            {
                "DEFAULT_MODEL": "llama3",
                "OLLAMA_ENDPOINT": "http://localhost:11434",
            },
        ):
            listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["What is 2+2?"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(
                    _mock_suite_data("Suite"), _mock_suite_result()
                )

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

    def test_audit_log_multiple_entries(self) -> None:
        """Multiple interactions produce multiple log lines."""
        listener = OllamaTimestampListener()
        for i in range(3):
            listener.start_keyword(
                _mock_keyword_data("Ask LLM", [f"Q{i}"]),
                _mock_keyword_result(),
            )
            listener.end_keyword(
                _mock_keyword_data("Ask LLM"),
                _mock_keyword_result(),
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(
                    _mock_suite_data("Suite"), _mock_suite_result()
                )

            audit_file = os.path.join(tmpdir, "ollama_audit.log")
            with open(audit_file) as f:
                data_lines = [
                    line for line in f.readlines() if not line.startswith("#")
                ]

            assert len(data_lines) == 3

    def test_audit_log_reflects_model_change(self) -> None:
        """Log entries reflect model changes mid-session."""
        listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Set LLM Model", ["llama3"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Set LLM Model"),
            _mock_keyword_result(),
        )

        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["Q1"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )

        listener.start_keyword(
            _mock_keyword_data("Set LLM Model", ["mistral"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Set LLM Model"),
            _mock_keyword_result(),
        )

        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["Q2"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(
                    _mock_suite_data("Suite"), _mock_suite_result()
                )

            audit_file = os.path.join(tmpdir, "ollama_audit.log")
            with open(audit_file) as f:
                data_lines = [
                    line for line in f.readlines() if not line.startswith("#")
                ]

        # 4 entries: Set LLM Model, Ask LLM, Set LLM Model, Ask LLM
        assert len(data_lines) == 4
        # First Ask LLM should use llama3
        ask1_parts = data_lines[1].strip().split("\t")
        assert ask1_parts[2] == "llama3"
        # Second Ask LLM should use mistral
        ask2_parts = data_lines[3].strip().split("\t")
        assert ask2_parts[2] == "mistral"

    def test_json_output_includes_model_and_endpoint(self) -> None:
        """JSON output also includes model and endpoint per chat entry."""
        with patch.dict(os.environ, {"DEFAULT_MODEL": "phi3"}):
            listener = OllamaTimestampListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["Hello"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(
                    _mock_suite_data("Suite"), _mock_suite_result()
                )

            with open(os.path.join(tmpdir, "ollama_timestamps.json")) as f:
                data = json.load(f)

            chat = data["chats"][0]
            assert chat["model"] == "phi3"
            assert "endpoint" in chat
