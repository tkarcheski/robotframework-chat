"""Tests for rfc.db_listener.DbListener (Listener API v3, 2-table schema)."""

import os
import sqlite3
from unittest.mock import MagicMock, patch

from rfc.db_listener import (
    DbListener,
    _build_output_xml_url,
    _extract_llm_metrics,
    _format_size,
    _parse_tags,
    _safe_int,
)


def _mock_suite_data(name: str = "Suite") -> MagicMock:
    """Create a mock running.TestSuite (data) object."""
    data = MagicMock()
    data.name = name
    return data


def _mock_suite_result(total: int = 3) -> MagicMock:
    """Create a mock result.TestSuite (result) object."""
    result = MagicMock()
    result.statistics.total = total
    result.metadata = {}
    return result


def _mock_test_data(
    name: str = "Test", tags: list | None = None, doc: str = ""
) -> MagicMock:
    """Create a mock running.TestCase (data) object."""
    data = MagicMock()
    data.name = name
    data.tags = tags if tags is not None else []
    data.doc = doc
    return data


def _mock_test_result(status: str = "PASS", message: str = "") -> MagicMock:
    """Create a mock result.TestCase (result) object."""
    result = MagicMock()
    result.status = status
    result.message = message
    return result


def _mock_message(text: str) -> MagicMock:
    """Create a mock result.Message object."""
    msg = MagicMock()
    msg.message = text
    return msg


