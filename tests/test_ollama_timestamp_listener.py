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
