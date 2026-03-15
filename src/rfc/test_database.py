"""Test results database manager for robotframework-chat.

Manages test result storage with support for SQLite (default)
and PostgreSQL (for Superset integration). Backend is selected
via DATABASE_URL environment variable or constructor parameter.

Schema: 2 tables (test_runs + test_results). output.xml is the
source of truth — the database stores a gzip-compressed copy and
an HTTP URL for web access.

SQLite:      sqlite:///data/test_history.db  (default)
PostgreSQL:  postgresql://user:pass@host:5433/dbname
"""

import abc
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from sqlalchemy import (  # type: ignore[import-not-found]
        Column,
        DateTime,
        Float,
        ForeignKey,
        Index,
        Integer,
        LargeBinary,
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
    """Represents a single test run/suite execution."""

    timestamp: datetime
    model_name: str
    test_suite: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    duration_seconds: float
    git_commit: str = ""
    git_branch: str = ""
    hostname: Optional[str] = None
    rfc_version: Optional[str] = None
    output_xml_url: Optional[str] = None
    output_xml_gz: Optional[bytes] = None
    output_xml_source: Optional[str] = None
    id: Optional[int] = None


@dataclass
class TestResult:
    """Represents an individual test case result."""

    run_id: int
    test_name: str
    test_status: str
    score: Optional[int] = None
    question: Optional[str] = None
    expected_answer: Optional[str] = None
    actual_answer: Optional[str] = None
    grading_reason: Optional[str] = None
    rfc_version: Optional[str] = None
    id: Optional[int] = None


class _Backend(abc.ABC):
    """Abstract interface shared by all database backends."""

    @abc.abstractmethod
    def add_test_run(self, run: TestRun) -> int: ...

    @abc.abstractmethod
    def add_test_results(self, results: List[TestResult]) -> None: ...

    @abc.abstractmethod
    def get_recent_runs(self, limit: int = 10) -> List[Dict[str, Any]]: ...

    @abc.abstractmethod
    def get_test_history(self, test_name: str) -> List[Dict[str, Any]]: ...

    @abc.abstractmethod
    def export_to_json(self, output_path: str) -> None: ...

    @abc.abstractmethod
    def get_version(self) -> str: ...

    @abc.abstractmethod
    def get_table_row_count(self, table_name: str) -> int: ...


class _SQLiteBackend(_Backend):
    """SQLite backend using the stdlib sqlite3 module."""

    SCHEMA = """
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
        git_commit TEXT,
        git_branch TEXT,
        hostname TEXT,
        rfc_version TEXT,
        output_xml_url TEXT,
        output_xml_gz BLOB,
        output_xml_source TEXT
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
        FOREIGN KEY (run_id) REFERENCES test_runs(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_test_runs_model ON test_runs(model_name);
    CREATE INDEX IF NOT EXISTS idx_test_runs_timestamp ON test_runs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_test_runs_suite ON test_runs(test_suite);
    CREATE INDEX IF NOT EXISTS idx_test_results_run_id ON test_results(run_id);
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.executescript(self.SCHEMA)

    def add_test_run(self, run: TestRun) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO test_runs
                (timestamp, model_name, test_suite, total_tests, passed,
                 failed, skipped, duration_seconds, git_commit, git_branch,
                 hostname, rfc_version, output_xml_url, output_xml_gz,
                 output_xml_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.timestamp.isoformat(),
                    run.model_name,
                    run.test_suite,
                    run.total_tests,
                    run.passed,
                    run.failed,
                    run.skipped,
                    run.duration_seconds,
                    run.git_commit,
                    run.git_branch,
                    run.hostname,
                    run.rfc_version,
                    run.output_xml_url,
                    run.output_xml_gz,
                    run.output_xml_source,
                ),
            )
            run_id = cursor.lastrowid
            return run_id if run_id is not None else 0

    def add_test_results(self, results: List[TestResult]) -> None:
        if not results:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO test_results
                (run_id, test_name, test_status, score, question,
                 expected_answer, actual_answer, grading_reason,
                 rfc_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        r.rfc_version,
                    )
                    for r in results
                ],
            )

    def get_recent_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM test_runs ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_test_history(self, test_name: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT tr.*, r.model_name, r.test_suite, r.timestamp AS run_timestamp
                FROM test_results tr
                JOIN test_runs r ON tr.run_id = r.id
                WHERE tr.test_name = ?
                ORDER BY r.timestamp DESC
                """,
                (test_name,),
            ).fetchall()
            return [dict(row) for row in rows]

    def export_to_json(self, output_path: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            runs = conn.execute(
                "SELECT * FROM test_runs ORDER BY timestamp DESC"
            ).fetchall()

            data: List[Dict[str, Any]] = []
            for run in runs:
                run_dict = dict(run)
                # Remove binary blob from JSON export
                run_dict.pop("output_xml_gz", None)
                results = conn.execute(
                    "SELECT * FROM test_results WHERE run_id = ?",
                    (run_dict["id"],),
                ).fetchall()
                run_dict["test_results"] = [dict(r) for r in results]
                data.append(run_dict)

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def get_version(self) -> str:
        with sqlite3.connect(self.db_path) as conn:
            return str(conn.execute("SELECT sqlite_version()").fetchone()[0])

    def get_table_row_count(self, table_name: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table_name}"  # noqa: S608
            ).fetchone()
            return int(row[0]) if row else 0