class TestDbListenerInit:
    def test_robot_listener_api_version(self) -> None:
        listener = DbListener()
        assert listener.ROBOT_LISTENER_API_VERSION == 3

    def test_initial_state(self) -> None:
        listener = DbListener()
        assert listener._db is None
        assert listener._start_time is None
        assert listener._ci_info == {}
        assert listener._test_cases == []
        assert listener._suite_depth == 0

    def test_database_url_from_constructor(self) -> None:
        listener = DbListener(database_url="sqlite:///test.db")
        assert listener._database_url == "sqlite:///test.db"

    def test_database_url_from_env(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///env.db"}):
            listener = DbListener()
        assert listener._database_url == "sqlite:///env.db"

    def test_constructor_overrides_env(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///env.db"}):
            listener = DbListener(database_url="sqlite:///explicit.db")
        assert listener._database_url == "sqlite:///explicit.db"


class TestDbListenerSuiteDepth:
    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_start_suite_increments_depth(self, _mock_ci: MagicMock) -> None:
        listener = DbListener()
        listener.start_suite(_mock_suite_data("Top"), _mock_suite_result())
        assert listener._suite_depth == 1
        listener.start_suite(_mock_suite_data("Nested"), _mock_suite_result())
        assert listener._suite_depth == 2

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_start_suite_only_initialises_at_top_level(
        self, _mock_ci: MagicMock
    ) -> None:
        listener = DbListener()
        listener.start_suite(_mock_suite_data("Top"), _mock_suite_result())
        first_start_time = listener._start_time
        assert first_start_time is not None

        listener.start_suite(_mock_suite_data("Nested"), _mock_suite_result())
        assert listener._start_time is first_start_time

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_end_suite_decrements_depth(self, _mock_ci: MagicMock) -> None:
        listener = DbListener()
        listener.start_suite(_mock_suite_data("Top"), _mock_suite_result())
        listener.start_suite(_mock_suite_data("Nested"), _mock_suite_result())
        listener.end_suite(_mock_suite_data("Nested"), _mock_suite_result())
        assert listener._suite_depth == 1

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_nested_end_suite_does_not_archive(self, _mock_ci: MagicMock) -> None:
        listener = DbListener()
        mock_db = MagicMock()
        listener._db = mock_db

        listener.start_suite(_mock_suite_data("Top"), _mock_suite_result())
        listener.start_suite(_mock_suite_data("Nested"), _mock_suite_result())
        listener.end_suite(_mock_suite_data("Nested"), _mock_suite_result())

        mock_db.add_test_run.assert_not_called()


class TestDbListenerEndTest:
    def test_records_test_case(self) -> None:
        listener = DbListener()
        listener.end_test(
            _mock_test_data("Test One"),
            _mock_test_result("PASS"),
        )
        assert len(listener._test_cases) == 1
        assert listener._test_cases[0]["name"] == "Test One"
        assert listener._test_cases[0]["status"] == "PASS"

    def test_extracts_score_from_tags(self) -> None:
        listener = DbListener()
        listener.end_test(
            _mock_test_data("Test One", tags=["IQ:100", "score:1"]),
            _mock_test_result(),
        )
        assert listener._test_cases[0]["score"] == 1.0

    def test_score_negative_one_when_no_score_tag(self) -> None:
        listener = DbListener()
        listener.end_test(
            _mock_test_data("Test One", tags=["IQ:100"]),
            _mock_test_result(),
        )
        assert listener._test_cases[0]["score"] == -1.0

    def test_score_from_rfc_data_fallback(self) -> None:
        """Score captured from RFC_DATA when no score: tag exists."""
        listener = DbListener()
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:score:1"))
        listener.end_test(
            _mock_test_data("T", tags=["tier:1"]),
            _mock_test_result(),
        )
        assert listener._test_cases[0]["score"] == 1.0

    def test_score_from_rfc_data_float(self) -> None:
        """Float score captured from RFC_DATA."""
        listener = DbListener()
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:score:0.75"))
        listener.end_test(
            _mock_test_data("T", tags=["tier:1"]),
            _mock_test_result(),
        )
        assert listener._test_cases[0]["score"] == 0.75

    def test_score_tag_takes_precedence_over_rfc_data(self) -> None:
        """Tag-based score wins when both tag and RFC_DATA are present."""
        listener = DbListener()
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:score:0"))
        listener.end_test(
            _mock_test_data("T", tags=["score:1"]),
            _mock_test_result(),
        )
        assert listener._test_cases[0]["score"] == 1.0

    def test_score_negative_one_for_invalid_score_tag(self) -> None:
        listener = DbListener()
        listener.end_test(
            _mock_test_data("Test One", tags=["score:abc"]),
            _mock_test_result(),
        )
        assert listener._test_cases[0]["score"] == -1.0

    def test_uses_doc_as_question(self) -> None:
        listener = DbListener()
        listener.end_test(
            _mock_test_data("T", doc="What is 2+2?"),
            _mock_test_result(),
        )
        assert listener._test_cases[0]["question"] == "What is 2+2?"

    def test_empty_doc_becomes_empty_string(self) -> None:
        listener = DbListener()
        listener.end_test(
            _mock_test_data("T", doc=""),
            _mock_test_result(),
        )
        assert listener._test_cases[0]["question"] == ""

    def test_multiple_tests_recorded(self) -> None:
        listener = DbListener()
        for i in range(5):
            listener.end_test(
                _mock_test_data(f"Test {i}"),
                _mock_test_result(),
            )
        assert len(listener._test_cases) == 5


class TestDbListenerEndSuiteArchival:
    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_archives_to_database(self, _mock_ci: MagicMock, tmp_path: object) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite(_mock_suite_data("My Suite"), _mock_suite_result())
        listener.end_test(_mock_test_data("Test A"), _mock_test_result("PASS"))
        listener.end_test(_mock_test_data("Test B"), _mock_test_result("FAIL"))
        listener.end_suite(_mock_suite_data("My Suite"), _mock_suite_result(total=2))

        db = listener._get_db()
        runs = db.get_recent_runs(limit=1)
        assert len(runs) == 1
        assert runs[0]["test_suite"] == "My Suite"
        assert runs[0]["passed"] == 1
        assert runs[0]["failed"] == 1

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_counts_pass_fail_skip(self, _mock_ci: MagicMock, tmp_path: object) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite(_mock_suite_data("Suite"), _mock_suite_result())
        listener.end_test(_mock_test_data("T1"), _mock_test_result("PASS"))
        listener.end_test(_mock_test_data("T2"), _mock_test_result("PASS"))
        listener.end_test(_mock_test_data("T3"), _mock_test_result("FAIL"))
        listener.end_test(_mock_test_data("T4"), _mock_test_result("SKIP"))
        listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result(total=4))

        runs = listener._get_db().get_recent_runs(limit=1)
        assert runs[0]["passed"] == 2
        assert runs[0]["failed"] == 1
        assert runs[0]["skipped"] == 1
        assert runs[0]["total_tests"] == 4

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_total_tests_falls_back_to_test_case_count(
        self, _mock_ci: MagicMock, tmp_path: object
    ) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite(_mock_suite_data("Suite"), _mock_suite_result())
        listener.end_test(_mock_test_data("T1"), _mock_test_result("PASS"))
        listener.end_test(_mock_test_data("T2"), _mock_test_result("PASS"))
        listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result(total=0))

        runs = listener._get_db().get_recent_runs(limit=1)
        assert runs[0]["total_tests"] == 2

    @patch("rfc.db_listener.collect_ci_metadata", return_value={"Commit_SHA": "abc"})
    def test_ci_metadata_included_in_run(
        self, _mock_ci: MagicMock, tmp_path: object
    ) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite(_mock_suite_data("Suite"), _mock_suite_result())
        listener.end_test(_mock_test_data("T1"), _mock_test_result())
        listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result())

        runs = listener._get_db().get_recent_runs(limit=1)
        assert runs[0]["git_commit"] == "abc"

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_rfc_version_recorded(self, _mock_ci: MagicMock, tmp_path: object) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite(_mock_suite_data("Suite"), _mock_suite_result())
        listener.end_test(_mock_test_data("T1"), _mock_test_result())
        listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result())

        runs = listener._get_db().get_recent_runs(limit=1)
        assert runs[0]["rfc_version"] != ""

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_model_name_from_env(self, _mock_ci: MagicMock, tmp_path: object) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        with patch.dict(os.environ, {"DEFAULT_MODEL": "mistral"}):
            listener.start_suite(_mock_suite_data("Suite"), _mock_suite_result())
            listener.end_test(_mock_test_data("T1"), _mock_test_result())
            listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result())

        runs = listener._get_db().get_recent_runs(limit=1)
        assert runs[0]["model_name"] == "mistral"

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_model_name_from_robot_variable_overrides_env(
        self, _mock_ci: MagicMock, tmp_path: object
    ) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        with patch.dict(os.environ, {"DEFAULT_MODEL": "phi4:14b"}):
            listener.start_suite(_mock_suite_data("Suite"), _mock_suite_result())
            listener.end_test(_mock_test_data("T1"), _mock_test_result())
            with patch("rfc.db_listener.BuiltIn") as mock_builtin_cls:
                mock_builtin_cls.return_value.get_variable_value.return_value = "llama3"
                listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result())

        runs = listener._get_db().get_recent_runs(limit=1)
        assert runs[0]["model_name"] == "llama3"

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_database_error_does_not_raise(self, _mock_ci: MagicMock) -> None:
        listener = DbListener()
        mock_db = MagicMock()
        mock_db.add_test_run.side_effect = Exception("db error")
        listener._db = mock_db

        listener.start_suite(_mock_suite_data("Suite"), _mock_suite_result())
        listener.end_test(_mock_test_data("T1"), _mock_test_result())
        # Should not raise — errors are logged and swallowed
        listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result())


