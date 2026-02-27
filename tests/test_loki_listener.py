"""Tests for LokiListener."""

import json
import os
from unittest.mock import MagicMock, patch

import requests

from rfc.loki_listener import LokiListener


class TestLokiListenerInit:
    """Tests for LokiListener initialization and configuration."""

    def test_robot_listener_api_version(self):
        listener = LokiListener()
        assert listener.ROBOT_LISTENER_API_VERSION == 2

    def test_initial_state(self):
        listener = LokiListener()
        assert listener._entries == []
        assert listener._in_tracked_keyword is None
        assert listener._suite_depth == 0
        assert listener._suite_name is None

    def test_default_loki_url(self):
        with patch.dict(os.environ, {}, clear=True):
            listener = LokiListener()
        assert listener._loki_url == "http://localhost:3100"

    def test_loki_url_from_env(self):
        with patch.dict(os.environ, {"LOKI_URL": "http://loki:3100"}):
            listener = LokiListener()
        assert listener._loki_url == "http://loki:3100"

    def test_loki_url_from_constructor(self):
        listener = LokiListener(loki_url="http://custom:3100")
        assert listener._loki_url == "http://custom:3100"

    def test_default_model_from_env(self):
        with patch.dict(os.environ, {"DEFAULT_MODEL": "mistral"}):
            listener = LokiListener()
        assert listener._model == "mistral"

    def test_default_model_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            listener = LokiListener()
        assert listener._model == "unknown"


class TestLokiListenerKeywordTracking:
    """Tests for keyword detection and entry creation."""

    def test_ask_llm_creates_input_entry(self):
        listener = LokiListener()
        listener.start_keyword("Ask LLM", {"args": ["What is 2+2?"]})
        assert len(listener._entries) == 1
        entry = listener._entries[0]
        assert entry["event_type"] == "input"
        assert entry["message"] == "What is 2+2?"

    def test_set_llm_model_creates_config_entry(self):
        listener = LokiListener()
        listener.start_keyword("Set LLM Model", {"args": ["llama3"]})
        assert len(listener._entries) == 1
        entry = listener._entries[0]
        assert entry["event_type"] == "config"
        assert "model=llama3" in entry["message"]

    def test_set_llm_model_updates_model(self):
        listener = LokiListener()
        listener.start_keyword("Set LLM Model", {"args": ["phi3"]})
        assert listener._model == "phi3"

    def test_set_llm_endpoint_creates_config_entry(self):
        listener = LokiListener()
        listener.start_keyword("Set LLM Endpoint", {"args": ["http://ai1:11434"]})
        assert len(listener._entries) == 1
        entry = listener._entries[0]
        assert entry["event_type"] == "config"
        assert "endpoint=http://ai1:11434" in entry["message"]

    def test_set_llm_parameters_creates_config_entry(self):
        listener = LokiListener()
        listener.start_keyword("Set LLM Parameters", {"args": ["0.5", "512"]})
        entry = listener._entries[0]
        assert entry["event_type"] == "config"
        assert "parameters=" in entry["message"]

    def test_grade_answer_creates_grading_entry(self):
        listener = LokiListener()
        listener.start_keyword("Grade Answer", {"args": ["What is 2+2?", "4", "4"]})
        entry = listener._entries[0]
        assert entry["event_type"] == "grading"
        assert entry["message"] == "What is 2+2?"

    def test_wait_for_llm_creates_system_entry(self):
        listener = LokiListener()
        listener.start_keyword("Wait For LLM", {"args": []})
        entry = listener._entries[0]
        assert entry["event_type"] == "system"

    def test_get_running_models_creates_system_entry(self):
        listener = LokiListener()
        listener.start_keyword("Get Running Models", {"args": []})
        entry = listener._entries[0]
        assert entry["event_type"] == "system"

    def test_llm_is_busy_creates_system_entry(self):
        listener = LokiListener()
        listener.start_keyword("LLM Is Busy", {"args": []})
        entry = listener._entries[0]
        assert entry["event_type"] == "system"

    def test_ignores_non_tracked_keywords(self):
        listener = LokiListener()
        listener.start_keyword("Should Be Equal", {"args": ["a", "b"]})
        assert listener._in_tracked_keyword is None
        assert len(listener._entries) == 0

    def test_end_keyword_clears_tracked(self):
        listener = LokiListener()
        listener.start_keyword("Ask LLM", {"args": ["test"]})
        assert listener._in_tracked_keyword == "Ask LLM"
        listener.end_keyword("Ask LLM", {})
        assert listener._in_tracked_keyword is None

    def test_end_keyword_mismatched_name_no_clear(self):
        listener = LokiListener()
        listener.start_keyword("Ask LLM", {"args": ["test"]})
        listener.end_keyword("Wait For LLM", {})
        assert listener._in_tracked_keyword == "Ask LLM"

    def test_empty_args_handled(self):
        listener = LokiListener()
        listener.start_keyword("Ask LLM", {"args": []})
        entry = listener._entries[0]
        assert entry["event_type"] == "input"
        assert entry["message"] == ""

    def test_no_args_key_handled(self):
        listener = LokiListener()
        listener.start_keyword("Ask LLM", {})
        entry = listener._entries[0]
        assert entry["event_type"] == "input"
        assert entry["message"] == ""


