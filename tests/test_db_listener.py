"""Tests for rfc.db_listener.DbListener."""

import os
from unittest.mock import MagicMock, patch

from rfc.db_listener import DbListener


def _suite_attrs(**overrides):
    """Build a minimal suite-end attributes dict."""
    defaults = {
        "totaltests": 3,
        "metadata": {},
    }
    defaults.update(overrides)
    return defaults


def _test_attrs(status="PASS", tags=None, doc="", message=""):
    """Build a minimal test-end attributes dict."""
    return {
        "status": status,
        "tags": tags or [],
        "doc": doc,
        "message": message,
    }


class TestDbListenerInit:
    def test_robot_listener_api_version(self):
        listener = DbListener()
        assert listener.ROBOT_LISTENER_API_VERSION == 2

    def test_initial_state(self):
        listener = DbListener()
        assert listener._db is None
        assert listener._start_time is None
        assert listener._ci_info == {}
        assert listener._test_cases == []
        assert listener._suite_depth == 0

    def test_database_url_from_constructor(self):
        listener = DbListener(database_url="sqlite:///test.db")
        assert listener._database_url == "sqlite:///test.db"

    def test_database_url_from_env(self):
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///env.db"}):
            listener = DbListener()
        assert listener._database_url == "sqlite:///env.db"

    def test_constructor_overrides_env(self):
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///env.db"}):
            listener = DbListener(database_url="sqlite:///explicit.db")
        assert listener._database_url == "sqlite:///explicit.db"


class TestDbListenerSuiteDepth:
    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_start_suite_increments_depth(self, _mock_ci):
        listener = DbListener()
        listener.start_suite("Top", {})
        assert listener._suite_depth == 1
        listener.start_suite("Nested", {})
        assert listener._suite_depth == 2

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_start_suite_only_initialises_at_top_level(self, _mock_ci):
        listener = DbListener()
        listener.start_suite("Top", {})
        first_start_time = listener._start_time
        assert first_start_time is not None

        # Nested suite should NOT reset start time
        listener.start_suite("Nested", {})
        assert listener._start_time is first_start_time

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_end_suite_decrements_depth(self, _mock_ci):
        listener = DbListener()
        listener.start_suite("Top", {})
        listener.start_suite("Nested", {})
        listener.end_suite("Nested", _suite_attrs())
        assert listener._suite_depth == 1

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_nested_end_suite_does_not_archive(self, _mock_ci):
        listener = DbListener()
        mock_db = MagicMock()
        listener._db = mock_db

        listener.start_suite("Top", {})
        listener.start_suite("Nested", {})
        listener.end_suite("Nested", _suite_attrs())

        mock_db.add_test_run.assert_not_called()


class TestDbListenerEndTest:
    def test_records_test_case(self):
        listener = DbListener()
        listener.end_test("Test One", _test_attrs(status="PASS"))
        assert len(listener._test_cases) == 1
        assert listener._test_cases[0]["name"] == "Test One"
        assert listener._test_cases[0]["status"] == "PASS"

    def test_extracts_score_from_tags(self):
        listener = DbListener()
        listener.end_test("Test One", _test_attrs(tags=["IQ:100", "score:1"]))
        assert listener._test_cases[0]["score"] == 1

    def test_score_none_when_no_score_tag(self):
        listener = DbListener()
        listener.end_test("Test One", _test_attrs(tags=["IQ:100"]))
        assert listener._test_cases[0]["score"] is None

    def test_score_none_for_invalid_score_tag(self):
        listener = DbListener()
        listener.end_test("Test One", _test_attrs(tags=["score:abc"]))
        assert listener._test_cases[0]["score"] is None

    def test_score_none_for_malformed_score_tag(self):
        listener = DbListener()
        listener.end_test("Test One", _test_attrs(tags=["score:"]))
        assert listener._test_cases[0]["score"] is None

    def test_uses_doc_as_question(self):
        listener = DbListener()
        listener.end_test("T", _test_attrs(doc="What is 2+2?"))
        assert listener._test_cases[0]["question"] == "What is 2+2?"

    def test_empty_doc_becomes_none(self):
        listener = DbListener()
        listener.end_test("T", _test_attrs(doc=""))
        assert listener._test_cases[0]["question"] is None

    def test_message_recorded(self):
        listener = DbListener()
        listener.end_test("T", _test_attrs(message="Assertion failed"))
        assert listener._test_cases[0]["message"] == "Assertion failed"

    def test_multiple_tests_recorded(self):
        listener = DbListener()
        for i in range(5):
            listener.end_test(f"Test {i}", _test_attrs())
        assert len(listener._test_cases) == 5