class TestDbListenerLogMessage:
    """Tests for RFC_DATA: structured log message capture."""

    def test_captures_actual_answer(self) -> None:
        listener = DbListener()
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:actual_answer:The answer is 4"))
        listener.end_test(_mock_test_data("T"), _mock_test_result())
        assert listener._test_cases[0]["actual_answer"] == "The answer is 4"

    def test_captures_expected_answer(self) -> None:
        listener = DbListener()
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:expected_answer:4"))
        listener.end_test(_mock_test_data("T"), _mock_test_result())
        assert listener._test_cases[0]["expected_answer"] == "4"

    def test_captures_grading_reason(self) -> None:
        listener = DbListener()
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        listener.log_message(
            _mock_message("RFC_DATA:grading_reason:Correct numeric answer")
        )
        listener.end_test(_mock_test_data("T"), _mock_test_result())
        assert listener._test_cases[0]["grading_reason"] == "Correct numeric answer"

    def test_ignores_non_rfc_data_messages(self) -> None:
        listener = DbListener()
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        listener.log_message(_mock_message("Just a normal log message"))
        listener.end_test(_mock_test_data("T"), _mock_test_result())
        assert listener._test_cases[0]["actual_answer"] is None

    def test_ignores_empty_message(self) -> None:
        listener = DbListener()
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        listener.log_message(_mock_message(""))
        listener.end_test(_mock_test_data("T"), _mock_test_result())
        assert listener._test_cases[0]["actual_answer"] is None

    def test_resets_between_tests(self) -> None:
        listener = DbListener()
        listener.start_test(_mock_test_data("T1"), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:actual_answer:first"))
        listener.end_test(_mock_test_data("T1"), _mock_test_result())

        listener.start_test(_mock_test_data("T2"), _mock_test_result())
        listener.end_test(_mock_test_data("T2"), _mock_test_result())

        assert listener._test_cases[0]["actual_answer"] == "first"
        assert listener._test_cases[1]["actual_answer"] is None

    def test_handles_value_with_colons(self) -> None:
        listener = DbListener()
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        listener.log_message(
            _mock_message("RFC_DATA:grading_reason:Score: 1/1, reason: correct")
        )
        listener.end_test(_mock_test_data("T"), _mock_test_result())
        assert (
            listener._test_cases[0]["grading_reason"] == "Score: 1/1, reason: correct"
        )

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_captured_data_archived_to_database(
        self, _mock_ci: MagicMock, tmp_path: object
    ) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite(_mock_suite_data("Suite"), _mock_suite_result())
        listener.start_test(_mock_test_data("Math Test"), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:actual_answer:4"))
        listener.log_message(_mock_message("RFC_DATA:expected_answer:4"))
        listener.log_message(_mock_message("RFC_DATA:grading_reason:Correct"))
        listener.end_test(_mock_test_data("Math Test"), _mock_test_result("PASS"))
        listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result(total=1))

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_results").fetchone()
            assert row["actual_answer"] == "4"
            assert row["expected_answer"] == "4"
            assert row["grading_reason"] == "Correct"

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_rfc_data_score_archived_to_database(
        self, _mock_ci: MagicMock, tmp_path: object
    ) -> None:
        """Score from RFC_DATA flows through to the database."""
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite(_mock_suite_data("Suite"), _mock_suite_result())
        listener.start_test(_mock_test_data("Graded Test"), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:score:1"))
        listener.log_message(_mock_message("RFC_DATA:expected_answer:4"))
        listener.log_message(_mock_message("RFC_DATA:grading_reason:Correct"))
        listener.end_test(_mock_test_data("Graded Test"), _mock_test_result("PASS"))
        listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result(total=1))

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_results").fetchone()
            assert row["score"] == 1.0


class TestDbListenerStartTest:
    def test_resets_current_test_data(self) -> None:
        listener = DbListener()
        listener._current_test_data = {"stale": "data"}
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        assert listener._current_test_data == {}


class TestDbListenerGetDb:
    def test_lazy_creates_database(self, tmp_path: object) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        listener = DbListener(database_url=f"sqlite:///{db_path}")
        assert listener._db is None
        db = listener._get_db()
        assert db is not None
        assert listener._db is db

    def test_reuses_existing_database(self, tmp_path: object) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        listener = DbListener(database_url=f"sqlite:///{db_path}")
        db1 = listener._get_db()
        db2 = listener._get_db()
        assert db1 is db2


class TestDbListenerDatabaseDescription:
    def test_not_configured_when_no_url(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            listener = DbListener()
            desc = listener._describe_database_destination()
            assert "NOT CONFIGURED" in desc

    def test_explicit_sqlite_url(self) -> None:
        listener = DbListener(database_url="sqlite:///path/to/my.db")
        desc = listener._describe_database_destination()
        assert "SQLite" in desc
        assert "path/to/my.db" in desc

    def test_postgresql_url_strips_credentials(self) -> None:
        listener = DbListener(
            database_url="postgresql://user:secret@localhost:5433/rfc"
        )
        desc = listener._describe_database_destination()
        assert "PostgreSQL" in desc
        assert "localhost:5433/rfc" in desc
        assert "secret" not in desc

    def test_does_not_trigger_db_init(self) -> None:
        listener = DbListener(database_url="sqlite:///whatever.db")
        listener._describe_database_destination()
        assert listener._db is None


class TestDbListenerConsoleOutput:
    @patch("rfc.db_listener.logger")
    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_start_suite_emits_console_banner(
        self, _mock_ci: MagicMock, mock_logger: MagicMock
    ) -> None:
        listener = DbListener(database_url="sqlite:///test.db")
        listener.start_suite(_mock_suite_data("My Suite"), _mock_suite_result())

        mock_logger.console.assert_called()
        console_calls = [str(call) for call in mock_logger.console.call_args_list]
        full_output = " ".join(console_calls)
        assert "SQLite" in full_output

    @patch("rfc.db_listener.logger")
    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_start_suite_banner_not_repeated_for_nested(
        self, _mock_ci: MagicMock, mock_logger: MagicMock
    ) -> None:
        listener = DbListener(database_url="sqlite:///test.db")
        listener.start_suite(_mock_suite_data("Top"), _mock_suite_result())
        mock_logger.console.reset_mock()
        listener.start_suite(_mock_suite_data("Nested"), _mock_suite_result())
        mock_logger.console.assert_not_called()

    @patch("rfc.db_listener.logger")
    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_end_suite_emits_console_summary(
        self, _mock_ci: MagicMock, mock_logger: MagicMock, tmp_path: object
    ) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite(_mock_suite_data("Suite"), _mock_suite_result())
        listener.end_test(_mock_test_data("T1"), _mock_test_result("PASS"))
        listener.end_test(_mock_test_data("T2"), _mock_test_result("FAIL"))
        mock_logger.console.reset_mock()
        listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result(total=2))

        mock_logger.console.assert_called()
        console_calls = [str(call) for call in mock_logger.console.call_args_list]
        full_output = " ".join(console_calls)
        assert "2 test" in full_output
        assert "run_id=" in full_output

    @patch("rfc.db_listener.logger")
    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_database_error_emits_console_warning(
        self, _mock_ci: MagicMock, mock_logger: MagicMock
    ) -> None:
        listener = DbListener()
        mock_db = MagicMock()
        mock_db.add_test_run.side_effect = Exception("connection refused")
        listener._db = mock_db

        listener.start_suite(_mock_suite_data("Suite"), _mock_suite_result())
        listener.end_test(_mock_test_data("T1"), _mock_test_result())
        mock_logger.console.reset_mock()
        listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result())

        mock_logger.console.assert_called()
        console_calls = [str(call) for call in mock_logger.console.call_args_list]
        full_output = " ".join(console_calls)
        assert "FAILED" in full_output
        assert "connection refused" in full_output


