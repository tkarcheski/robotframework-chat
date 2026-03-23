"""Tests for rfc.base_listener.BaseListener."""

from typing import ClassVar
from unittest.mock import MagicMock

from rfc.base_listener import BaseListener


def _mock_suite_data(name: str = "Suite") -> MagicMock:
    data = MagicMock()
    data.name = name
    return data


def _mock_suite_result() -> MagicMock:
    result = MagicMock()
    result.metadata = {}
    return result


def _mock_test_data(name: str = "Test") -> MagicMock:
    data = MagicMock()
    data.name = name
    return data


def _mock_test_result(status: str = "PASS") -> MagicMock:
    result = MagicMock()
    result.status = status
    return result


def _mock_message(text: str) -> MagicMock:
    msg = MagicMock()
    msg.message = text
    return msg


def _mock_keyword_data(name: str, args: list | None = None) -> MagicMock:
    data = MagicMock()
    data.name = name
    data.args = tuple(args) if args is not None else ()
    return data


def _mock_keyword_result() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Concrete subclass for testing
# ---------------------------------------------------------------------------


class StubListener(BaseListener):
    """Minimal concrete subclass that records hook calls."""

    TRACKED_KEYWORDS: ClassVar[dict[str, str]] = {
        "Ask LLM": "input",
        "Set LLM Model": "config",
    }

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []
        self.kw_types: list[str] = []

    def on_suite_start(self, data: MagicMock, result: MagicMock) -> None:
        self.calls.append("on_suite_start")

    def on_suite_end(self, data: MagicMock, result: MagicMock) -> None:
        self.calls.append("on_suite_end")

    def on_test_start(self, data: MagicMock, result: MagicMock) -> None:
        self.calls.append("on_test_start")

    def on_test_end(self, data: MagicMock, result: MagicMock) -> None:
        self.calls.append("on_test_end")

    def on_log_message(self, message: MagicMock) -> None:
        self.calls.append("on_log_message")

    def on_keyword_start(
        self, data: MagicMock, result: MagicMock, keyword_type: str
    ) -> None:
        self.calls.append("on_keyword_start")
        self.kw_types.append(keyword_type)

    def on_keyword_end(self, data: MagicMock, result: MagicMock) -> None:
        self.calls.append("on_keyword_end")


# ---------------------------------------------------------------------------
# Suite depth tracking
# ---------------------------------------------------------------------------


class TestSuiteDepth:
    def test_initial_depth_is_zero(self) -> None:
        listener = StubListener()
        assert listener._suite_depth == 0

    def test_start_suite_increments_depth(self) -> None:
        listener = StubListener()
        listener.start_suite(_mock_suite_data(), _mock_suite_result())
        assert listener._suite_depth == 1

    def test_on_suite_start_called_at_depth_one(self) -> None:
        listener = StubListener()
        listener.start_suite(_mock_suite_data(), _mock_suite_result())
        assert "on_suite_start" in listener.calls

    def test_on_suite_start_not_called_for_nested(self) -> None:
        listener = StubListener()
        listener.start_suite(_mock_suite_data(), _mock_suite_result())
        listener.calls.clear()
        listener.start_suite(_mock_suite_data("Nested"), _mock_suite_result())
        assert "on_suite_start" not in listener.calls

    def test_end_suite_decrements_depth(self) -> None:
        listener = StubListener()
        listener.start_suite(_mock_suite_data(), _mock_suite_result())
        listener.end_suite(_mock_suite_data(), _mock_suite_result())
        assert listener._suite_depth == 0

    def test_on_suite_end_called_at_depth_zero(self) -> None:
        listener = StubListener()
        listener.start_suite(_mock_suite_data(), _mock_suite_result())
        listener.end_suite(_mock_suite_data(), _mock_suite_result())
        assert "on_suite_end" in listener.calls

    def test_on_suite_end_not_called_for_nested(self) -> None:
        listener = StubListener()
        listener.start_suite(_mock_suite_data(), _mock_suite_result())
        listener.start_suite(_mock_suite_data("Nested"), _mock_suite_result())
        listener.end_suite(_mock_suite_data("Nested"), _mock_suite_result())
        assert "on_suite_end" not in listener.calls

    def test_full_nested_lifecycle(self) -> None:
        listener = StubListener()
        # Top-level start
        listener.start_suite(_mock_suite_data("Top"), _mock_suite_result())
        assert listener._suite_depth == 1
        # Nested start
        listener.start_suite(_mock_suite_data("Child"), _mock_suite_result())
        assert listener._suite_depth == 2
        # Nested end
        listener.end_suite(_mock_suite_data("Child"), _mock_suite_result())
        assert listener._suite_depth == 1
        # Top-level end
        listener.end_suite(_mock_suite_data("Top"), _mock_suite_result())
        assert listener._suite_depth == 0
        # on_suite_start and on_suite_end each called exactly once
        assert listener.calls.count("on_suite_start") == 1
        assert listener.calls.count("on_suite_end") == 1


