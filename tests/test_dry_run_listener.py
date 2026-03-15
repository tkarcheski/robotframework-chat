"""Tests for rfc.dry_run_listener.DryRunListener."""

from unittest.mock import MagicMock, patch

from rfc.dry_run_listener import DryRunListener


def _suite_attrs(**overrides: object) -> dict:
    defaults: dict = {"totaltests": 3, "metadata": {}}
    defaults.update(overrides)
    return defaults


def _test_attrs(status: str = "PASS", message: str = "") -> dict:
    return {"status": status, "message": message}


class TestDryRunListenerInit:
    def test_api_version(self) -> None:
        listener = DryRunListener()
        assert listener.ROBOT_LISTENER_API_VERSION == 2

    def test_initial_state(self) -> None:
        listener = DryRunListener()
        assert listener._start_time is None
        assert listener._test_cases == []
        assert listener._errors == []
        assert listener._suite_depth == 0


class TestDryRunListenerStartSuite:
    def test_start_suite_initializes_state(self) -> None:
        listener = DryRunListener()
        listener.start_suite("TopLevel", _suite_attrs())
        assert listener._suite_depth == 1
        assert listener._start_time is not None
        assert listener._test_cases == []
        assert listener._errors == []

    def test_nested_suite_increments_depth(self) -> None:
        listener = DryRunListener()
        listener.start_suite("TopLevel", _suite_attrs())
        listener.start_suite("Child", _suite_attrs())
        assert listener._suite_depth == 2

    def test_nested_suite_does_not_reset_state(self) -> None:
        listener = DryRunListener()
        listener.start_suite("TopLevel", _suite_attrs())
        listener._test_cases.append({"name": "existing", "status": "PASS"})
        listener.start_suite("Child", _suite_attrs())
        assert len(listener._test_cases) == 1


class TestDryRunListenerEndTest:
    def test_end_test_pass(self) -> None:
        listener = DryRunListener()
        listener.end_test("Test One", _test_attrs("PASS"))
        assert len(listener._test_cases) == 1
        assert listener._test_cases[0] == {"name": "Test One", "status": "PASS"}
        assert listener._errors == []

    def test_end_test_fail_records_error(self) -> None:
        listener = DryRunListener()
        listener.end_test("Test Two", _test_attrs("FAIL", "No keyword found"))
        assert len(listener._test_cases) == 1
        assert listener._test_cases[0]["status"] == "FAIL"
        assert len(listener._errors) == 1
        assert "Test Two: No keyword found" in listener._errors[0]

    def test_end_test_fail_no_message(self) -> None:
        listener = DryRunListener()
        listener.end_test("Test Three", _test_attrs("FAIL", ""))
        assert listener._errors == []


class TestDryRunListenerEndSuite:
    @patch("rfc.dry_run_listener.logger")
    def test_end_suite_logs_at_top_level(self, mock_logger: MagicMock) -> None:
        listener = DryRunListener()
        listener.start_suite("Top", _suite_attrs(totaltests=2))
        listener.end_test("T1", _test_attrs("PASS"))
        listener.end_test("T2", _test_attrs("FAIL", "error msg"))
        listener.end_suite("Top", _suite_attrs(totaltests=2))

        mock_logger.console.assert_called()
        console_calls = [str(call) for call in mock_logger.console.call_args_list]
        full_output = " ".join(console_calls)
        assert "2 tests" in full_output
        assert "1 passed" in full_output
        assert "1 failed" in full_output

    def test_nested_end_suite_does_not_log(self) -> None:
        listener = DryRunListener()
        listener.start_suite("Top", _suite_attrs())
        listener.start_suite("Child", _suite_attrs())
        # Should not error - just decrements depth
        listener.end_suite("Child", _suite_attrs())
        assert listener._suite_depth == 1

    @patch("rfc.dry_run_listener.logger")
    def test_end_suite_warns_on_errors(self, mock_logger: MagicMock) -> None:
        listener = DryRunListener()
        listener.start_suite("Top", _suite_attrs())
        listener.end_test("T1", _test_attrs("FAIL", "keyword not found"))
        listener.end_suite("Top", _suite_attrs(totaltests=1))

        mock_logger.warn.assert_called()