class _SQLAlchemyBackend(_Backend):
    """PostgreSQL backend using SQLAlchemy."""

    # Idempotent DDL migrations run after create_all().
    _PG_MIGRATIONS: list[str] = [
        # Drop old tables from pre-redesign schema.
        "DROP TABLE IF EXISTS keyword_results CASCADE",
        "DROP TABLE IF EXISTS ollama_metrics CASCADE",
        "DROP TABLE IF EXISTS host_info CASCADE",
        "DROP TABLE IF EXISTS models CASCADE",
        "DROP TABLE IF EXISTS pipeline_results CASCADE",
        "DROP TABLE IF EXISTS robot_dry_run_results CASCADE",
        "DROP TABLE IF EXISTS analytics_model_trends CASCADE",
        "DROP TABLE IF EXISTS analytics_test_stability CASCADE",
        "DROP TABLE IF EXISTS analytics_model_comparison CASCADE",
        "DROP TABLE IF EXISTS analytics_regression_alerts CASCADE",
        "DROP TABLE IF EXISTS analytics_performance_fingerprints CASCADE",
        # Add columns that may be missing from pre-existing test_runs tables.
        "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS output_xml_url TEXT",
        "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS output_xml_gz BYTEA",
        "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS output_xml_source TEXT",
    ]

    def __init__(self, database_url: str):
        self.engine: Engine = create_engine(database_url)
        self.metadata = MetaData()
        self._define_tables()

        try:
            self.metadata.create_all(self.engine)
        except Exception:
            logger.warning("create_all() failed; running migrations anyway")

        self._run_migrations()

    def _define_tables(self) -> None:
        self._test_runs = Table(
            "test_runs",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("timestamp", DateTime, nullable=False),
            Column("model_name", String, nullable=False),
            Column("test_suite", String, nullable=False),
            Column("total_tests", Integer),
            Column("passed", Integer),
            Column("failed", Integer),
            Column("skipped", Integer),
            Column("duration_seconds", Float),
            Column("git_commit", Text),
            Column("git_branch", Text),
            Column("hostname", Text),
            Column("rfc_version", Text),
            Column("output_xml_url", Text),
            Column("output_xml_gz", LargeBinary),
            Column("output_xml_source", Text),
            Index("idx_test_runs_model", "model_name"),
            Index("idx_test_runs_timestamp", "timestamp"),
            Index("idx_test_runs_suite", "test_suite"),
        )

        self._test_results = Table(
            "test_results",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column(
                "run_id",
                Integer,
                ForeignKey("test_runs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("test_name", String, nullable=False),
            Column("test_status", String, nullable=False),
            Column("score", Integer),
            Column("question", Text),
            Column("expected_answer", Text),
            Column("actual_answer", Text),
            Column("grading_reason", Text),
            Column("rfc_version", Text),
            Index("idx_test_results_run_id", "run_id"),
        )

    def _run_migrations(self) -> None:
        for sql in self._PG_MIGRATIONS:
            try:
                with self.engine.begin() as conn:
                    conn.execute(text(sql))
            except Exception:
                pass  # Migration already applied or not applicable

    def add_test_run(self, run: TestRun) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(
                self._test_runs.insert().values(
                    timestamp=run.timestamp,
                    model_name=run.model_name,
                    test_suite=run.test_suite,
                    total_tests=run.total_tests,
                    passed=run.passed,
                    failed=run.failed,
                    skipped=run.skipped,
                    duration_seconds=run.duration_seconds,
                    git_commit=run.git_commit,
                    git_branch=run.git_branch,
                    hostname=run.hostname,
                    rfc_version=run.rfc_version,
                    output_xml_url=run.output_xml_url,
                    output_xml_gz=run.output_xml_gz,
                    output_xml_source=run.output_xml_source,
                )
            )
            return int(result.inserted_primary_key[0])

    def add_test_results(self, results: List[TestResult]) -> None:
        if not results:
            return
        with self.engine.begin() as conn:
            conn.execute(
                self._test_results.insert(),
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
                        "rfc_version": r.rfc_version,
                    }
                    for r in results
                ],
            )

    def get_recent_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            result = conn.execute(
                self._test_runs.select()
                .order_by(self._test_runs.c.timestamp.desc())
                .limit(limit)
            )
            return [dict(row._mapping) for row in result]

    def get_test_history(self, test_name: str) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            j = self._test_results.join(
                self._test_runs,
                self._test_results.c.run_id == self._test_runs.c.id,
            )
            result = conn.execute(
                self._test_results.select()
                .select_from(j)
                .where(self._test_results.c.test_name == test_name)
                .order_by(self._test_runs.c.timestamp.desc())
            )
            return [dict(row._mapping) for row in result]

    def export_to_json(self, output_path: str) -> None:
        runs = self.get_recent_runs(limit=10000)
        for run in runs:
            run.pop("output_xml_gz", None)
        with open(output_path, "w") as f:
            json.dump(runs, f, indent=2, default=str)

    def get_version(self) -> str:
        with self.engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            return str(result.scalar())

    def get_table_row_count(self, table_name: str) -> int:
        with self.engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))  # noqa: S608
            return int(result.scalar() or 0)


