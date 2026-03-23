"""Tests for rfc.dry_run_listener.DryRunListener (Listener API v3)."""

from unittest.mock import MagicMock, patch

from rfc.dry_run_listener import DryRunListener


def _mock_suite_data(name: str = "Suite") -> MagicMock:
    """Create a mock running.TestSuite (data) object."""
    data = MagicMock()
    data.name = name
    return data


def _mock_suite_result(total: int = 3) -> MagicMock:
    """Create a mock result.TestSuite (result) object."""
    result = MagicMock()
    result.statistics.total = total
    result.statistics.passed = 0
    result.statistics.failed = 0
    result.statistics.skipped = 0
    result.metadata = {}
    return result


def _mock_test_data(name: str = "Test") -> MagicMock:
    """Create a mock running.TestCase (data) object."""
    data = MagicMock()
    data.name = name
    return data


def _mock_test_result(status: str = "PASS", message: str = "") -> MagicMock:
    """Create a mock result.TestCase (result) object."""
    result = MagicMock()
    result.status = status
    result.message = message
    return result


class TestDryRunListenerInit:
    def test_api_version(self) -> None:
        listener = DryRunListener()
        assert listener.ROBOT_LISTENER_API_VERSION == 3

    def test_initial_state(self) -> None:
        listener = DryRunListener()
        assert listener._start_time is None
        assert listener._test_cases == []

    def test_accepts_database_url_arg(self) -> None:
        """--listener DryRunListener:sqlite:///tmp.db must not raise."""
        listener = DryRunListener("sqlite:///tmp.db")
        assert listener._start_time is None
        assert listener._errors == []
        assert listener._suite_depth == 0


class TestDryRunListenerStartSuite:
    def test_start_suite_initializes_state(self) -> None:
        listener = DryRunListener()
        listener.start_suite(_mock_suite_data("TopLevel"), _mock_suite_result())
        assert listener._suite_depth == 1
        assert listener._start_time is not None
        assert listener._test_cases == []
        assert listener._errors == []

    def test_nested_suite_increments_depth(self) -> None:
        listener = DryRunListener()
        listener.start_suite(_mock_suite_data("TopLevel"), _mock_suite_result())
        listener.start_suite(_mock_suite_data("Child"), _mock_suite_result())
        assert listener._suite_depth == 2

    def test_nested_suite_does_not_reset_state(self) -> None:
        listener = DryRunListener()
        listener.start_suite(_mock_suite_data("TopLevel"), _mock_suite_result())
        listener._test_cases.append({"name": "existing", "status": "PASS"})
        listener.start_suite(_mock_suite_data("Child"), _mock_suite_result())
        assert len(listener._test_cases) == 1


class TestDryRunListenerEndTest:
    def test_end_test_pass(self) -> None:
        listener = DryRunListener()
        listener.end_test(_mock_test_data("Test One"), _mock_test_result("PASS"))
        assert len(listener._test_cases) == 1
        assert listener._test_cases[0] == {"name": "Test One", "status": "PASS"}
        assert listener._errors == []

    def test_end_test_fail_records_error(self) -> None:
        listener = DryRunListener()
        listener.end_test(
            _mock_test_data("Test Two"),
            _mock_test_result("FAIL", "No keyword found"),
        )
        assert len(listener._test_cases) == 1
        assert listener._test_cases[0]["status"] == "FAIL"
        assert len(listener._errors) == 1
        assert "Test Two: No keyword found" in listener._errors[0]

    def test_end_test_fail_no_message(self) -> None:
        listener = DryRunListener()
        listener.end_test(_mock_test_data("Test Three"), _mock_test_result("FAIL", ""))
        assert listener._errors == []


class TestDryRunListenerEndSuite:
    @patch("rfc.dry_run_listener.logger")
    def test_end_suite_logs_at_top_level(self, mock_logger: MagicMock) -> None:
        listener = DryRunListener()
        suite_data = _mock_suite_data("Top")
        suite_result = _mock_suite_result(total=2)
        listener.start_suite(suite_data, suite_result)
        listener.end_test(_mock_test_data("T1"), _mock_test_result("PASS"))
        listener.end_test(_mock_test_data("T2"), _mock_test_result("FAIL", "error msg"))
        listener.end_suite(suite_data, suite_result)

        mock_logger.console.assert_called()
        console_calls = [str(call) for call in mock_logger.console.call_args_list]
        full_output = " ".join(console_calls)
        assert "2 tests" in full_output
        assert "1 passed" in full_output
        assert "1 failed" in full_output

    def test_nested_end_suite_does_not_log(self) -> None:
        listener = DryRunListener()
        listener.start_suite(_mock_suite_data("Top"), _mock_suite_result())
        listener.start_suite(_mock_suite_data("Child"), _mock_suite_result())
        # Should not error - just decrements depth
        listener.end_suite(_mock_suite_data("Child"), _mock_suite_result())
        assert listener._suite_depth == 1

    @patch("rfc.dry_run_listener.logger")
    def test_end_suite_warns_on_errors(self, mock_logger: MagicMock) -> None:
        listener = DryRunListener()
        suite_data = _mock_suite_data("Top")
        suite_result = _mock_suite_result(total=1)
        listener.start_suite(suite_data, suite_result)
        listener.end_test(
            _mock_test_data("T1"),
            _mock_test_result("FAIL", "keyword not found"),
        )
        listener.end_suite(suite_data, suite_result)

        mock_logger.warn.assert_called()