class TestDbListenerHostInfo:
    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    @patch(
        "rfc.db_listener.collect_host_info",
        return_value={
            "hostname": "dev1",
            "os_name": "Linux",
            "os_version": "5.15.0",
            "cpu_arch": "x86_64",
            "cpu_count": 16,
            "total_ram_gb": 64.0,
            "gpu_info": "NVIDIA RTX 4090, 24576 MiB",
        },
    )
    def test_hostname_stored_on_test_run(
        self, _mock_host: MagicMock, _mock_ci: MagicMock, tmp_path: object
    ) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite(_mock_suite_data("Suite"), _mock_suite_result())
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        listener.end_test(_mock_test_data("T"), _mock_test_result())
        listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result(total=1))

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_runs").fetchone()
            assert row["hostname"] == "dev1"


class TestBuildOutputXmlUrl:
    def test_from_report_base_url(self) -> None:
        env = {"REPORT_BASE_URL": "https://results.example.com/math"}
        with patch.dict(os.environ, env, clear=False):
            url = _build_output_xml_url()
        assert url == "https://results.example.com/math/output.xml"

    def test_from_ci_job_url(self) -> None:
        env = {"CI_JOB_URL": "https://gitlab.example.com/project/-/jobs/123"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("REPORT_BASE_URL", None)
            url = _build_output_xml_url()
        assert url is not None
        assert "output.xml" in url

    def test_from_output_dir(self) -> None:
        env = {"ROBOT_OUTPUT_DIR": "/tmp/results/math"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("REPORT_BASE_URL", None)
            os.environ.pop("CI_JOB_URL", None)
            url = _build_output_xml_url()
        assert url == "/tmp/results/math/output.xml"

    def test_empty_when_no_env(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REPORT_BASE_URL", None)
            os.environ.pop("CI_JOB_URL", None)
            os.environ.pop("ROBOT_OUTPUT_DIR", None)
            url = _build_output_xml_url()
        assert url == ""


class TestParseTags:
    """Tests for _parse_tags() structured tag extraction."""

    def test_extracts_severity(self) -> None:
        result = _parse_tags(["safety", "severity:high", "regression"])
        assert result["tag_severity"] == "high"

    def test_extracts_tier(self) -> None:
        result = _parse_tags(["tier:1", "safety"])
        assert result["tag_tier"] == 1

    def test_extracts_verify(self) -> None:
        result = _parse_tags(["verify:python", "safety"])
        assert result["tag_verify"] == "python"

    def test_remaining_tags_sorted_alphabetically(self) -> None:
        result = _parse_tags(
            [
                "safety",
                "regression",
                "batch",
                "severity:high",
                "tier:1",
                "verify:python",
            ]
        )
        assert result["tags_sorted"] == "batch,regression,safety"

    def test_empty_tags(self) -> None:
        result = _parse_tags([])
        assert result["tag_severity"] == ""
        assert result["tag_tier"] == -1
        assert result["tag_verify"] == ""
        assert result["tags_sorted"] == ""

    def test_no_structured_tags(self) -> None:
        result = _parse_tags(["safety", "regression"])
        assert result["tag_severity"] == ""
        assert result["tag_tier"] == -1
        assert result["tag_verify"] == ""
        assert result["tags_sorted"] == "regression,safety"

    def test_invalid_tier_kept_in_other(self) -> None:
        result = _parse_tags(["tier:abc", "safety"])
        assert result["tag_tier"] == -1
        assert "tier:abc" in result["tags_sorted"]

    def test_all_structured_no_remaining(self) -> None:
        result = _parse_tags(["severity:critical", "tier:2", "verify:llm"])
        assert result["tag_severity"] == "critical"
        assert result["tag_tier"] == 2
        assert result["tag_verify"] == "llm"
        assert result["tags_sorted"] == ""

    def test_real_safety_suite_tags(self) -> None:
        """Test with actual tags from the Safety test suite."""
        result = _parse_tags(
            [
                "safety",
                "llm-security",
                "regression",
                "tier:1",
                "verify:python",
                "prompt_injection",
                "severity:critical",
            ]
        )
        assert result["tag_severity"] == "critical"
        assert result["tag_tier"] == 1
        assert result["tag_verify"] == "python"
        assert (
            result["tags_sorted"] == "llm-security,prompt_injection,regression,safety"
        )

    def test_score_tag_kept_in_other(self) -> None:
        """score: tags are NOT extracted (handled separately by DbListener)."""
        result = _parse_tags(["score:1", "tier:0", "verify:robot"])
        assert result["tag_tier"] == 0
        assert result["tag_verify"] == "robot"
        assert "score:1" in (result["tags_sorted"] or "")


class TestFormatSize:
    def test_bytes(self) -> None:
        assert _format_size(500) == "500B"

    def test_kilobytes(self) -> None:
        assert "KB" in _format_size(5000)

    def test_megabytes(self) -> None:
        assert "MB" in _format_size(5_000_000)


class TestSafeInt:
    def test_valid_int(self) -> None:
        assert _safe_int("42") == 42

    def test_none_returns_none(self) -> None:
        assert _safe_int(None) is None

    def test_invalid_returns_none(self) -> None:
        assert _safe_int("abc") is None


class TestExtractLlmMetrics:
    def test_valid_json(self) -> None:
        data = '{"eval_count": 186, "eval_duration_ns": 16907870673, "eval_rate": 11.0}'
        result = _extract_llm_metrics(data)
        assert result["eval_count"] == 186
        assert result["eval_duration_ns"] == 16907870673
        assert result["eval_rate"] == 11.0

    def test_none_returns_empty(self) -> None:
        assert _extract_llm_metrics(None) == {}

    def test_invalid_json_returns_empty(self) -> None:
        assert _extract_llm_metrics("not json") == {}

    def test_missing_keys_return_none(self) -> None:
        result = _extract_llm_metrics('{"eval_count": 10}')
        assert result["eval_count"] == 10
        assert result.get("eval_duration_ns") is None


class TestDbListenerThinkingCapture:
    """Tests for thinking and metrics data capture in the listener."""

    def test_captures_thinking_text(self) -> None:
        listener = DbListener()
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:thinking_text:I need to reason"))
        listener.end_test(_mock_test_data("T"), _mock_test_result())
        assert listener._test_cases[0]["thinking_text"] == "I need to reason"

    def test_captures_thinking_tokens(self) -> None:
        listener = DbListener()
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:thinking_tokens:15"))
        listener.end_test(_mock_test_data("T"), _mock_test_result())
        assert listener._test_cases[0]["thinking_tokens"] == 15

    def test_captures_num_ctx(self) -> None:
        listener = DbListener()
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:num_ctx:4096"))
        listener.end_test(_mock_test_data("T"), _mock_test_result())
        assert listener._test_cases[0]["num_ctx"] == 4096

    def test_extracts_metrics_from_llm_metrics_json(self) -> None:
        listener = DbListener()
        listener.start_test(_mock_test_data("T"), _mock_test_result())
        metrics = (
            '{"eval_count": 186, "eval_duration_ns": 16907870673, "eval_rate": 11.0}'
        )
        listener.log_message(_mock_message(f"RFC_DATA:llm_metrics:{metrics}"))
        listener.end_test(_mock_test_data("T"), _mock_test_result())
        assert listener._test_cases[0]["eval_count"] == 186
        assert listener._test_cases[0]["tokens_per_second"] == 11.0

    @patch("rfc.db_listener.collect_ci_metadata", return_value={})
    def test_thinking_data_archived_to_database(
        self, _mock_ci: MagicMock, tmp_path: object
    ) -> None:
        db_path = str(tmp_path / "test.db")  # type: ignore[operator]
        listener = DbListener(database_url=f"sqlite:///{db_path}")

        listener.start_suite(_mock_suite_data("Suite"), _mock_suite_result())
        listener.start_test(_mock_test_data("Think Test"), _mock_test_result())
        listener.log_message(_mock_message("RFC_DATA:actual_answer:42"))
        listener.log_message(_mock_message("RFC_DATA:thinking_text:Let me think"))
        listener.log_message(_mock_message("RFC_DATA:thinking_tokens:3"))
        listener.log_message(_mock_message("RFC_DATA:num_ctx:8192"))
        metrics = (
            '{"eval_count": 50, "eval_duration_ns": 5000000000, "eval_rate": 10.0}'
        )
        listener.log_message(_mock_message(f"RFC_DATA:llm_metrics:{metrics}"))
        listener.end_test(_mock_test_data("Think Test"), _mock_test_result("PASS"))
        listener.end_suite(_mock_suite_data("Suite"), _mock_suite_result(total=1))

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM test_results").fetchone()
            assert row["thinking_text"] == "Let me think"
            assert row["thinking_tokens"] == 3
            assert row["num_ctx"] == 8192
            assert row["eval_count"] == 50
            assert row["tokens_per_second"] == 10.0
