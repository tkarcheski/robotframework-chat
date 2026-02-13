"""Test results database manager for robotframework-chat.

Manages SQLite database for storing and querying test results
with Git LFS support for version control.
"""

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TestRun:
    """Represents a single test run/pipeline execution."""

    timestamp: datetime
    model_name: str
    model_release_date: Optional[str]
    model_parameters: Optional[str]
    test_suite: str
    gitlab_commit: str
    gitlab_branch: str
    gitlab_pipeline_url: str
    runner_id: str
    runner_tags: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    duration_seconds: float
    id: Optional[int] = None


@dataclass
class TestResult:
    """Represents an individual test case result."""

    run_id: int
    test_name: str
    test_status: str
    score: Optional[int]
    question: Optional[str]
    expected_answer: Optional[str]
    actual_answer: Optional[str]
    grading_reason: Optional[str]
    id: Optional[int] = None


@dataclass
class ModelInfo:
    """Represents model metadata."""

    name: str
    full_name: Optional[str]
    organization: Optional[str]
    release_date: Optional[str]
    parameters: Optional[str]
    last_tested: Optional[datetime] = None


class TestDatabase:
    """Manager for test results SQLite database."""

    SCHEMA = """
    -- Test runs table - one row per pipeline execution
    CREATE TABLE IF NOT EXISTS test_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME NOT NULL,
        model_name TEXT NOT NULL,
        model_release_date TEXT,
        model_parameters TEXT,
        test_suite TEXT NOT NULL,
        gitlab_commit TEXT,
        gitlab_branch TEXT,
        gitlab_pipeline_url TEXT,
        runner_id TEXT,
        runner_tags TEXT,
        total_tests INTEGER DEFAULT 0,
        passed INTEGER DEFAULT 0,
        failed INTEGER DEFAULT 0,
        skipped INTEGER DEFAULT 0,
        duration_seconds REAL
    );

    -- Individual test results
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
        FOREIGN KEY (run_id) REFERENCES test_runs(id) ON DELETE CASCADE
    );

    -- Model metadata
    CREATE TABLE IF NOT EXISTS models (
        name TEXT PRIMARY KEY,
        full_name TEXT,
        organization TEXT,
        release_date TEXT,
        parameters TEXT,
        last_tested DATETIME
    );

    -- Indexes for common queries
    CREATE INDEX IF NOT EXISTS idx_test_runs_model ON test_runs(model_name);
    CREATE INDEX IF NOT EXISTS idx_test_runs_timestamp ON test_runs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_test_runs_suite ON test_runs(test_suite);
    CREATE INDEX IF NOT EXISTS idx_test_results_run_id ON test_results(run_id);
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file. Defaults to data/test_history.db
        """
        if db_path is None:
            # Find project root and create data directory
            project_root = self._find_project_root()
            db_path = os.path.join(project_root, "data", "test_history.db")

        self.db_path = db_path
        self._ensure_directory()
        self._init_schema()

    def _find_project_root(self) -> str:
        """Find project root by looking for .git directory."""
        current = Path.cwd()
        while current != current.parent:
            if (current / ".git").exists():
                return str(current)
            current = current.parent
        return str(Path.cwd())

    def _ensure_directory(self) -> None:
        """Ensure database directory exists."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def _init_schema(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(self.SCHEMA)

    def add_test_run(self, run: TestRun) -> int:
        """Add a new test run and return its ID.

        Args:
            run: TestRun object to insert

        Returns:
            ID of the inserted run
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO test_runs
                (timestamp, model_name, model_release_date, model_parameters,
                 test_suite, gitlab_commit, gitlab_branch, gitlab_pipeline_url,
                 runner_id, runner_tags, total_tests, passed, failed, skipped, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.timestamp.isoformat(),
                    run.model_name,
                    run.model_release_date,
                    run.model_parameters,
                    run.test_suite,
                    run.gitlab_commit,
                    run.gitlab_branch,
                    run.gitlab_pipeline_url,
                    run.runner_id,
                    run.runner_tags,
                    run.total_tests,
                    run.passed,
                    run.failed,
                    run.skipped,
                    run.duration_seconds,
                ),
            )
            run_id = cursor.lastrowid

            # Update model last_tested
            conn.execute(
                """
                INSERT INTO models (name, last_tested)
                VALUES (?, ?)
                ON CONFLICT(name) DO UPDATE SET last_tested=excluded.last_tested
                """,
                (run.model_name, run.timestamp.isoformat()),
            )

            return run_id if run_id is not None else 0

    def add_test_results(self, results: List[TestResult]) -> None:
        """Add multiple test results.

        Args:
            results: List of TestResult objects to insert
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO test_results
                (run_id, test_name, test_status, score, question,
                 expected_answer, actual_answer, grading_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r.run_id,
                        r.test_name,
                        r.test_status,
                        r.score,
                        r.question,
                        r.expected_answer,
                        r.actual_answer,
                        r.grading_reason,
                    )
                    for r in results
                ],
            )

    def add_or_update_model(self, model: ModelInfo) -> None:
        """Add or update model metadata.

        Args:
            model: ModelInfo object with model details
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO models
                (name, full_name, organization, release_date, parameters, last_tested)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    full_name=COALESCE(excluded.full_name, models.full_name),
                    organization=COALESCE(excluded.organization, models.organization),
                    release_date=COALESCE(excluded.release_date, models.release_date),
                    parameters=COALESCE(excluded.parameters, models.parameters),
                    last_tested=COALESCE(excluded.last_tested, models.last_tested)
                """,
                (
                    model.name,
                    model.full_name,
                    model.organization,
                    model.release_date,
                    model.parameters,
                    model.last_tested.isoformat() if model.last_tested else None,
                ),
            )

    def get_model_performance(
        self, model_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get performance summary for models.

        Args:
            model_name: Optional model name to filter by

        Returns:
            List of performance statistics dictionaries
        """
        query = """
            SELECT
                model_name,
                COUNT(*) as total_runs,
                AVG(CAST(passed AS FLOAT) / total_tests * 100) as avg_pass_rate,
                SUM(passed) as total_passed,
                SUM(failed) as total_failed,
                AVG(duration_seconds) as avg_duration
            FROM test_runs
            WHERE 1=1
        """
        params = []

        if model_name:
            query += " AND model_name = ?"
            params.append(model_name)

        query += " GROUP BY model_name ORDER BY avg_pass_rate DESC"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_recent_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent test runs.

        Args:
            limit: Maximum number of runs to return

        Returns:
            List of recent test run dictionaries
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM test_runs
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_test_history(self, test_name: str) -> List[Dict[str, Any]]:
        """Get history of a specific test across runs.

        Args:
            test_name: Name of the test to query

        Returns:
            List of test execution history
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT
                    tr.*,
                    truns.model_name,
                    truns.timestamp,
                    truns.gitlab_commit
                FROM test_results tr
                JOIN test_runs truns ON tr.run_id = truns.id
                WHERE tr.test_name = ?
                ORDER BY truns.timestamp DESC
                """,
                (test_name,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def export_to_json(self, output_path: str) -> None:
        """Export database contents to JSON file.

        Args:
            output_path: Path to output JSON file
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            data = {
                "test_runs": [
                    dict(row)
                    for row in conn.execute("SELECT * FROM test_runs").fetchall()
                ],
                "test_results": [
                    dict(row)
                    for row in conn.execute("SELECT * FROM test_results").fetchall()
                ],
                "models": [
                    dict(row) for row in conn.execute("SELECT * FROM models").fetchall()
                ],
                "exported_at": datetime.now().isoformat(),
            }

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


def main():
    """CLI for database operations."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m rfc.test_database <command> [args]")
        print("Commands: init, stats, export")
        sys.exit(1)

    command = sys.argv[1]
    db = TestDatabase()

    if command == "init":
        print(f"Database initialized at: {db.db_path}")

    elif command == "stats":
        stats = db.get_model_performance()
        print("\nModel Performance Summary:")
        print("-" * 80)
        for stat in stats:
            print(
                f"{stat['model_name']:20} | "
                f"Runs: {stat['total_runs']:3} | "
                f"Pass Rate: {stat['avg_pass_rate']:.1f}% | "
                f"Avg Duration: {stat['avg_duration']:.1f}s"
            )

    elif command == "export":
        output = sys.argv[2] if len(sys.argv) > 2 else "test_history.json"
        db.export_to_json(output)
        print(f"Exported to: {output}")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
