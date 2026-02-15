"""Test results database manager for robotframework-chat.

Manages test result storage with support for SQLite (default)
and PostgreSQL (for Superset integration). Backend is selected
via DATABASE_URL environment variable or constructor parameter.

SQLite:      sqlite:///data/test_history.db  (default)
PostgreSQL:  postgresql://user:pass@host:5432/dbname
"""

import abc
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from sqlalchemy import (  # type: ignore[import-not-found]
        Column,
        DateTime,
        Float,
        ForeignKey,
        Index,
        Integer,
        MetaData,
        String,
        Table,
        Text,
        create_engine,
        text,
    )
    from sqlalchemy.engine import Engine  # type: ignore[import-not-found]

    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


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
    rfc_version: Optional[str] = None
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


class _Backend(abc.ABC):
    """Abstract interface shared by all database backends."""

    @abc.abstractmethod
    def add_test_run(self, run: TestRun) -> int: ...

    @abc.abstractmethod
    def add_test_results(self, results: List[TestResult]) -> None: ...

    @abc.abstractmethod
    def add_or_update_model(self, model: ModelInfo) -> None: ...

    @abc.abstractmethod
    def get_model_performance(
        self, model_name: Optional[str] = None
    ) -> List[Dict[str, Any]]: ...

    @abc.abstractmethod
    def get_recent_runs(self, limit: int = 10) -> List[Dict[str, Any]]: ...

    @abc.abstractmethod
    def get_test_history(self, test_name: str) -> List[Dict[str, Any]]: ...

    @abc.abstractmethod
    def export_to_json(self, output_path: str) -> None: ...


