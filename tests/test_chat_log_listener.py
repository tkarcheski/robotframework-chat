"""Tests for ChatLogListener (Listener API v3)."""

import os
import tempfile
from unittest.mock import MagicMock, patch

from rfc.chat_log_listener import ChatLogListener


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


def _mock_message(text: str, level: str = "INFO") -> MagicMock:
    """Create a mock result.Message object."""
    msg = MagicMock()
    msg.message = text
    msg.level = level
    return msg


class TestChatLogListener:
    """Unit tests for the chat log listener."""

    def test_robot_listener_api_version(self) -> None:
        listener = ChatLogListener()
        assert listener.ROBOT_LISTENER_API_VERSION == 3

    def test_initial_state(self) -> None:
        listener = ChatLogListener()
        assert listener._entries == []
        assert listener._in_tracked_keyword is None

    def test_default_model_from_env(self) -> None:
        with patch.dict(os.environ, {"DEFAULT_MODEL": "mistral"}):
            listener = ChatLogListener()
        assert listener._model == "mistral"

    def test_default_model_fallback(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            listener = ChatLogListener()
        assert listener._model == "unknown"

    # ------------------------------------------------------------------
    # Config keywords
    # ------------------------------------------------------------------

    def test_set_llm_model_logs_config(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Set LLM Model", ["mistral"]),
            _mock_keyword_result(),
        )
        assert len(listener._entries) == 1
        ts, model, ptype, msg = listener._entries[0]
        assert model == "mistral"
        assert ptype == "config"
        assert "model=mistral" in msg

    def test_set_llm_model_updates_model(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Set LLM Model", ["phi3"]),
            _mock_keyword_result(),
        )
        assert listener._model == "phi3"

    def test_set_llm_endpoint_logs_config(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Set LLM Endpoint", ["http://ai1:11434"]),
            _mock_keyword_result(),
        )
        assert len(listener._entries) == 1
        _, _, ptype, msg = listener._entries[0]
        assert ptype == "config"
        assert "endpoint=http://ai1:11434" in msg

    def test_set_llm_parameters_logs_config(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Set LLM Parameters", ["0.5", "512"]),
            _mock_keyword_result(),
        )
        assert len(listener._entries) == 1
        _, _, ptype, msg = listener._entries[0]
        assert ptype == "config"
        assert "parameters=" in msg
        assert "0.5" in msg
        assert "512" in msg

    # ------------------------------------------------------------------
    # Ask LLM
    # ------------------------------------------------------------------

    def test_ask_llm_logs_input(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["What is 2+2?"]),
            _mock_keyword_result(),
        )
        assert len(listener._entries) == 1
        _, _, ptype, msg = listener._entries[0]
        assert ptype == "input"
        assert msg == "What is 2+2?"

    def test_ask_llm_captures_output_via_log_message(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["What is 2+2?"]),
            _mock_keyword_result(),
        )
        listener.log_message(_mock_message("llama3 >> The answer is 4."))
        assert len(listener._entries) == 2
        _, _, ptype, msg = listener._entries[1]
        assert ptype == "output"
        assert msg == "The answer is 4."

    def test_ask_llm_output_uses_current_model(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Set LLM Model", ["mistral"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Set LLM Model"),
            _mock_keyword_result(),
        )
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["Hello"]),
            _mock_keyword_result(),
        )
        listener.log_message(_mock_message("mistral >> Hi there!"))
        # Both input and output entries should use "mistral"
        _, model_input, _, _ = listener._entries[1]
        _, model_output, _, _ = listener._entries[2]
        assert model_input == "mistral"
        assert model_output == "mistral"

    # ------------------------------------------------------------------
    # Grade Answer
    # ------------------------------------------------------------------

    def test_grade_answer_logs_grading(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Grade Answer", ["What is 2+2?", "4", "4"]),
            _mock_keyword_result(),
        )
        assert len(listener._entries) == 1
        _, _, ptype, msg = listener._entries[0]
        assert ptype == "grading"
        assert msg == "What is 2+2?"

    def test_grade_answer_captures_output(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Grade Answer", ["What is 2+2?", "4", "4"]),
            _mock_keyword_result(),
        )
        listener.log_message(
            _mock_message('llama3 >> {"score": 1, "reason": "correct"}')
        )
        assert len(listener._entries) == 2
        _, _, ptype, msg = listener._entries[1]
        assert ptype == "output"
        assert '"score": 1' in msg

    # ------------------------------------------------------------------
    # System keywords
    # ------------------------------------------------------------------

    def test_wait_for_llm_logs_system(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Wait For LLM"),
            _mock_keyword_result(),
        )
        assert len(listener._entries) == 1
        _, _, ptype, _ = listener._entries[0]
        assert ptype == "system"

    def test_get_running_models_logs_system(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Get Running Models"),
            _mock_keyword_result(),
        )
        _, _, ptype, _ = listener._entries[0]
        assert ptype == "system"

    def test_llm_is_busy_logs_system(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("LLM Is Busy"),
            _mock_keyword_result(),
        )
        _, _, ptype, _ = listener._entries[0]
        assert ptype == "system"

    # ------------------------------------------------------------------
    # Ignores non-tracked keywords
    # ------------------------------------------------------------------

    def test_ignores_non_tracked_keywords(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Should Be Equal", ["a", "b"]),
            _mock_keyword_result(),
        )
        assert listener._in_tracked_keyword is None
        assert len(listener._entries) == 0

    def test_log_message_ignored_outside_tracked_keyword(self) -> None:
        listener = ChatLogListener()
        listener.log_message(_mock_message("llama3 >> hello"))
        assert len(listener._entries) == 0

    # ------------------------------------------------------------------
    # End keyword clears state
    # ------------------------------------------------------------------

    def test_end_keyword_clears_tracked(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["test"]),
            _mock_keyword_result(),
        )
        assert listener._in_tracked_keyword == "Ask LLM"
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )
        assert listener._in_tracked_keyword is None

    def test_end_keyword_mismatched_name_no_clear(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["test"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Wait For LLM"),
            _mock_keyword_result(),
        )
        assert listener._in_tracked_keyword == "Ask LLM"

    # ------------------------------------------------------------------
    # File output
    # ------------------------------------------------------------------

    def test_end_suite_saves_chat_log(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["Hello"]),
            _mock_keyword_result(),
        )
        listener.log_message(_mock_message("llama3 >> Hi!"))
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(_mock_suite_data("Test Suite"), _mock_suite_result())

            path = os.path.join(tmpdir, "chat.log")
            assert os.path.exists(path)

            with open(path) as f:
                content = f.read()

            assert "# chat.log" in content
            assert "# Suite: Test Suite" in content
            assert "input\tHello" in content
            assert "output\tHi!" in content

    def test_end_suite_no_entries_no_file(self) -> None:
        listener = ChatLogListener()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(_mock_suite_data("Empty"), _mock_suite_result())
            assert not os.path.exists(os.path.join(tmpdir, "chat.log"))

    def test_suite_depth_only_saves_at_top_level(self) -> None:
        listener = ChatLogListener()
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
                listener.end_suite(_mock_suite_data("Nested"), _mock_suite_result())
                assert not os.path.exists(os.path.join(tmpdir, "chat.log"))

                listener.end_suite(_mock_suite_data("Top"), _mock_suite_result())
                assert os.path.exists(os.path.join(tmpdir, "chat.log"))

    def test_multiline_message_flattened(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["line1\nline2\nline3"]),
            _mock_keyword_result(),
        )
        assert len(listener._entries) == 1
        # The raw entry preserves newlines; flattening happens at write time
        _, _, _, msg = listener._entries[0]
        assert msg == "line1\nline2\nline3"

        # But the file output should flatten
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result())

            with open(os.path.join(tmpdir, "chat.log")) as f:
                lines = [ln for ln in f.readlines() if not ln.startswith("#")]

            assert len(lines) == 1
            assert "\n" not in lines[0].rstrip("\n")
            assert "line1 line2 line3" in lines[0]

    def test_timestamps_are_iso_format(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["test"]),
            _mock_keyword_result(),
        )
        ts, _, _, _ = listener._entries[0]
        assert ts.endswith("Z")
        assert "T" in ts

    def test_tab_separated_format(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["Hello world"]),
            _mock_keyword_result(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result())

            with open(os.path.join(tmpdir, "chat.log")) as f:
                data_lines = [ln for ln in f.readlines() if not ln.startswith("#")]

            assert len(data_lines) == 1
            parts = data_lines[0].strip().split("\t")
            assert len(parts) == 4
            assert parts[2] == "input"
            assert parts[3] == "Hello world"

    def test_empty_args_handled(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", []),
            _mock_keyword_result(),
        )
        _, _, ptype, msg = listener._entries[0]
        assert ptype == "input"
        assert msg == ""

    def test_no_args_handled(self) -> None:
        listener = ChatLogListener()
        listener.start_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )
        _, _, ptype, msg = listener._entries[0]
        assert ptype == "input"
        assert msg == ""

    def test_full_conversation_flow(self) -> None:
        """Simulate a realistic test run with multiple interactions."""
        listener = ChatLogListener()
        listener.start_suite(_mock_suite_data("Math Tests"), _mock_suite_result())

        # Configure
        listener.start_keyword(
            _mock_keyword_data("Set LLM Model", ["llama3"]),
            _mock_keyword_result(),
        )
        listener.end_keyword(
            _mock_keyword_data("Set LLM Model"),
            _mock_keyword_result(),
        )

        # Ask a question
        listener.start_keyword(
            _mock_keyword_data("Ask LLM", ["What is 2+2?"]),
            _mock_keyword_result(),
        )
        listener.log_message(_mock_message("llama3 >> 4"))
        listener.end_keyword(
            _mock_keyword_data("Ask LLM"),
            _mock_keyword_result(),
        )

        # Grade the answer
        listener.start_keyword(
            _mock_keyword_data("Grade Answer", ["What is 2+2?", "4", "4"]),
            _mock_keyword_result(),
        )
        listener.log_message(
            _mock_message('llama3 >> {"score": 1, "reason": "correct"}')
        )
        listener.end_keyword(
            _mock_keyword_data("Grade Answer"),
            _mock_keyword_result(),
        )

        assert len(listener._entries) == 5
        types = [e[2] for e in listener._entries]
        assert types == ["config", "input", "output", "grading", "output"]

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite(_mock_suite_data("Math Tests"), _mock_suite_result())

            with open(os.path.join(tmpdir, "chat.log")) as f:
                content = f.read()

            assert "config\tmodel=llama3" in content
            assert "input\tWhat is 2+2?" in content
            assert "output\t4" in content
            assert "grading\tWhat is 2+2?" in content