class TestLokiListenerLogMessage:
    """Tests for LLM response capture via log_message."""

    def test_captures_llm_output_during_ask(self):
        listener = LokiListener()
        listener.start_keyword("Ask LLM", {"args": ["What is 2+2?"]})
        listener.log_message({"message": "llama3 >> The answer is 4.", "level": "INFO"})
        assert len(listener._entries) == 2
        entry = listener._entries[1]
        assert entry["event_type"] == "output"
        assert entry["message"] == "The answer is 4."

    def test_captures_llm_output_during_grade(self):
        listener = LokiListener()
        listener.start_keyword("Grade Answer", {"args": ["Q?", "A", "A"]})
        listener.log_message({"message": 'llama3 >> {"score": 1}', "level": "INFO"})
        assert len(listener._entries) == 2
        entry = listener._entries[1]
        assert entry["event_type"] == "output"

    def test_ignores_log_message_outside_tracked_keyword(self):
        listener = LokiListener()
        listener.log_message({"message": "llama3 >> hello", "level": "INFO"})
        assert len(listener._entries) == 0

    def test_ignores_log_message_without_arrow(self):
        listener = LokiListener()
        listener.start_keyword("Ask LLM", {"args": ["test"]})
        listener.log_message({"message": "some other log", "level": "INFO"})
        assert len(listener._entries) == 1  # only the input entry


class TestLokiListenerEntryFormat:
    """Tests for the Loki push API payload format."""

    def test_entry_has_required_fields(self):
        listener = LokiListener()
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        entry = listener._entries[0]
        assert "timestamp" in entry
        assert "event_type" in entry
        assert "message" in entry
        assert "model" in entry

    def test_entry_timestamp_is_nanoseconds(self):
        listener = LokiListener()
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        entry = listener._entries[0]
        # Loki expects nanosecond timestamps as strings
        ts = entry["timestamp"]
        assert isinstance(ts, str)
        assert len(ts) >= 19  # nanosecond precision

    def test_build_push_payload_structure(self):
        listener = LokiListener()
        listener._suite_name = "Math Tests"
        listener.start_keyword("Ask LLM", {"args": ["What is 2+2?"]})
        listener.log_message({"message": "llama3 >> 4", "level": "INFO"})

        payload = listener._build_push_payload()
        assert "streams" in payload
        assert len(payload["streams"]) > 0

        stream = payload["streams"][0]
        assert "stream" in stream
        assert "values" in stream
        assert stream["stream"]["job"] == "robotframework"
        assert stream["stream"]["suite"] == "Math Tests"

    def test_build_push_payload_groups_by_event_type(self):
        listener = LokiListener()
        listener._suite_name = "Tests"
        listener.start_keyword("Ask LLM", {"args": ["q1"]})
        listener.end_keyword("Ask LLM", {})
        listener.start_keyword("Set LLM Model", {"args": ["llama3"]})
        listener.end_keyword("Set LLM Model", {})

        payload = listener._build_push_payload()
        # Should have separate streams for different event types
        event_types = {s["stream"]["event_type"] for s in payload["streams"]}
        assert "input" in event_types
        assert "config" in event_types

    def test_build_push_payload_values_format(self):
        """Each value should be [timestamp_ns, log_line]."""
        listener = LokiListener()
        listener._suite_name = "Tests"
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})

        payload = listener._build_push_payload()
        stream = payload["streams"][0]
        assert len(stream["values"]) == 1
        ts, line = stream["values"][0]
        assert isinstance(ts, str)
        assert isinstance(line, str)
        assert "Hello" in line

    def test_empty_entries_produces_empty_streams(self):
        listener = LokiListener()
        payload = listener._build_push_payload()
        assert payload == {"streams": []}


