"""Tests for the analytics metadata layer.

Uses an in-memory SQLite database with synthetic test data to verify
trend computation, stability scoring, regression detection, model
comparison, and performance fingerprinting.
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from src.rfc.analytics import (
    compute_model_comparison,
    compute_model_trends,
    compute_performance_fingerprints,
    compute_test_stability,
    detect_regressions,
    refresh_all,
)


def _create_schema(conn: sqlite3.Connection) -> None:
    """Create the minimal schema needed for analytics."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS test_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            model_name TEXT NOT NULL,
            test_suite TEXT NOT NULL,
            total_tests INTEGER DEFAULT 0,
            passed INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            skipped INTEGER DEFAULT 0,
            duration_seconds REAL,
            hostname TEXT,
            model_release_date TEXT,
            model_parameters TEXT,
            git_commit TEXT,
            git_branch TEXT,
            pipeline_url TEXT,
            runner_id TEXT,
            runner_tags TEXT,
            rfc_version TEXT,
            report_url TEXT,
            log_url TEXT
        );

        CREATE TABLE IF NOT EXISTS test_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            test_name TEXT NOT NULL,
            test_status TEXT NOT NULL,
            score INTEGER,
            question TEXT,
            expected_answer TEXT,
            actual_answer TEXT,
            grading_reason TEXT,
            rfc_version TEXT,
            FOREIGN KEY (run_id) REFERENCES test_runs(id)
        );

        CREATE TABLE IF NOT EXISTS ollama_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            test_name TEXT NOT NULL,
            model_name TEXT NOT NULL,
            prompt_text TEXT,
            total_duration_ns INTEGER,
            eval_count INTEGER,
            eval_duration_ns INTEGER,
            eval_rate REAL,
            load_duration_ns INTEGER,
            prompt_eval_count INTEGER,
            prompt_eval_duration_ns INTEGER,
            prompt_eval_rate REAL,
            rfc_version TEXT,
            timestamp DATETIME,
            FOREIGN KEY (run_id) REFERENCES test_runs(id)
        );
    """)


def _insert_run(
    conn: sqlite3.Connection,
    model: str,
    suite: str,
    passed: int,
    failed: int,
    duration: float,
    ts: datetime,
    hostname: str = "test-host",
) -> int:
    """Insert a test run and return its ID."""
    cursor = conn.execute(
        """INSERT INTO test_runs
           (timestamp, model_name, test_suite, total_tests, passed, failed,
            duration_seconds, hostname, git_commit, git_branch, pipeline_url,
            runner_id, runner_tags)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '', '', '', '')""",
        (ts.isoformat(), model, suite, passed + failed, passed, failed,
         duration, hostname),
    )
    return cursor.lastrowid  # type: ignore[return-value]


def _insert_result(
    conn: sqlite3.Connection,
    run_id: int,
    test_name: str,
    status: str,
) -> None:
    """Insert an individual test result."""
    conn.execute(
        """INSERT INTO test_results (run_id, test_name, test_status)
           VALUES (?, ?, ?)""",
        (run_id, test_name, status),
    )


@pytest.fixture
def db_conn() -> sqlite3.Connection:
    """Create an in-memory SQLite database with analytics schema."""
    conn = sqlite3.connect(":memory:")
    _create_schema(conn)
    return conn


@pytest.fixture
def populated_db(db_conn: sqlite3.Connection) -> sqlite3.Connection:
    """Database with synthetic test data for analytics.

    Creates runs for two models over 14 days, with llama3 stable
    and mistral gradually degrading.
    """
    now = datetime.now()
    for day in range(14):
        ts = now - timedelta(days=13 - day)

        # llama3: consistently good (9/10 pass)
        run_id = _insert_run(db_conn, "llama3", "math", 9, 1, 30.0, ts)
        for i in range(9):
            _insert_result(db_conn, run_id, f"test_{i}", "PASS")
        _insert_result(db_conn, run_id, "test_9", "FAIL")

        # mistral: starts good, degrades in second week
        if day < 7:
            run_id = _insert_run(db_conn, "mistral", "math", 8, 2, 25.0, ts)
            for i in range(8):
                _insert_result(db_conn, run_id, f"test_{i}", "PASS")
            for i in range(8, 10):
                _insert_result(db_conn, run_id, f"test_{i}", "FAIL")
        else:
            run_id = _insert_run(db_conn, "mistral", "math", 5, 5, 40.0, ts)
            for i in range(5):
                _insert_result(db_conn, run_id, f"test_{i}", "PASS")
            for i in range(5, 10):
                _insert_result(db_conn, run_id, f"test_{i}", "FAIL")

    db_conn.commit()
    return db_conn


class TestComputeModelTrends:
    def test_computes_trends_for_both_models(
        self, populated_db: sqlite3.Connection
    ) -> None:
        count = compute_model_trends(populated_db, window_days=7)
        assert count >= 2  # at least one trend row per model

    def test_detects_regression_direction(
        self, populated_db: sqlite3.Connection
    ) -> None:
        compute_model_trends(populated_db, window_days=7)
        rows = populated_db.execute(
            "SELECT model_name, trend_direction FROM analytics_model_trends"
        ).fetchall()
        directions = {r[0]: r[1] for r in rows}
        # mistral should show regressing (pass rate dropped)
        assert directions.get("mistral") == "regressing"
        # llama3 should be stable
        assert directions.get("llama3") == "stable"

    def test_idempotent_recomputation(
        self, populated_db: sqlite3.Connection
    ) -> None:
        count1 = compute_model_trends(populated_db, window_days=7)
        count2 = compute_model_trends(populated_db, window_days=7)
        # Should replace, not duplicate
        assert count1 == count2

    def test_empty_db_returns_zero(self, db_conn: sqlite3.Connection) -> None:
        count = compute_model_trends(db_conn, window_days=7)
        assert count == 0


class TestComputeTestStability:
    def test_classifies_stable_test(
        self, populated_db: sqlite3.Connection
    ) -> None:
        compute_test_stability(populated_db, window_runs=14)
        rows = populated_db.execute(
            """SELECT test_name, classification FROM analytics_test_stability
               WHERE model_name = 'llama3' AND test_name = 'test_0'"""
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "stable"

    def test_classifies_broken_test(
        self, populated_db: sqlite3.Connection
    ) -> None:
        compute_test_stability(populated_db, window_runs=14)
        rows = populated_db.execute(
            """SELECT test_name, classification FROM analytics_test_stability
               WHERE model_name = 'llama3' AND test_name = 'test_9'"""
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "broken"

    def test_detects_flaky_test(self, db_conn: sqlite3.Connection) -> None:
        """A test that oscillates PASS/FAIL should be classified as flaky."""
        now = datetime.now()
        for day in range(10):
            ts = now - timedelta(days=9 - day)
            run_id = _insert_run(db_conn, "phi4", "math", 1, 0, 5.0, ts)
            # Alternates PASS/FAIL each day
            status = "PASS" if day % 2 == 0 else "FAIL"
            _insert_result(db_conn, run_id, "flaky_test", status)
        db_conn.commit()

        compute_test_stability(db_conn, window_runs=10)
        rows = db_conn.execute(
            """SELECT test_name, classification, stability_score
               FROM analytics_test_stability
               WHERE model_name = 'phi4' AND test_name = 'flaky_test'"""
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "flaky"
        assert 0.0 < rows[0][2] < 1.0

    def test_stability_score_range(
        self, populated_db: sqlite3.Connection
    ) -> None:
        compute_test_stability(populated_db, window_runs=14)
        rows = populated_db.execute(
            "SELECT stability_score FROM analytics_test_stability"
        ).fetchall()
        for row in rows:
            assert 0.0 <= row[0] <= 1.0

    def test_empty_db(self, db_conn: sqlite3.Connection) -> None:
        count = compute_test_stability(db_conn, window_runs=10)
        assert count == 0


class TestComputeModelComparison:
    def test_creates_pairwise_comparison(
        self, populated_db: sqlite3.Connection
    ) -> None:
        count = compute_model_comparison(populated_db)
        assert count >= 1

    def test_llama3_beats_mistral(
        self, populated_db: sqlite3.Connection
    ) -> None:
        compute_model_comparison(populated_db)
        rows = populated_db.execute(
            """SELECT model_a, model_b, winner
               FROM analytics_model_comparison
               WHERE test_suite = 'math'"""
        ).fetchall()
        assert len(rows) >= 1
        # At least one comparison should show llama3 winning
        winners = [r[2] for r in rows]
        assert "llama3" in winners

    def test_empty_db(self, db_conn: sqlite3.Connection) -> None:
        count = compute_model_comparison(db_conn)
        assert count == 0


class TestDetectRegressions:
    def test_detects_mistral_regression(
        self, populated_db: sqlite3.Connection
    ) -> None:
        alerts = detect_regressions(populated_db, threshold=0.1)
        assert len(alerts) >= 1
        # Should flag mistral's pass rate drop
        mistral_alerts = [a for a in alerts if a["model_name"] == "mistral"]
        assert len(mistral_alerts) >= 1
        assert mistral_alerts[0]["alert_type"] == "pass_rate_drop"

    def test_no_false_positives_for_stable_model(
        self, populated_db: sqlite3.Connection
    ) -> None:
        alerts = detect_regressions(populated_db, threshold=0.1)
        llama_alerts = [a for a in alerts if a["model_name"] == "llama3"]
        assert len(llama_alerts) == 0

    def test_severity_levels(
        self, populated_db: sqlite3.Connection
    ) -> None:
        alerts = detect_regressions(populated_db, threshold=0.1)
        for alert in alerts:
            assert alert["severity"] in ("info", "warning", "critical")

    def test_empty_db(self, db_conn: sqlite3.Connection) -> None:
        alerts = detect_regressions(db_conn, threshold=0.1)
        assert alerts == []


class TestComputePerformanceFingerprints:
    def test_computes_fingerprints(
        self, populated_db: sqlite3.Connection
    ) -> None:
        count = compute_performance_fingerprints(populated_db)
        assert count >= 1

    def test_empty_db(self, db_conn: sqlite3.Connection) -> None:
        count = compute_performance_fingerprints(db_conn)
        assert count == 0


class TestRefreshAll:
    def test_runs_all_computations(
        self, populated_db: sqlite3.Connection
    ) -> None:
        result = refresh_all(populated_db)
        assert "model_trends" in result
        assert "test_stability" in result
        assert "model_comparison" in result
        assert "regressions" in result
        assert "performance_fingerprints" in result
        # All should have produced rows
        assert result["model_trends"] > 0
        assert result["test_stability"] > 0
