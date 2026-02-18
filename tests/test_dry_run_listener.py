"""Tests for rfc.dry_run_listener.DryRunListener."""

from unittest.mock import MagicMock, patch

from rfc.dry_run_listener import DryRunListener


def _suite_attrs(**overrides):
    defaults = {"totaltests": 3, "metadata": {}}
    defaults.update(overrides)
    return defaults


def _test_attrs(status="PASS", message=""):
    return {"status": status, "message": message}


class TestDryRunListenerInit:
    def test_api_version(self):
        listener = DryRunListener()
        assert listener.ROBOT_LISTENER_API_VERSION == 2

    def test_initial_state(self):
        listener = DryRunListener()
        assert listener._db is None
        assert listener._start_time is None
        assert listener._ci_info == {}
        assert listener._test_cases == []
        assert listener._errors == []
        assert listener._suite_depth == 0

    def test_database_url_from_constructor(self):
        listener = DryRunListener(database_url="sqlite:///test.db")
        assert listener._database_url == "sqlite:///test.db"

    @patch.dict("os.environ", {"DATABASE_URL": "sqlite:///env.db"})
    def test_database_url_from_env(self):
        listener = DryRunListener()
        assert listener._database_url == "sqlite:///env.db"


class TestDryRunListenerStartSuite:
    @patch("rfc.dry_run_listener.collect_ci_metadata", return_value={"Branch": "main"})
    def test_start_suite_initializes_state(self, mock_ci):
        listener = DryRunListener()
        listener.start_suite("TopLevel", _suite_attrs())
        assert listener._suite_depth == 1
        assert listener._start_time is not None
        assert listener._ci_info == {"Branch": "main"}
        assert listener._test_cases == []
        assert listener._errors == []

    @patch("rfc.dry_run_listener.collect_ci_metadata", return_value={})
    def test_nested_suite_increments_depth(self, mock_ci):
        listener = DryRunListener()
        listener.start_suite("TopLevel", _suite_attrs())
        listener.start_suite("Child", _suite_attrs())
        assert listener._suite_depth == 2

    @patch("rfc.dry_run_listener.collect_ci_metadata", return_value={})
    def test_nested_suite_does_not_reset_state(self, mock_ci):
        listener = DryRunListener()
        listener.start_suite("TopLevel", _suite_attrs())
        listener._test_cases.append({"name": "existing", "status": "PASS"})
        listener.start_suite("Child", _suite_attrs())
        assert len(listener._test_cases) == 1


class TestDryRunListenerEndTest:
    def test_end_test_pass(self):
        listener = DryRunListener()
        listener.end_test("Test One", _test_attrs("PASS"))
        assert len(listener._test_cases) == 1
        assert listener._test_cases[0] == {"name": "Test One", "status": "PASS"}
        assert listener._errors == []

    def test_end_test_fail_records_error(self):
        listener = DryRunListener()
        listener.end_test("Test Two", _test_attrs("FAIL", "No keyword found"))
        assert len(listener._test_cases) == 1
        assert listener._test_cases[0]["status"] == "FAIL"
        assert len(listener._errors) == 1
        assert "Test Two: No keyword found" in listener._errors[0]

    def test_end_test_fail_no_message(self):
        listener = DryRunListener()
        listener.end_test("Test Three", _test_attrs("FAIL", ""))
        assert listener._errors == []

    def test_end_test_skip(self):
        listener = DryRunListener()
        listener.end_test("Test Skip", _test_attrs("SKIP"))
        assert listener._test_cases[0]["status"] == "SKIP"