class TestDatabase:
    """Facade that selects the correct backend at construction time.

    If ``database_url`` is provided, uses SQLAlchemy (for PostgreSQL).
    If ``db_path`` is provided, uses SQLite directly.
    Otherwise, reads ``DATABASE_URL`` from the environment.
    """

    def __init__(
        self,
        *,
        db_path: Optional[str] = None,
        database_url: Optional[str] = None,
    ):
        if db_path:
            self._backend: _Backend = _SQLiteBackend(db_path)
        elif database_url:
            if database_url.startswith("sqlite:///"):
                sqlite_path = database_url.replace("sqlite:///", "")
                self._backend = _SQLiteBackend(sqlite_path)
            elif HAS_SQLALCHEMY:
                self._backend = _SQLAlchemyBackend(database_url)
            else:
                raise RuntimeError(
                    "SQLAlchemy is required for PostgreSQL. "
                    "Install with: uv sync --extra superset"
                )
        else:
            env_url = os.environ.get("DATABASE_URL")
            if env_url:
                if env_url.startswith("sqlite:///"):
                    sqlite_path = env_url.replace("sqlite:///", "")
                    self._backend = _SQLiteBackend(sqlite_path)
                elif HAS_SQLALCHEMY:
                    self._backend = _SQLAlchemyBackend(env_url)
                else:
                    raise RuntimeError(
                        "SQLAlchemy is required for PostgreSQL. "
                        "Install with: uv sync --extra superset"
                    )
            else:
                raise RuntimeError(
                    "DATABASE_URL is not set and no db_path provided. "
                    "Set DATABASE_URL or pass db_path explicitly."
                )

    def add_test_run(self, run: TestRun) -> int:
        return self._backend.add_test_run(run)

    def add_test_results(self, results: List[TestResult]) -> None:
        self._backend.add_test_results(results)

    def get_recent_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self._backend.get_recent_runs(limit)

    def get_test_history(self, test_name: str) -> List[Dict[str, Any]]:
        return self._backend.get_test_history(test_name)

    def export_to_json(self, output_path: str) -> None:
        self._backend.export_to_json(output_path)

    def get_version(self) -> str:
        return self._backend.get_version()

    def get_table_row_count(self, table_name: str) -> int:
        return self._backend.get_table_row_count(table_name)
