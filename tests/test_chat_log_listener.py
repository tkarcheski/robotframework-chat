"""Tests for ChatLogListener."""

import os
import tempfile
from unittest.mock import patch

from rfc.chat_log_listener import ChatLogListener


class TestChatLogListener:
    """Unit tests for the chat log listener."""

    def test_robot_listener_api_version(self):
        listener = ChatLogListener()
        assert listener.ROBOT_LISTENER_API_VERSION == 2

    def test_initial_state(self):
        listener = ChatLogListener()
        assert listener._entries == []
        assert listener._in_tracked_keyword is None

    def test_default_model_from_env(self):
        with patch.dict(os.environ, {"DEFAULT_MODEL": "mistral"}):
            listener = ChatLogListener()
        assert listener._model == "mistral"

    def test_default_model_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            listener = ChatLogListener()
        assert listener._model == "unknown"

    # ------------------------------------------------------------------
    # Config keywords
    # ------------------------------------------------------------------

    def test_set_llm_model_logs_config(self):
        listener = ChatLogListener()
        listener.start_keyword("Set LLM Model", {"args": ["mistral"]})
        assert len(listener._entries) == 1
        ts, model, ptype, msg = listener._entries[0]
        assert model == "mistral"
        assert ptype == "config"
        assert "model=mistral" in msg

    def test_set_llm_model_updates_model(self):
        listener = ChatLogListener()
        listener.start_keyword("Set LLM Model", {"args": ["phi3"]})
        assert listener._model == "phi3"

    def test_set_llm_endpoint_logs_config(self):
        listener = ChatLogListener()
        listener.start_keyword(
            "Set LLM Endpoint", {"args": ["http://ai1:11434"]}
        )
        assert len(listener._entries) == 1
        _, _, ptype, msg = listener._entries[0]
        assert ptype == "config"
        assert "endpoint=http://ai1:11434" in msg

    def test_set_llm_parameters_logs_config(self):
        listener = ChatLogListener()
        listener.start_keyword("Set LLM Parameters", {"args": ["0.5", "512"]})
        assert len(listener._entries) == 1
        _, _, ptype, msg = listener._entries[0]
        assert ptype == "config"
        assert "parameters=" in msg
        assert "0.5" in msg
        assert "512" in msg

    # ------------------------------------------------------------------
    # Ask LLM
    # ------------------------------------------------------------------

    def test_ask_llm_logs_input(self):
        listener = ChatLogListener()
        listener.start_keyword("Ask LLM", {"args": ["What is 2+2?"]})
        assert len(listener._entries) == 1
        _, _, ptype, msg = listener._entries[0]
        assert ptype == "input"
        assert msg == "What is 2+2?"

    def test_ask_llm_captures_output_via_log_message(self):
        listener = ChatLogListener()
        listener.start_keyword("Ask LLM", {"args": ["What is 2+2?"]})
        listener.log_message({"message": "llama3 >> The answer is 4.", "level": "INFO"})
        assert len(listener._entries) == 2
        _, _, ptype, msg = listener._entries[1]
        assert ptype == "output"
        assert msg == "The answer is 4."

    def test_ask_llm_output_uses_current_model(self):
        listener = ChatLogListener()
        listener.start_keyword("Set LLM Model", {"args": ["mistral"]})
        listener.end_keyword("Set LLM Model", {})
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        listener.log_message({"message": "mistral >> Hi there!", "level": "INFO"})
        # Both input and output entries should use "mistral"
        _, model_input, _, _ = listener._entries[1]
        _, model_output, _, _ = listener._entries[2]
        assert model_input == "mistral"
        assert model_output == "mistral"

    # ------------------------------------------------------------------
    # Grade Answer
    # ------------------------------------------------------------------

    def test_grade_answer_logs_grading(self):
        listener = ChatLogListener()
        listener.start_keyword(
            "Grade Answer", {"args": ["What is 2+2?", "4", "4"]}
        )
        assert len(listener._entries) == 1
        _, _, ptype, msg = listener._entries[0]
        assert ptype == "grading"
        assert msg == "What is 2+2?"

    def test_grade_answer_captures_output(self):
        listener = ChatLogListener()
        listener.start_keyword(
            "Grade Answer", {"args": ["What is 2+2?", "4", "4"]}
        )
        listener.log_message({
            "message": 'llama3 >> {"score": 1, "reason": "correct"}',
            "level": "INFO",
        })
        assert len(listener._entries) == 2
        _, _, ptype, msg = listener._entries[1]
        assert ptype == "output"
        assert '"score": 1' in msg

    # ------------------------------------------------------------------
    # System keywords
    # ------------------------------------------------------------------

    def test_wait_for_llm_logs_system(self):
        listener = ChatLogListener()
        listener.start_keyword("Wait For LLM", {"args": []})
        assert len(listener._entries) == 1
        _, _, ptype, _ = listener._entries[0]
        assert ptype == "system"

    def test_get_running_models_logs_system(self):
        listener = ChatLogListener()
        listener.start_keyword("Get Running Models", {"args": []})
        _, _, ptype, _ = listener._entries[0]
        assert ptype == "system"

    def test_llm_is_busy_logs_system(self):
        listener = ChatLogListener()
        listener.start_keyword("LLM Is Busy", {"args": []})
        _, _, ptype, _ = listener._entries[0]
        assert ptype == "system"

    # ------------------------------------------------------------------
    # Ignores non-tracked keywords
    # ------------------------------------------------------------------

    def test_ignores_non_tracked_keywords(self):
        listener = ChatLogListener()
        listener.start_keyword("Should Be Equal", {"args": ["a", "b"]})
        assert listener._in_tracked_keyword is None
        assert len(listener._entries) == 0

    def test_log_message_ignored_outside_tracked_keyword(self):
        listener = ChatLogListener()
        listener.log_message({"message": "llama3 >> hello", "level": "INFO"})
        assert len(listener._entries) == 0

    # ------------------------------------------------------------------
    # End keyword clears state
    # ------------------------------------------------------------------

    def test_end_keyword_clears_tracked(self):
        listener = ChatLogListener()
        listener.start_keyword("Ask LLM", {"args": ["test"]})
        assert listener._in_tracked_keyword == "Ask LLM"
        listener.end_keyword("Ask LLM", {})
        assert listener._in_tracked_keyword is None

    def test_end_keyword_mismatched_name_no_clear(self):
        listener = ChatLogListener()
        listener.start_keyword("Ask LLM", {"args": ["test"]})
        listener.end_keyword("Wait For LLM", {})
        assert listener._in_tracked_keyword == "Ask LLM"

    # ------------------------------------------------------------------
    # File output
    # ------------------------------------------------------------------

    def test_end_suite_saves_chat_log(self):
        listener = ChatLogListener()
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        listener.log_message({"message": "llama3 >> Hi!", "level": "INFO"})
        listener.end_keyword("Ask LLM", {})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("Test Suite", {"totaltests": 1})

            path = os.path.join(tmpdir, "chat.log")
            assert os.path.exists(path)

            with open(path) as f:
                content = f.read()

            assert "# chat.log" in content
            assert "# Suite: Test Suite" in content
            assert "input\tHello" in content
            assert "output\tHi!" in content

    def test_end_suite_no_entries_no_file(self):
        listener = ChatLogListener()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("Empty", {"totaltests": 0})
            assert not os.path.exists(os.path.join(tmpdir, "chat.log"))

    def test_suite_depth_only_saves_at_top_level(self):
        listener = ChatLogListener()
        listener.start_suite("Top", {})
        listener.start_suite("Nested", {})
        listener.start_keyword("Ask LLM", {"args": ["test"]})
        listener.end_keyword("Ask LLM", {})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("Nested", {"totaltests": 1})
                assert not os.path.exists(os.path.join(tmpdir, "chat.log"))

                listener.end_suite("Top", {"totaltests": 1})
                assert os.path.exists(os.path.join(tmpdir, "chat.log"))

    def test_multiline_message_flattened(self):
        listener = ChatLogListener()
        listener.start_keyword("Ask LLM", {"args": ["line1\nline2\nline3"]})
        assert len(listener._entries) == 1
        # The raw entry preserves newlines; flattening happens at write time
        _, _, _, msg = listener._entries[0]
        assert msg == "line1\nline2\nline3"

        # But the file output should flatten
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("Suite", {"totaltests": 1})

            with open(os.path.join(tmpdir, "chat.log")) as f:
                lines = [ln for ln in f.readlines() if not ln.startswith("#")]

            assert len(lines) == 1
            assert "\n" not in lines[0].rstrip("\n")
            assert "line1 line2 line3" in lines[0]

    def test_timestamps_are_iso_format(self):
        listener = ChatLogListener()
        listener.start_keyword("Ask LLM", {"args": ["test"]})
        ts, _, _, _ = listener._entries[0]
        assert ts.endswith("Z")
        assert "T" in ts

    def test_tab_separated_format(self):
        listener = ChatLogListener()
        listener.start_keyword("Ask LLM", {"args": ["Hello world"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("Suite", {"totaltests": 1})

            with open(os.path.join(tmpdir, "chat.log")) as f:
                data_lines = [ln for ln in f.readlines() if not ln.startswith("#")]

            assert len(data_lines) == 1
            parts = data_lines[0].strip().split("\t")
            assert len(parts) == 4
            assert parts[2] == "input"
            assert parts[3] == "Hello world"

    def test_empty_args_handled(self):
        listener = ChatLogListener()
        listener.start_keyword("Ask LLM", {"args": []})
        _, _, ptype, msg = listener._entries[0]
        assert ptype == "input"
        assert msg == ""

    def test_no_args_key_handled(self):
        listener = ChatLogListener()
        listener.start_keyword("Ask LLM", {})
        _, _, ptype, msg = listener._entries[0]
        assert ptype == "input"
        assert msg == ""

    def test_full_conversation_flow(self):
        """Simulate a realistic test run with multiple interactions."""
        listener = ChatLogListener()
        listener.start_suite("Math Tests", {})

        # Configure
        listener.start_keyword("Set LLM Model", {"args": ["llama3"]})
        listener.end_keyword("Set LLM Model", {})

        # Ask a question
        listener.start_keyword("Ask LLM", {"args": ["What is 2+2?"]})
        listener.log_message({"message": "llama3 >> 4", "level": "INFO"})
        listener.end_keyword("Ask LLM", {})

        # Grade the answer
        listener.start_keyword("Grade Answer", {"args": ["What is 2+2?", "4", "4"]})
        listener.log_message({
            "message": 'llama3 >> {"score": 1, "reason": "correct"}',
            "level": "INFO",
        })
        listener.end_keyword("Grade Answer", {})

        assert len(listener._entries) == 5
        types = [e[2] for e in listener._entries]
        assert types == ["config", "input", "output", "grading", "output"]

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": tmpdir}):
                listener.end_suite("Math Tests", {"totaltests": 1})

            with open(os.path.join(tmpdir, "chat.log")) as f:
                content = f.read()

            assert "config\tmodel=llama3" in content
            assert "input\tWhat is 2+2?" in content
            assert "output\t4" in content
            assert "grading\tWhat is 2+2?" in content