class TestDryRunListenerEndSuite:
    @patch(
        "rfc.dry_run_listener.collect_ci_metadata", return_value={"Commit_SHA": "abc"}
    )
    def test_end_suite_archives_at_top_level(self, mock_ci):
        listener = DryRunListener()
        mock_db = MagicMock()
        mock_db.add_dry_run_result.return_value = 42

        with patch.object(listener, "_get_db", return_value=mock_db):
            listener.start_suite("Top", _suite_attrs(totaltests=2))
            listener.end_test("T1", _test_attrs("PASS"))
            listener.end_test("T2", _test_attrs("FAIL", "error msg"))
            listener.end_suite("Top", _suite_attrs(totaltests=2))

        mock_db.add_dry_run_result.assert_called_once()
        result = mock_db.add_dry_run_result.call_args[0][0]
        assert result.test_suite == "Top"
        assert result.total_tests == 2
        assert result.passed == 1
        assert result.failed == 1
        assert result.git_commit == "abc"

    @patch("rfc.dry_run_listener.collect_ci_metadata", return_value={})
    def test_nested_end_suite_does_not_archive(self, mock_ci):
        listener = DryRunListener()
        mock_db = MagicMock()

        with patch.object(listener, "_get_db", return_value=mock_db):
            listener.start_suite("Top", _suite_attrs())
            listener.start_suite("Child", _suite_attrs())
            listener.end_suite("Child", _suite_attrs())

        mock_db.add_dry_run_result.assert_not_called()

    @patch("rfc.dry_run_listener.collect_ci_metadata", return_value={})
    def test_end_suite_handles_db_error_gracefully(self, mock_ci):
        listener = DryRunListener()
        mock_db = MagicMock()
        mock_db.add_dry_run_result.side_effect = Exception("db error")

        with patch.object(listener, "_get_db", return_value=mock_db):
            listener.start_suite("Top", _suite_attrs())
            listener.end_suite("Top", _suite_attrs())
            # Should not raise

    @patch("rfc.dry_run_listener.collect_ci_metadata", return_value={})
    def test_end_suite_skip_count(self, mock_ci):
        listener = DryRunListener()
        mock_db = MagicMock()
        mock_db.add_dry_run_result.return_value = 1

        with patch.object(listener, "_get_db", return_value=mock_db):
            listener.start_suite("Top", _suite_attrs(totaltests=3))
            listener.end_test("T1", _test_attrs("PASS"))
            listener.end_test("T2", _test_attrs("FAIL", "err"))
            listener.end_test("T3", _test_attrs("SKIP"))
            listener.end_suite("Top", _suite_attrs(totaltests=3))

        result = mock_db.add_dry_run_result.call_args[0][0]
        assert result.passed == 1
        assert result.failed == 1
        assert result.skipped == 1

    @patch("rfc.dry_run_listener.collect_ci_metadata", return_value={})
    def test_end_suite_uses_test_count_if_totaltests_zero(self, mock_ci):
        listener = DryRunListener()
        mock_db = MagicMock()
        mock_db.add_dry_run_result.return_value = 1

        with patch.object(listener, "_get_db", return_value=mock_db):
            listener.start_suite("Top", _suite_attrs(totaltests=0))
            listener.end_test("T1", _test_attrs("PASS"))
            listener.end_test("T2", _test_attrs("PASS"))
            listener.end_suite("Top", _suite_attrs(totaltests=0))

        result = mock_db.add_dry_run_result.call_args[0][0]
        assert result.total_tests == 2


class TestDryRunListenerGetDb:
    def test_get_db_with_url(self):
        listener = DryRunListener(database_url="sqlite:///test.db")
        with patch("rfc.dry_run_listener.TestDatabase") as MockDB:
            listener._get_db()
            MockDB.assert_called_once_with(database_url="sqlite:///test.db")

    def test_get_db_without_url(self):
        listener = DryRunListener()
        listener._database_url = None
        with patch("rfc.dry_run_listener.TestDatabase") as MockDB:
            listener._get_db()
            MockDB.assert_called_once_with()

    def test_get_db_returns_cached(self):
        listener = DryRunListener()
        mock_db = MagicMock()
        listener._db = mock_db
        assert listener._get_db() is mock_db
