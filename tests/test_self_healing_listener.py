"""Tests for rfc.self_healing_listener — SelfHealingEvent and SelfHealingListener."""

from unittest.mock import MagicMock


from rfc.self_healing_listener import SelfHealingEvent, SelfHealingListener


class TestSelfHealingEvent:
    def test_basic_creation(self):
        event = SelfHealingEvent(
            test_name="Test Math",
            test_status="FAIL",
            healing_data={
                "self_healing_attempts": "3",
                "self_healing_strategy": "prompt",
                "self_healing_success": "True",
                "self_healing_original_error": "wrong answer",
                "self_healing_duration_seconds": "1.5",
                "self_healing_strategies_tried": '["original", "prompt"]',
                "self_healing_prompt_history": '["p1", "p2"]',
            },
        )
        assert event.test_name == "Test Math"
        assert event.test_status == "FAIL"
        assert event.attempts == 3
        assert event.strategy == "prompt"
        assert event.success is True
        assert event.original_error == "wrong answer"
        assert event.duration_seconds == 1.5
        assert event.strategies_tried == ["original", "prompt"]
        assert event.prompt_history == ["p1", "p2"]

    def test_missing_keys_use_defaults(self):
        event = SelfHealingEvent(
            test_name="Test",
            test_status="PASS",
            healing_data={},
        )
        assert event.attempts == 0
        assert event.strategy == ""
        assert event.success is False
        assert event.original_error == ""
        assert event.duration_seconds == 0.0
        assert event.strategies_tried == []
        assert event.prompt_history == []

    def test_invalid_json_handled(self):
        event = SelfHealingEvent(
            test_name="Test",
            test_status="FAIL",
            healing_data={
                "self_healing_strategies_tried": "not json",
                "self_healing_prompt_history": "also not json",
            },
        )
        assert event.strategies_tried == []
        assert event.prompt_history == []

    def test_to_dict(self):
        event = SelfHealingEvent(
            test_name="Test",
            test_status="FAIL",
            healing_data={
                "self_healing_attempts": "2",
                "self_healing_strategy": "model",
                "self_healing_success": "True",
            },
        )
        d = event.to_dict()
        assert d["test_name"] == "Test"
        assert d["attempts"] == 2
        assert d["strategy"] == "model"
        assert d["success"] is True
        assert isinstance(d, dict)


class TestSelfHealingListener:
    def _make_listener(self):
        return SelfHealingListener()

    def _make_test_data(self, name="Test Case"):
        data = MagicMock()
        data.name = name
        return data

    def _make_result(self, status="FAIL"):
        result = MagicMock()
        result.status = status
        return result

    def test_init(self):
        listener = self._make_listener()
        assert listener.healing_events == []

    def test_captures_healing_event_on_test_end(self):
        listener = self._make_listener()
        # Simulate RFC_DATA capture by directly setting _current_test_data
        listener._current_test_data = {
            "self_healing_attempts": "2",
            "self_healing_strategy": "prompt",
            "self_healing_success": "True",
            "self_healing_original_error": "wrong",
            "self_healing_duration_seconds": "0.5",
            "self_healing_strategies_tried": '["original", "prompt"]',
            "self_healing_prompt_history": '["p1", "p2"]',
            "score": "0.5",  # non-healing key, should be ignored
        }
        data = self._make_test_data("Math Test")
        result = self._make_result("PASS")

        listener.on_test_end(data, result)

        events = listener.healing_events
        assert len(events) == 1
        assert events[0].test_name == "Math Test"
        assert events[0].attempts == 2
        assert events[0].success is True

    def test_ignores_test_without_healing(self):
        listener = self._make_listener()
        listener._current_test_data = {
            "score": "1.0",
            "actual_answer": "four",
        }
        data = self._make_test_data()
        result = self._make_result("PASS")

        listener.on_test_end(data, result)

        assert listener.healing_events == []

    def test_multiple_events(self):
        listener = self._make_listener()

        # First test
        listener._current_test_data = {
            "self_healing_attempts": "1",
            "self_healing_success": "True",
        }
        listener.on_test_end(self._make_test_data("Test 1"), self._make_result())

        # Second test
        listener._current_test_data = {
            "self_healing_attempts": "3",
            "self_healing_success": "False",
        }
        listener.on_test_end(self._make_test_data("Test 2"), self._make_result())

        events = listener.healing_events
        assert len(events) == 2
        assert events[0].test_name == "Test 1"
        assert events[1].test_name == "Test 2"

    def test_healing_events_returns_copy(self):
        listener = self._make_listener()
        events1 = listener.healing_events
        events2 = listener.healing_events
        assert events1 is not events2

    def test_suite_end_logs_summary(self):
        """on_suite_end should not raise even with events."""
        listener = self._make_listener()
        listener._current_test_data = {
            "self_healing_attempts": "1",
            "self_healing_success": "True",
        }
        listener.on_test_end(self._make_test_data(), self._make_result())

        # Should not raise
        listener.on_suite_end(MagicMock(), MagicMock())

    def test_suite_end_no_events(self):
        """on_suite_end should not raise with no events."""
        listener = self._make_listener()
        listener.on_suite_end(MagicMock(), MagicMock())

    def test_tracked_keywords(self):
        """Listener tracks the expected keywords."""
        listener = self._make_listener()
        assert "Ask LLM" in listener.TRACKED_KEYWORDS
        assert "Grade Answer" in listener.TRACKED_KEYWORDS
        assert "Ask And Grade With Retry" in listener.TRACKED_KEYWORDS

    def test_listener_api_version(self):
        listener = self._make_listener()
        assert listener.ROBOT_LISTENER_API_VERSION == 3