class _SQLiteBackend(_Backend):
    """SQLite backend using the stdlib sqlite3 module."""

    SCHEMA = """
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
        duration_seconds REAL,
        rfc_version TEXT
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
        FOREIGN KEY (run_id) REFERENCES test_runs(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS models (
        name TEXT PRIMARY KEY,
        full_name TEXT,
        organization TEXT,
        release_date TEXT,
        parameters TEXT,
        last_tested DATETIME
    );

    CREATE INDEX IF NOT EXISTS idx_test_runs_model ON test_runs(model_name);
    CREATE INDEX IF NOT EXISTS idx_test_runs_timestamp ON test_runs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_test_runs_suite ON test_runs(test_suite);
    CREATE INDEX IF NOT EXISTS idx_test_results_run_id ON test_results(run_id);
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.executescript(self.SCHEMA)

    def add_test_run(self, run: TestRun) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO test_runs
                (timestamp, model_name, model_release_date, model_parameters,
                 test_suite, gitlab_commit, gitlab_branch, gitlab_pipeline_url,
                 runner_id, runner_tags, total_tests, passed, failed, skipped,
                 duration_seconds, rfc_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    run.rfc_version,
                ),
            )
            run_id = cursor.lastrowid
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
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO models
                (name, full_name, organization, release_date, parameters,
                 last_tested)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    full_name=COALESCE(excluded.full_name, models.full_name),
                    organization=COALESCE(excluded.organization,
                                          models.organization),
                    release_date=COALESCE(excluded.release_date,
                                          models.release_date),
                    parameters=COALESCE(excluded.parameters, models.parameters),
                    last_tested=COALESCE(excluded.last_tested,
                                         models.last_tested)
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
        params: list[Any] = []
        if model_name:
            query += " AND model_name = ?"
            params.append(model_name)
        query += " GROUP BY model_name ORDER BY avg_pass_rate DESC"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_recent_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM test_runs ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_test_history(self, test_name: str) -> List[Dict[str, Any]]:
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


class _SQLAlchemyBackend(_Backend):
    """PostgreSQL/SQLAlchemy backend for Superset integration."""

    def __init__(self, database_url: str):
        self.engine: Engine = create_engine(database_url)
        self.metadata = MetaData()
        self._define_tables()
        self.metadata.create_all(self.engine)

    def _define_tables(self) -> None:
        self.test_runs = Table(
            "test_runs",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("timestamp", DateTime, nullable=False),
            Column("model_name", String(255), nullable=False),
            Column("model_release_date", String(255)),
            Column("model_parameters", String(255)),
            Column("test_suite", String(255), nullable=False),
            Column("gitlab_commit", String(255)),
            Column("gitlab_branch", String(255)),
            Column("gitlab_pipeline_url", Text),
            Column("runner_id", String(255)),
            Column("runner_tags", Text),
            Column("total_tests", Integer, default=0),
            Column("passed", Integer, default=0),
            Column("failed", Integer, default=0),
            Column("skipped", Integer, default=0),
            Column("duration_seconds", Float),
            Column("rfc_version", String(50)),
        )

        self.test_results = Table(
            "test_results",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column(
                "run_id",
                Integer,
                ForeignKey("test_runs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("test_name", String(255), nullable=False),
            Column("test_status", String(50), nullable=False),
            Column("score", Integer),
            Column("question", Text),
            Column("expected_answer", Text),
            Column("actual_answer", Text),
            Column("grading_reason", Text),
        )

        self.models = Table(
            "models",
            self.metadata,
            Column("name", String(255), primary_key=True),
            Column("full_name", String(255)),
            Column("organization", String(255)),
            Column("release_date", String(255)),
            Column("parameters", String(255)),
            Column("last_tested", DateTime),
        )

        Index("idx_test_runs_model", self.test_runs.c.model_name)
        Index("idx_test_runs_timestamp", self.test_runs.c.timestamp)
        Index("idx_test_runs_suite", self.test_runs.c.test_suite)
        Index("idx_test_results_run_id", self.test_results.c.run_id)

    def add_test_run(self, run: TestRun) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(
                self.test_runs.insert().values(
                    timestamp=run.timestamp,
                    model_name=run.model_name,
                    model_release_date=run.model_release_date,
                    model_parameters=run.model_parameters,
                    test_suite=run.test_suite,
                    gitlab_commit=run.gitlab_commit,
                    gitlab_branch=run.gitlab_branch,
                    gitlab_pipeline_url=run.gitlab_pipeline_url,
                    runner_id=run.runner_id,
                    runner_tags=run.runner_tags,
                    total_tests=run.total_tests,
                    passed=run.passed,
                    failed=run.failed,
                    skipped=run.skipped,
                    duration_seconds=run.duration_seconds,
                    rfc_version=run.rfc_version,
                )
            )
            run_id = result.inserted_primary_key[0]

            # Upsert model last_tested
            conn.execute(
                text(
                    """
                    INSERT INTO models (name, last_tested)
                    VALUES (:name, :last_tested)
                    ON CONFLICT(name)
                    DO UPDATE SET last_tested = EXCLUDED.last_tested
                    """
                ),
                {"name": run.model_name, "last_tested": run.timestamp},
            )
            return int(run_id)

    def add_test_results(self, results: List[TestResult]) -> None:
        if not results:
            return
        with self.engine.begin() as conn:
            conn.execute(
                self.test_results.insert(),
                [
                    {
                        "run_id": r.run_id,
                        "test_name": r.test_name,
                        "test_status": r.test_status,
                        "score": r.score,
                        "question": r.question,
                        "expected_answer": r.expected_answer,
                        "actual_answer": r.actual_answer,
                        "grading_reason": r.grading_reason,
                    }
                    for r in results
                ],
            )

    def add_or_update_model(self, model: ModelInfo) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO models
                    (name, full_name, organization, release_date, parameters,
                     last_tested)
                    VALUES (:name, :full_name, :organization, :release_date,
                            :parameters, :last_tested)
                    ON CONFLICT(name) DO UPDATE SET
                        full_name = COALESCE(EXCLUDED.full_name, models.full_name),
                        organization = COALESCE(EXCLUDED.organization,
                                                models.organization),
                        release_date = COALESCE(EXCLUDED.release_date,
                                                models.release_date),
                        parameters = COALESCE(EXCLUDED.parameters,
                                              models.parameters),
                        last_tested = COALESCE(EXCLUDED.last_tested,
                                               models.last_tested)
                    """
                ),
                {
                    "name": model.name,
                    "full_name": model.full_name,
                    "organization": model.organization,
                    "release_date": model.release_date,
                    "parameters": model.parameters,
                    "last_tested": (model.last_tested if model.last_tested else None),
                },
            )

    def get_model_performance(
        self, model_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
                model_name,
                COUNT(*) as total_runs,
                AVG(CAST(passed AS FLOAT) / total_tests * 100) as avg_pass_rate,
                SUM(passed) as total_passed,
                SUM(failed) as total_failed,
                AVG(duration_seconds) as avg_duration
            FROM test_runs
            WHERE total_tests > 0
        """
        params: dict[str, Any] = {}
        if model_name:
            query += " AND model_name = :model_name"
            params["model_name"] = model_name
        query += " GROUP BY model_name ORDER BY avg_pass_rate DESC"

        with self.engine.connect() as conn:
            result = conn.execute(text(query), params)
            return [dict(row._mapping) for row in result.fetchall()]

    def get_recent_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM test_runs ORDER BY timestamp DESC LIMIT :lim"),
                {"lim": limit},
            )
            return [dict(row._mapping) for row in result.fetchall()]

    def get_test_history(self, test_name: str) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT
                        tr.*,
                        truns.model_name,
                        truns.timestamp,
                        truns.gitlab_commit
                    FROM test_results tr
                    JOIN test_runs truns ON tr.run_id = truns.id
                    WHERE tr.test_name = :test_name
                    ORDER BY truns.timestamp DESC
                    """
                ),
                {"test_name": test_name},
            )
            return [dict(row._mapping) for row in result.fetchall()]

    def export_to_json(self, output_path: str) -> None:
        with self.engine.connect() as conn:
            data = {
                "test_runs": [
                    dict(row._mapping)
                    for row in conn.execute(text("SELECT * FROM test_runs")).fetchall()
                ],
                "test_results": [
                    dict(row._mapping)
                    for row in conn.execute(
                        text("SELECT * FROM test_results")
                    ).fetchall()
                ],
                "models": [
                    dict(row._mapping)
                    for row in conn.execute(text("SELECT * FROM models")).fetchall()
                ],
                "exported_at": datetime.now().isoformat(),
            }
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


