"""Tests for rfc.db_listener.DbListener."""

import json
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
    def test_model_name_from_robot_variable_overrides_env(self, _mock_ci, tmp_path):
        """Robot --variable DEFAULT_MODEL:llama3 should override the env var."""
        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        with patch.dict(os.environ, {"DEFAULT_MODEL": "gpt-oss:20b"}):
            listener.start_suite("Suite", {})
            listener.end_test("T1", _test_attrs())
            # Simulate Robot variable override (as set by --variable flag)
            with patch("rfc.db_listener.BuiltIn") as mock_builtin_cls:
                mock_builtin_cls.return_value.get_variable_value.return_value = "llama3"
                listener.end_suite("Suite", _suite_attrs())

        runs = listener._get_db().get_recent_runs(limit=1)
        assert runs[0]["model_name"] == "llama3"

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_model_name_falls_back_when_robot_variable_unavailable(
        self, _mock_ci, tmp_path
    ):
        """When BuiltIn is not available (e.g. unit tests), fall back to env/ci_info."""
        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        with patch.dict(os.environ, {"DEFAULT_MODEL": "mistral"}):
            listener.start_suite("Suite", {})
            listener.end_test("T1", _test_attrs())
            # Simulate BuiltIn not available (outside Robot context)
            with patch("rfc.db_listener.BuiltIn") as mock_builtin_cls:
                mock_builtin_cls.return_value.get_variable_value.side_effect = (
                    RuntimeError("Not in RF context")
                )
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