class TestDbListenerEndSuiteArchival:
    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_archives_to_database(self, _mock_ci, tmp_path):
        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite("My Suite", {})
        listener.end_test("Test A", _test_attrs(status="PASS"))
        listener.end_test("Test B", _test_attrs(status="FAIL"))
        listener.end_suite("My Suite", _suite_attrs(totaltests=2))

        # Verify records were written
        db = listener._get_db()
        runs = db.get_recent_runs(limit=1)
        assert len(runs) == 1
        assert runs[0]["test_suite"] == "My Suite"
        assert runs[0]["passed"] == 1
        assert runs[0]["failed"] == 1

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_counts_pass_fail_skip(self, _mock_ci, tmp_path):
        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite("Suite", {})
        listener.end_test("T1", _test_attrs(status="PASS"))
        listener.end_test("T2", _test_attrs(status="PASS"))
        listener.end_test("T3", _test_attrs(status="FAIL"))
        listener.end_test("T4", _test_attrs(status="SKIP"))
        listener.end_suite("Suite", _suite_attrs(totaltests=4))

        runs = listener._get_db().get_recent_runs(limit=1)
        assert runs[0]["passed"] == 2
        assert runs[0]["failed"] == 1
        assert runs[0]["skipped"] == 1
        assert runs[0]["total_tests"] == 4

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_total_tests_falls_back_to_test_case_count(self, _mock_ci, tmp_path):
        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite("Suite", {})
        listener.end_test("T1", _test_attrs(status="PASS"))
        listener.end_test("T2", _test_attrs(status="PASS"))
        listener.end_suite("Suite", _suite_attrs(totaltests=0))

        runs = listener._get_db().get_recent_runs(limit=1)
        assert runs[0]["total_tests"] == 2

    @patch("rfc.db_listener.collect_ci_metadata", return_value={"Commit_SHA": "abc"})
    def test_ci_metadata_included_in_run(self, _mock_ci, tmp_path):
        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite("Suite", {})
        listener.end_test("T1", _test_attrs())
        listener.end_suite("Suite", _suite_attrs())

        runs = listener._get_db().get_recent_runs(limit=1)
        assert runs[0]["git_commit"] == "abc"

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_rfc_version_recorded(self, _mock_ci, tmp_path):
        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite("Suite", {})
        listener.end_test("T1", _test_attrs())
        listener.end_suite("Suite", _suite_attrs())

        runs = listener._get_db().get_recent_runs(limit=1)
        assert runs[0]["rfc_version"] is not None

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_model_name_from_env(self, _mock_ci, tmp_path):
        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        with patch.dict(os.environ, {"DEFAULT_MODEL": "mistral"}):
            listener.start_suite("Suite", {})
            listener.end_test("T1", _test_attrs())
            listener.end_suite("Suite", _suite_attrs())

        runs = listener._get_db().get_recent_runs(limit=1)
        assert runs[0]["model_name"] == "mistral"

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_database_error_does_not_raise(self, _mock_ci):
        listener = DbListener()
        mock_db = MagicMock()
        mock_db.add_test_run.side_effect = Exception("db error")
        listener._db = mock_db

        listener.start_suite("Suite", {})
        listener.end_test("T1", _test_attrs())
        # Should not raise — errors are logged and swallowed
        listener.end_suite("Suite", _suite_attrs())


class TestDbListenerGetDb:
    def test_lazy_creates_database(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")
        assert listener._db is None
        db = listener._get_db()
        assert db is not None
        assert listener._db is db

    def test_reuses_existing_database(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")
        db1 = listener._get_db()
        db2 = listener._get_db()
        assert db1 is db2