class TestDatabase:
    """Manager for test results database.

    Supports SQLite (default) and PostgreSQL backends.
    Backend selection:
      - Set DATABASE_URL env var to a PostgreSQL connection string
      - Pass database_url to constructor
      - Falls back to SQLite at data/test_history.db
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        database_url: Optional[str] = None,
    ):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file (legacy parameter).
            database_url: SQLAlchemy database URL. Overrides db_path.
                          Also read from DATABASE_URL env var.
        """
        url = database_url or os.getenv("DATABASE_URL")
        self._backend: _Backend

        if url and not url.startswith("sqlite"):
            if not HAS_SQLALCHEMY:
                raise ImportError(
                    "sqlalchemy and psycopg2-binary are required for "
                    "PostgreSQL support. Install with: "
                    "uv sync --extra superset"
                )
            self._backend = _SQLAlchemyBackend(url)
            self.db_path = url
        else:
            # SQLite path
            if db_path is None and url and url.startswith("sqlite"):
                # Extract path from sqlite:///path URL
                db_path = url.replace("sqlite:///", "")
            if db_path is None:
                project_root = self._find_project_root()
                db_path = os.path.join(project_root, "data", "test_history.db")
            self._backend = _SQLiteBackend(db_path)
            self.db_path = db_path

    @staticmethod
    def _find_project_root() -> str:
        current = Path.cwd()
        while current != current.parent:
            if (current / ".git").exists():
                return str(current)
            current = current.parent
        return str(Path.cwd())

    def add_test_run(self, run: TestRun) -> int:
        return self._backend.add_test_run(run)

    def add_test_results(self, results: List[TestResult]) -> None:
        self._backend.add_test_results(results)

    def add_or_update_model(self, model: ModelInfo) -> None:
        self._backend.add_or_update_model(model)

    def get_model_performance(
        self, model_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        return self._backend.get_model_performance(model_name)

    def get_recent_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self._backend.get_recent_runs(limit)

    def get_test_history(self, test_name: str) -> List[Dict[str, Any]]:
        return self._backend.get_test_history(test_name)

    def export_to_json(self, output_path: str) -> None:
        self._backend.export_to_json(output_path)


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