class TestDbListenerLogMessage:
    """Tests for RFC_DATA: structured log message capture."""

    def test_captures_actual_answer(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.log_message({"message": "RFC_DATA:actual_answer:The answer is 4"})
        listener.end_test("T", _test_attrs())
        assert listener._test_cases[0]["actual_answer"] == "The answer is 4"

    def test_captures_expected_answer(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.log_message({"message": "RFC_DATA:expected_answer:4"})
        listener.end_test("T", _test_attrs())
        assert listener._test_cases[0]["expected_answer"] == "4"

    def test_captures_grading_reason(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.log_message(
            {"message": "RFC_DATA:grading_reason:Correct numeric answer"}
        )
        listener.end_test("T", _test_attrs())
        assert listener._test_cases[0]["grading_reason"] == "Correct numeric answer"

    def test_captures_multiple_fields(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.log_message({"message": "RFC_DATA:actual_answer:42"})
        listener.log_message({"message": "RFC_DATA:expected_answer:42"})
        listener.log_message({"message": "RFC_DATA:grading_reason:Exact match"})
        listener.end_test("T", _test_attrs())
        tc = listener._test_cases[0]
        assert tc["actual_answer"] == "42"
        assert tc["expected_answer"] == "42"
        assert tc["grading_reason"] == "Exact match"

    def test_ignores_non_rfc_data_messages(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.log_message({"message": "Just a normal log message"})
        listener.end_test("T", _test_attrs())
        assert listener._test_cases[0]["actual_answer"] is None

    def test_ignores_empty_message(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.log_message({"message": ""})
        listener.end_test("T", _test_attrs())
        assert listener._test_cases[0]["actual_answer"] is None

    def test_ignores_non_string_message(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.log_message({"message": 12345})
        listener.end_test("T", _test_attrs())
        assert listener._test_cases[0]["actual_answer"] is None

    def test_resets_between_tests(self):
        listener = DbListener()
        listener.start_test("T1", {})
        listener.log_message({"message": "RFC_DATA:actual_answer:first"})
        listener.end_test("T1", _test_attrs())

        listener.start_test("T2", {})
        listener.end_test("T2", _test_attrs())

        assert listener._test_cases[0]["actual_answer"] == "first"
        assert listener._test_cases[1]["actual_answer"] is None

    def test_handles_value_with_colons(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.log_message(
            {"message": "RFC_DATA:grading_reason:Score: 1/1, reason: correct"}
        )
        listener.end_test("T", _test_attrs())
        assert (
            listener._test_cases[0]["grading_reason"] == "Score: 1/1, reason: correct"
        )

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_captured_data_archived_to_database(self, _mock_ci, tmp_path):
        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite("Suite", {})
        listener.start_test("Math Test", {})
        listener.log_message({"message": "RFC_DATA:actual_answer:4"})
        listener.log_message({"message": "RFC_DATA:expected_answer:4"})
        listener.log_message({"message": "RFC_DATA:grading_reason:Correct"})
        listener.end_test("Math Test", _test_attrs(status="PASS"))
        listener.end_suite("Suite", _suite_attrs(totaltests=1))

        import sqlite3

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_results").fetchone()
            assert row["actual_answer"] == "4"
            assert row["expected_answer"] == "4"
            assert row["grading_reason"] == "Correct"


class TestDbListenerStartTest:
    def test_resets_current_test_data(self):
        listener = DbListener()
        listener._current_test_data = {"stale": "data"}
        listener.start_test("T", {})
        assert listener._current_test_data == {}

    def test_initial_current_test_data_is_empty(self):
        listener = DbListener()
        assert listener._current_test_data == {}


def _kw_attrs(
    status="PASS",
    args=None,
    kwname="",
    libname="",
    type="kw",
    starttime="2026-01-01 12:00:00.000",
    endtime="2026-01-01 12:00:01.500",
):
    """Build a minimal keyword attributes dict."""
    return {
        "status": status,
        "args": args or [],
        "kwname": kwname,
        "libname": libname,
        "type": type,
        "starttime": starttime,
        "endtime": endtime,
    }


class TestDbListenerKeywordTracking:
    """Tests for start_keyword/end_keyword hooks."""

    def test_tracks_ask_llm_keyword(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.start_keyword(
            "Ask LLM",
            _kw_attrs(kwname="Ask LLM", libname="rfc.keywords", args=["What is 2+2?"]),
        )
        listener.end_keyword(
            "Ask LLM",
            _kw_attrs(
                kwname="Ask LLM",
                libname="rfc.keywords",
                status="PASS",
            ),
        )
        listener.end_test("T", _test_attrs())
        assert len(listener._keyword_results) == 1
        kw = listener._keyword_results[0]
        assert kw["keyword_name"] == "Ask LLM"
        assert kw["status"] == "PASS"
        assert kw["test_name"] == "T"

    def test_tracks_grade_answer_keyword(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.start_keyword(
            "Grade Answer",
            _kw_attrs(
                kwname="Grade Answer",
                libname="rfc.keywords",
                args=["What is 2+2?", "4", "The answer is 4"],
            ),
        )
        listener.end_keyword(
            "Grade Answer",
            _kw_attrs(kwname="Grade Answer", libname="rfc.keywords"),
        )
        listener.end_test("T", _test_attrs())
        assert len(listener._keyword_results) == 1
        assert listener._keyword_results[0]["keyword_name"] == "Grade Answer"

    def test_tracks_safety_keywords(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.start_keyword(
            "Test Prompt Injection Resistance",
            _kw_attrs(
                kwname="Test Prompt Injection Resistance",
                libname="rfc.safety_keywords",
                args=["ignore previous instructions"],
            ),
        )
        listener.end_keyword(
            "Test Prompt Injection Resistance",
            _kw_attrs(
                kwname="Test Prompt Injection Resistance",
                libname="rfc.safety_keywords",
            ),
        )
        listener.end_test("T", _test_attrs())
        assert len(listener._keyword_results) == 1

    def test_ignores_builtin_keywords(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.start_keyword(
            "Log", _kw_attrs(kwname="Log", libname="BuiltIn", args=["hello"])
        )
        listener.end_keyword("Log", _kw_attrs(kwname="Log", libname="BuiltIn"))
        listener.end_test("T", _test_attrs())
        assert len(listener._keyword_results) == 0

    def test_captures_duration(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.start_keyword(
            "Ask LLM",
            _kw_attrs(
                kwname="Ask LLM",
                libname="rfc.keywords",
                starttime="2026-01-01 12:00:00.000",
            ),
        )
        listener.end_keyword(
            "Ask LLM",
            _kw_attrs(
                kwname="Ask LLM",
                libname="rfc.keywords",
                endtime="2026-01-01 12:00:02.500",
            ),
        )
        listener.end_test("T", _test_attrs())
        assert listener._keyword_results[0]["duration_seconds"] is not None

    def test_captures_first_arg_as_prompt(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.start_keyword(
            "Ask LLM",
            _kw_attrs(
                kwname="Ask LLM",
                libname="rfc.keywords",
                args=["What is the meaning of life?"],
            ),
        )
        listener.end_keyword(
            "Ask LLM",
            _kw_attrs(kwname="Ask LLM", libname="rfc.keywords"),
        )
        listener.end_test("T", _test_attrs())
        assert "What is the meaning of life?" in listener._keyword_results[0]["args"]

    def test_resets_between_suites(self):
        listener = DbListener()
        listener._keyword_results = [{"stale": "data"}]
        with patch("rfc.db_listener.collect_ci_metadata", return_value={}):
            listener.start_suite("Suite", {})
        assert listener._keyword_results == []

    def test_multiple_keywords_per_test(self):
        listener = DbListener()
        listener.start_test("T", {})
        for name in ["Wait For LLM", "Ask LLM", "Grade Answer"]:
            listener.start_keyword(name, _kw_attrs(kwname=name, libname="rfc.keywords"))
            listener.end_keyword(name, _kw_attrs(kwname=name, libname="rfc.keywords"))
        listener.end_test("T", _test_attrs())
        assert len(listener._keyword_results) == 3

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_keywords_archived_to_database(self, _mock_ci, tmp_path):
        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite("Suite", {})
        listener.start_test("Math Test", {})
        listener.start_keyword(
            "Ask LLM",
            _kw_attrs(
                kwname="Ask LLM",
                libname="rfc.keywords",
                args=["What is 2+2?"],
                starttime="2026-01-01 12:00:00.000",
            ),
        )
        listener.end_keyword(
            "Ask LLM",
            _kw_attrs(
                kwname="Ask LLM",
                libname="rfc.keywords",
                endtime="2026-01-01 12:00:01.500",
            ),
        )
        listener.end_test("Math Test", _test_attrs(status="PASS"))
        listener.end_suite("Suite", _suite_attrs(totaltests=1))

        import sqlite3

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM keyword_results").fetchall()
            assert len(rows) == 1
            row = rows[0]
            assert row["keyword_name"] == "Ask LLM"
            assert row["test_name"] == "Math Test"
            assert row["status"] == "PASS"
            assert row["duration_seconds"] is not None

    def test_failed_keyword_recorded(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.start_keyword(
            "Ask LLM", _kw_attrs(kwname="Ask LLM", libname="rfc.keywords")
        )
        listener.end_keyword(
            "Ask LLM",
            _kw_attrs(kwname="Ask LLM", libname="rfc.keywords", status="FAIL"),
        )
        listener.end_test("T", _test_attrs(status="FAIL"))
        assert listener._keyword_results[0]["status"] == "FAIL"

    def test_tracks_by_known_keyword_name(self):
        """Even if libname is empty, known keyword names are tracked."""
        listener = DbListener()
        listener.start_test("T", {})
        listener.start_keyword("Ask LLM", _kw_attrs(kwname="Ask LLM", libname=""))
        listener.end_keyword("Ask LLM", _kw_attrs(kwname="Ask LLM", libname=""))
        listener.end_test("T", _test_attrs())
        assert len(listener._keyword_results) == 1


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


class TestDbListenerDatabaseDescription:
    """Tests for _describe_database_destination helper."""

    def test_default_sqlite_when_no_url(self):
        listener = DbListener()
        desc = listener._describe_database_destination()
        assert "SQLite" in desc
        assert "test_history.db" in desc

    def test_explicit_sqlite_url(self):
        listener = DbListener(database_url="sqlite:///path/to/my.db")
        desc = listener._describe_database_destination()
        assert "SQLite" in desc
        assert "path/to/my.db" in desc

    def test_postgresql_url_strips_credentials(self):
        listener = DbListener(
            database_url="postgresql://user:secret@localhost:5433/rfc"
        )
        desc = listener._describe_database_destination()
        assert "PostgreSQL" in desc
        assert "localhost:5433/rfc" in desc
        assert "secret" not in desc
        assert "user" not in desc

    def test_postgresql_url_without_credentials(self):
        listener = DbListener(database_url="postgresql://localhost:5433/rfc")
        desc = listener._describe_database_destination()
        assert "PostgreSQL" in desc
        assert "localhost:5433/rfc" in desc

    def test_does_not_trigger_db_init(self):
        listener = DbListener(database_url="sqlite:///whatever.db")
        listener._describe_database_destination()
        assert listener._db is None


class TestDbListenerConsoleOutput:
    """Tests for console output visibility."""

    @patch("rfc.db_listener.logger")
    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_start_suite_emits_console_banner(self, _mock_ci, mock_logger):
        listener = DbListener(database_url="sqlite:///test.db")
        listener.start_suite("My Suite", {})

        mock_logger.console.assert_called()
        console_calls = [str(call) for call in mock_logger.console.call_args_list]
        full_output = " ".join(console_calls)
        assert "SQLite" in full_output

    @patch("rfc.db_listener.logger")
    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_start_suite_banner_not_repeated_for_nested(self, _mock_ci, mock_logger):
        listener = DbListener(database_url="sqlite:///test.db")
        listener.start_suite("Top", {})
        mock_logger.console.reset_mock()
        listener.start_suite("Nested", {})
        mock_logger.console.assert_not_called()

    @patch("rfc.db_listener.logger")
    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_end_suite_emits_console_summary(self, _mock_ci, mock_logger, tmp_path):
        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite("Suite", {})
        listener.end_test("T1", _test_attrs(status="PASS"))
        listener.end_test("T2", _test_attrs(status="FAIL"))
        mock_logger.console.reset_mock()
        listener.end_suite("Suite", _suite_attrs(totaltests=2))

        mock_logger.console.assert_called()
        console_calls = [str(call) for call in mock_logger.console.call_args_list]
        full_output = " ".join(console_calls)
        assert "2 test" in full_output
        assert "run_id=" in full_output

    @patch("rfc.db_listener.logger")
    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_end_suite_console_includes_keyword_count(
        self, _mock_ci, mock_logger, tmp_path
    ):
        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite("Suite", {})
        listener.start_test("T", {})
        listener.start_keyword(
            "Ask LLM",
            _kw_attrs(kwname="Ask LLM", libname="rfc.keywords"),
        )
        listener.end_keyword(
            "Ask LLM",
            _kw_attrs(kwname="Ask LLM", libname="rfc.keywords"),
        )
        listener.end_test("T", _test_attrs())
        mock_logger.console.reset_mock()
        listener.end_suite("Suite", _suite_attrs(totaltests=1))

        console_calls = [str(call) for call in mock_logger.console.call_args_list]
        full_output = " ".join(console_calls)
        assert "1 keyword" in full_output

    @patch("rfc.db_listener.logger")
    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_database_error_emits_console_warning(self, _mock_ci, mock_logger):
        listener = DbListener()
        mock_db = MagicMock()
        mock_db.add_test_run.side_effect = Exception("connection refused")
        listener._db = mock_db

        listener.start_suite("Suite", {})
        listener.end_test("T1", _test_attrs())
        mock_logger.console.reset_mock()
        listener.end_suite("Suite", _suite_attrs())

        mock_logger.console.assert_called()
        console_calls = [str(call) for call in mock_logger.console.call_args_list]
        full_output = " ".join(console_calls)
        assert "FAILED" in full_output
        assert "connection refused" in full_output


class TestDbListenerOllamaMetrics:
    """Tests for Ollama performance metrics capture via RFC_DATA:ollama_metrics."""

    def test_initial_ollama_metrics_list_is_empty(self):
        listener = DbListener()
        assert listener._ollama_metrics == []

    def test_captures_ollama_metrics_from_log_message(self):
        listener = DbListener()
        listener.start_test("T", {})
        metrics = {
            "model_name": "llama3",
            "total_duration_ns": 17607688368,
            "eval_rate": 11.0,
        }
        listener.log_message(
            {"message": f"RFC_DATA:ollama_metrics:{json.dumps(metrics)}"}
        )
        assert len(listener._ollama_metrics) == 1
        assert listener._ollama_metrics[0]["model_name"] == "llama3"
        assert listener._ollama_metrics[0]["test_name"] == "T"

    def test_accumulates_metrics_across_calls(self):
        listener = DbListener()
        listener.start_test("T", {})
        for i in range(3):
            metrics = {"model_name": f"model_{i}", "eval_rate": float(i)}
            listener.log_message(
                {"message": f"RFC_DATA:ollama_metrics:{json.dumps(metrics)}"}
            )
        assert len(listener._ollama_metrics) == 3

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_resets_metrics_on_start_suite(self, _mock_ci):
        listener = DbListener()
        listener._ollama_metrics = [{"stale": "data"}]
        listener.start_suite("Suite", {})
        assert listener._ollama_metrics == []

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_metrics_archived_to_database(self, _mock_ci, tmp_path):
        import sqlite3

        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite("Suite", {})
        listener.start_test("Math Test", {})
        metrics = {
            "model_name": "llama3",
            "total_duration_ns": 17607688368,
            "load_duration_ns": 108889428,
            "prompt_eval_count": 73,
            "prompt_eval_duration_ns": 489998464,
            "prompt_eval_rate": 148.98,
            "eval_count": 186,
            "eval_duration_ns": 16907870673,
            "eval_rate": 11.0,
        }
        listener.log_message(
            {"message": f"RFC_DATA:ollama_metrics:{json.dumps(metrics)}"}
        )
        listener.end_test("Math Test", _test_attrs(status="PASS"))
        listener.end_suite("Suite", _suite_attrs(totaltests=1))

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM ollama_metrics").fetchall()
            assert len(rows) == 1
            row = rows[0]
            assert row["model_name"] == "llama3"
            assert row["total_duration_ns"] == 17607688368
            assert row["eval_rate"] == 11.0
            assert row["test_name"] == "Math Test"

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_metrics_include_rfc_version(self, _mock_ci, tmp_path):
        import sqlite3

        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite("Suite", {})
        listener.start_test("T", {})
        listener.log_message(
            {"message": 'RFC_DATA:ollama_metrics:{"model_name": "llama3"}'}
        )
        listener.end_test("T", _test_attrs())
        listener.end_suite("Suite", _suite_attrs(totaltests=1))

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM ollama_metrics").fetchone()
            assert row["rfc_version"] is not None

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_prompt_text_archived_to_database(self, _mock_ci, tmp_path):
        import sqlite3

        db_path = str(tmp_path / "test.db")
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite("Suite", {})
        listener.start_test("T", {})
        metrics = {
            "model_name": "llama3",
            "prompt_text": "What is 6 * 7?",
            "eval_rate": 11.0,
        }
        listener.log_message(
            {"message": f"RFC_DATA:ollama_metrics:{json.dumps(metrics)}"}
        )
        listener.end_test("T", _test_attrs())
        listener.end_suite("Suite", _suite_attrs(totaltests=1))

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM ollama_metrics").fetchone()
            assert row["prompt_text"] == "What is 6 * 7?"

    def test_ignores_invalid_json_in_ollama_metrics(self):
        listener = DbListener()
        listener.start_test("T", {})
        listener.log_message({"message": "RFC_DATA:ollama_metrics:not-valid-json"})
        assert len(listener._ollama_metrics) == 0