class TestLokiListenerSuiteTracking:
    """Tests for suite depth tracking and flush behavior."""

    def test_start_suite_increments_depth(self):
        listener = LokiListener()
        listener.start_suite("Top", {})
        assert listener._suite_depth == 1

    def test_start_suite_captures_name(self):
        listener = LokiListener()
        listener.start_suite("Math Tests", {})
        assert listener._suite_name == "Math Tests"

    def test_nested_suite_does_not_flush(self):
        listener = LokiListener()
        listener.start_suite("Top", {})
        listener.start_suite("Nested", {})
        listener.start_keyword("Ask LLM", {"args": ["test"]})
        listener.end_keyword("Ask LLM", {})

        with patch.object(listener, "_flush_to_loki") as mock_flush:
            listener.end_suite("Nested", {"totaltests": 1})
            mock_flush.assert_not_called()

    def test_top_level_suite_flushes(self):
        listener = LokiListener()
        listener.start_suite("Top", {})
        listener.start_keyword("Ask LLM", {"args": ["test"]})
        listener.end_keyword("Ask LLM", {})

        with patch.object(listener, "_flush_to_loki") as mock_flush:
            listener.end_suite("Top", {"totaltests": 1})
            mock_flush.assert_called_once()

    def test_no_entries_no_flush(self):
        listener = LokiListener()
        listener.start_suite("Top", {})
        with patch.object(listener, "_flush_to_loki") as mock_flush:
            listener.end_suite("Top", {"totaltests": 0})
            mock_flush.assert_not_called()

    def test_flush_clears_entries(self):
        listener = LokiListener()
        listener.start_suite("Top", {})
        listener.start_keyword("Ask LLM", {"args": ["test"]})
        listener.end_keyword("Ask LLM", {})

        with patch("rfc.loki_listener.requests.post"):
            listener.end_suite("Top", {"totaltests": 1})

        assert listener._entries == []


class TestLokiListenerHTTPPush:
    """Tests for the HTTP push to Loki."""

    def test_flush_posts_to_loki_push_endpoint(self):
        listener = LokiListener(loki_url="http://loki:3100")
        listener.start_suite("Tests", {})
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        listener.end_keyword("Ask LLM", {})

        with patch("rfc.loki_listener.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=204)
            listener.end_suite("Tests", {"totaltests": 1})

            mock_post.assert_called_once()
            url = mock_post.call_args[0][0]
            assert url == "http://loki:3100/loki/api/v1/push"

            kwargs = mock_post.call_args[1]
            assert kwargs["headers"]["Content-Type"] == "application/json"
            payload = json.loads(kwargs["data"])
            assert "streams" in payload

    def test_flush_graceful_on_connection_error(self):
        """Loki being unreachable should not raise."""
        listener = LokiListener()
        listener.start_suite("Tests", {})
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        listener.end_keyword("Ask LLM", {})

        with patch("rfc.loki_listener.requests.post") as mock_post:
            mock_post.side_effect = requests.ConnectionError("refused")
            # Should not raise
            listener.end_suite("Tests", {"totaltests": 1})

    def test_flush_graceful_on_http_error(self):
        """Non-2xx response should not raise."""
        listener = LokiListener()
        listener.start_suite("Tests", {})
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        listener.end_keyword("Ask LLM", {})

        with patch("rfc.loki_listener.requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=500, text="Internal Server Error"
            )
            # Should not raise
            listener.end_suite("Tests", {"totaltests": 1})

    def test_flush_graceful_on_timeout(self):
        """Timeout should not raise."""
        listener = LokiListener()
        listener.start_suite("Tests", {})
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        listener.end_keyword("Ask LLM", {})

        with patch("rfc.loki_listener.requests.post") as mock_post:
            mock_post.side_effect = requests.Timeout("timed out")
            listener.end_suite("Tests", {"totaltests": 1})

    def test_flush_uses_short_timeout(self):
        """HTTP push should use a reasonable timeout to avoid blocking tests."""
        listener = LokiListener()
        listener.start_suite("Tests", {})
        listener.start_keyword("Ask LLM", {"args": ["Hello"]})
        listener.end_keyword("Ask LLM", {})

        with patch("rfc.loki_listener.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=204)
            listener.end_suite("Tests", {"totaltests": 1})

            kwargs = mock_post.call_args[1]
            assert kwargs["timeout"] <= 5


class TestLokiListenerFullFlow:
    """End-to-end flow tests simulating realistic test runs."""

    def test_full_conversation_flow(self):
        listener = LokiListener()
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
        listener.log_message(
            {"message": 'llama3 >> {"score": 1, "reason": "correct"}', "level": "INFO"}
        )
        listener.end_keyword("Grade Answer", {})

        assert len(listener._entries) == 5
        event_types = [e["event_type"] for e in listener._entries]
        assert event_types == ["config", "input", "output", "grading", "output"]

        # Verify model label is updated after Set LLM Model
        for entry in listener._entries[1:]:
            assert entry["model"] == "llama3"

        # Verify push payload
        payload = listener._build_push_payload()
        assert len(payload["streams"]) > 0
        all_labels = {s["stream"]["event_type"] for s in payload["streams"]}
        assert all_labels == {"config", "input", "output", "grading"}

    def test_multiline_message_preserved_in_entry(self):
        listener = LokiListener()
        listener.start_keyword("Ask LLM", {"args": ["line1\nline2\nline3"]})
        entry = listener._entries[0]
        assert entry["message"] == "line1\nline2\nline3"
