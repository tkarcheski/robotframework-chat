"""Tests for the test_runs.session_id and .model_harness migrations (Issue #350)."""

import sqlite3
from datetime import datetime

from rfc.test_database import TestDatabase, TestResult, TestRun


_PRE_MIGRATION_TEST_RUNS_DDL = """
CREATE TABLE test_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    model_name TEXT NOT NULL,
    test_suite TEXT NOT NULL,
    total_tests INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    duration_seconds REAL,
    git_commit TEXT,
    git_branch TEXT,
    hostname TEXT,
    rfc_version TEXT
)
"""

# A genuinely old schema that predates the ``hostname`` column. The
# ``test_results_full`` view references ``r.hostname``, so opening a database
# at this revision must add the column before creating the view.
_PRE_HOSTNAME_TEST_RUNS_DDL = """
CREATE TABLE test_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    model_name TEXT NOT NULL,
    test_suite TEXT NOT NULL,
    total_tests INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    duration_seconds REAL,
    git_commit TEXT,
    git_branch TEXT,
    rfc_version TEXT
)
"""


class TestSessionIdColumn:
    def test_fresh_db_has_session_id_column(self, tmp_path):
        db_file = tmp_path / "test.db"
        TestDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(test_runs)")}
        assert "session_id" in cols

    def test_session_id_added_to_existing_pre_migration_db(self, tmp_path):
        db_file = tmp_path / "test.db"
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute(_PRE_MIGRATION_TEST_RUNS_DDL)
            conn.execute(
                "INSERT INTO test_runs (timestamp, model_name, test_suite) VALUES (?, ?, ?)",
                ("2026-01-01T00:00:00", "llama3", "math"),
            )
        TestDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            rows = conn.execute(
                "SELECT id, model_name, session_id FROM test_runs"
            ).fetchall()
        assert rows == [(1, "llama3", None)]

    def test_migration_is_idempotent(self, tmp_path):
        db_file = tmp_path / "test.db"
        TestDatabase(db_path=str(db_file))
        TestDatabase(db_path=str(db_file))

    def test_view_exposes_session_id(self, tmp_path):
        db_file = tmp_path / "test.db"
        db = TestDatabase(db_path=str(db_file))
        run = TestRun(
            timestamp=datetime(2026, 5, 9, 0, 0, 0),
            model_name="llama3",
            test_suite="math",
            total_tests=1,
            passed=1,
            failed=0,
            skipped=0,
            duration_seconds=1.0,
            session_id="my-session-abc",
        )
        run_id = db.add_test_run(run)
        db.add_test_results(
            [TestResult(run_id=run_id, test_name="t1", test_status="PASS")]
        )
        with sqlite3.connect(str(db_file)) as conn:
            row = conn.execute(
                "SELECT session_id FROM test_results_full WHERE test_name = 't1'"
            ).fetchone()
        assert row[0] == "my-session-abc"


class TestHostnameColumn:
    def test_fresh_db_has_hostname_column(self, tmp_path):
        db_file = tmp_path / "test.db"
        TestDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(test_runs)")}
        assert "hostname" in cols

    def test_hostname_added_to_existing_pre_hostname_db(self, tmp_path):
        db_file = tmp_path / "test.db"
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute(_PRE_HOSTNAME_TEST_RUNS_DDL)
            conn.execute(
                "INSERT INTO test_runs (timestamp, model_name, test_suite) VALUES (?, ?, ?)",
                ("2026-01-01T00:00:00", "llama3", "math"),
            )
        # Opening the DB must add the missing column *and* build the
        # ``test_results_full`` view, which references ``r.hostname``.
        TestDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(test_runs)")}
            rows = conn.execute(
                "SELECT id, model_name, hostname FROM test_runs"
            ).fetchall()
        assert "hostname" in cols
        assert rows == [(1, "llama3", None)]

    def test_view_exposes_hostname(self, tmp_path):
        db_file = tmp_path / "test.db"
        db = TestDatabase(db_path=str(db_file))
        run = TestRun(
            timestamp=datetime(2026, 5, 9, 0, 0, 0),
            model_name="llama3",
            test_suite="math",
            total_tests=1,
            passed=1,
            failed=0,
            skipped=0,
            duration_seconds=1.0,
            hostname="ai1",
        )
        run_id = db.add_test_run(run)
        db.add_test_results(
            [TestResult(run_id=run_id, test_name="t1", test_status="PASS")]
        )
        with sqlite3.connect(str(db_file)) as conn:
            row = conn.execute(
                "SELECT hostname FROM test_results_full WHERE test_name = 't1'"
            ).fetchone()
        assert row[0] == "ai1"


class TestTestRunDataclass:
    def test_session_id_default_is_empty_string(self):
        run = TestRun(
            timestamp=datetime(2026, 5, 9, 0, 0, 0),
            model_name="llama3",
            test_suite="math",
            total_tests=0,
            passed=0,
            failed=0,
            skipped=0,
            duration_seconds=0.0,
        )
        assert run.session_id == ""

    def test_model_harness_default_is_empty_string(self):
        run = TestRun(
            timestamp=datetime(2026, 5, 9, 0, 0, 0),
            model_name="llama3",
            test_suite="math",
            total_tests=0,
            passed=0,
            failed=0,
            skipped=0,
            duration_seconds=0.0,
        )
        assert run.model_harness == ""


class TestModelHarnessColumn:
    def test_fresh_db_has_model_harness_column(self, tmp_path):
        db_file = tmp_path / "test.db"
        TestDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(test_runs)")}
        assert "model_harness" in cols

    def test_model_harness_added_to_existing_pre_migration_db(self, tmp_path):
        db_file = tmp_path / "test.db"
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute(_PRE_MIGRATION_TEST_RUNS_DDL)
            conn.execute(
                "INSERT INTO test_runs (timestamp, model_name, test_suite) VALUES (?, ?, ?)",
                ("2026-01-01T00:00:00", "llama3", "math"),
            )
        TestDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            rows = conn.execute(
                "SELECT id, model_name, model_harness FROM test_runs"
            ).fetchall()
        assert rows == [(1, "llama3", None)]

    def test_view_exposes_model_harness(self, tmp_path):
        db_file = tmp_path / "test.db"
        db = TestDatabase(db_path=str(db_file))
        run = TestRun(
            timestamp=datetime(2026, 5, 9, 0, 0, 0),
            model_name="claude-opus-4-7[1m]",
            test_suite="agentic_coding",
            total_tests=1,
            passed=1,
            failed=0,
            skipped=0,
            duration_seconds=1.0,
            session_id="sid-xyz",
            model_harness="claude-opus-4-7[1m]",
        )
        run_id = db.add_test_run(run)
        db.add_test_results(
            [TestResult(run_id=run_id, test_name="t1", test_status="PASS")]
        )
        with sqlite3.connect(str(db_file)) as conn:
            row = conn.execute(
                "SELECT model_harness FROM test_results_full WHERE test_name = 't1'"
            ).fetchone()
        assert row[0] == "claude-opus-4-7[1m]"