# ---------------------------------------------------------------------------
# RFC_DATA capture
# ---------------------------------------------------------------------------


class TestRfcDataCapture:
    def test_rfc_data_parsed_into_current_test_data(self) -> None:
        listener = StubListener()
        listener.start_test(_mock_test_data(), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:actual_answer:42"))
        assert listener._current_test_data == {"actual_answer": "42"}

    def test_rfc_data_multiple_keys(self) -> None:
        listener = StubListener()
        listener.start_test(_mock_test_data(), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:key1:val1"))
        listener.log_message(_mock_message("RFC_DATA:key2:val2"))
        assert listener._current_test_data == {"key1": "val1", "key2": "val2"}

    def test_rfc_data_value_with_colons(self) -> None:
        listener = StubListener()
        listener.start_test(_mock_test_data(), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:url:http://localhost:8080"))
        assert listener._current_test_data["url"] == "http://localhost:8080"

    def test_rfc_data_overwrite_same_key(self) -> None:
        listener = StubListener()
        listener.start_test(_mock_test_data(), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:key:old"))
        listener.log_message(_mock_message("RFC_DATA:key:new"))
        assert listener._current_test_data["key"] == "new"

    def test_rfc_data_reset_between_tests(self) -> None:
        listener = StubListener()
        listener.start_test(_mock_test_data("T1"), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:key:val"))
        listener.end_test(_mock_test_data("T1"), _mock_test_result())
        listener.start_test(_mock_test_data("T2"), _mock_test_result())
        assert listener._current_test_data == {}

    def test_non_rfc_data_message_calls_on_log_message(self) -> None:
        listener = StubListener()
        listener.start_test(_mock_test_data(), _mock_test_result())
        listener.log_message(_mock_message("hello world"))
        assert "on_log_message" in listener.calls

    def test_rfc_data_message_does_not_call_on_log_message(self) -> None:
        listener = StubListener()
        listener.start_test(_mock_test_data(), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:key:val"))
        assert "on_log_message" not in listener.calls

    def test_non_string_message_ignored(self) -> None:
        listener = StubListener()
        msg = MagicMock()
        msg.message = 12345
        listener.log_message(msg)
        assert listener._current_test_data == {}

    def test_empty_key_ignored(self) -> None:
        listener = StubListener()
        listener.start_test(_mock_test_data(), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA::value"))
        assert listener._current_test_data == {}


# ---------------------------------------------------------------------------
# Test lifecycle hooks
# ---------------------------------------------------------------------------


class TestTestLifecycle:
    def test_on_test_start_called(self) -> None:
        listener = StubListener()
        listener.start_test(_mock_test_data(), _mock_test_result())
        assert "on_test_start" in listener.calls

    def test_on_test_end_called(self) -> None:
        listener = StubListener()
        listener.start_test(_mock_test_data(), _mock_test_result())
        listener.end_test(_mock_test_data(), _mock_test_result())
        assert "on_test_end" in listener.calls

    def test_current_test_data_available_during_on_test_end(self) -> None:
        """on_test_end should see data before it gets cleared."""

        class CheckDataListener(BaseListener):
            def __init__(self) -> None:
                super().__init__()
                self.captured: dict[str, str] = {}

            def on_test_end(self, data: MagicMock, result: MagicMock) -> None:
                self.captured = dict(self._current_test_data)

        listener = CheckDataListener()
        listener.start_test(_mock_test_data(), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:answer:42"))
        listener.end_test(_mock_test_data(), _mock_test_result())
        assert listener.captured == {"answer": "42"}
        # Cleared after on_test_end
        assert listener._current_test_data == {}


# ---------------------------------------------------------------------------
# Keyword tracking
# ---------------------------------------------------------------------------


class TestKeywordTracking:
    def test_tracked_keyword_calls_on_keyword_start(self) -> None:
        listener = StubListener()
        kw_data = _mock_keyword_data("Ask LLM", ["prompt"])
        listener.start_keyword(kw_data, _mock_keyword_result())
        assert "on_keyword_start" in listener.calls
        assert listener.kw_types == ["input"]

    def test_untracked_keyword_ignored(self) -> None:
        listener = StubListener()
        kw_data = _mock_keyword_data("Log", ["msg"])
        listener.start_keyword(kw_data, _mock_keyword_result())
        assert "on_keyword_start" not in listener.calls

    def test_keyword_type_passed_correctly(self) -> None:
        listener = StubListener()
        kw_data = _mock_keyword_data("Set LLM Model", ["llama3"])
        listener.start_keyword(kw_data, _mock_keyword_result())
        assert listener.kw_types == ["config"]

    def test_end_keyword_calls_on_keyword_end(self) -> None:
        listener = StubListener()
        kw_data = _mock_keyword_data("Ask LLM", ["prompt"])
        listener.start_keyword(kw_data, _mock_keyword_result())
        listener.end_keyword(kw_data, _mock_keyword_result())
        assert "on_keyword_end" in listener.calls

    def test_end_keyword_clears_tracked_state(self) -> None:
        listener = StubListener()
        kw_data = _mock_keyword_data("Ask LLM", ["prompt"])
        listener.start_keyword(kw_data, _mock_keyword_result())
        assert listener._in_tracked_keyword == "Ask LLM"
        listener.end_keyword(kw_data, _mock_keyword_result())
        assert listener._in_tracked_keyword is None

    def test_end_keyword_mismatched_name_ignored(self) -> None:
        listener = StubListener()
        kw_data = _mock_keyword_data("Ask LLM", ["prompt"])
        other_kw = _mock_keyword_data("Log", [])
        listener.start_keyword(kw_data, _mock_keyword_result())
        listener.end_keyword(other_kw, _mock_keyword_result())
        assert "on_keyword_end" not in listener.calls
        assert listener._in_tracked_keyword == "Ask LLM"

    def test_no_tracked_keywords_by_default(self) -> None:
        """BaseListener with no TRACKED_KEYWORDS ignores all keywords."""
        listener = BaseListener()
        kw_data = _mock_keyword_data("Ask LLM", ["prompt"])
        listener.start_keyword(kw_data, _mock_keyword_result())
        assert listener._in_tracked_keyword is None


# ---------------------------------------------------------------------------
# Default hook implementations (no-ops)
# ---------------------------------------------------------------------------


class TestDefaultHooks:
    def test_default_hooks_are_noop(self) -> None:
        """BaseListener hooks do nothing by default (no crash)."""
        listener = BaseListener()
        listener.start_suite(_mock_suite_data(), _mock_suite_result())
        listener.start_test(_mock_test_data(), _mock_test_result())
        listener.log_message(_mock_message("hello"))
        listener.end_test(_mock_test_data(), _mock_test_result())
        listener.end_suite(_mock_suite_data(), _mock_suite_result())

    def test_listener_api_version(self) -> None:
        assert BaseListener.ROBOT_LISTENER_API_VERSION == 3
