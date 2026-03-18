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
    hostname: str = ""
    rfc_version: str = ""
    output_xml_url: str = ""
    output_xml_gz: bytes = b""
    output_xml_source: str = ""
    temperature: float = 0.0
    seed: int = 0
    top_p: float = 0.0
    top_k: int = 0
    id: int = -1


@dataclass
class TestResult:
    """Represents an individual test case result."""

    run_id: int
    test_name: str
    test_status: str
    score: float = -1.0
    tags: str = ""
    question: str = ""
    expected_answer: str = ""
    actual_answer: str = ""
    grading_reason: str = ""
    rfc_version: str = ""
    tag_severity: str = ""
    tag_tier: int = -1
    tag_verify: str = ""
    thinking_text: str = ""
    thinking_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    accepted_prediction_tokens: int = 0
    rejected_prediction_tokens: int = 0
    num_ctx: int = 0
    num_predict: int = 0
    eval_count: int = 0
    eval_duration_ns: int = 0
    prompt_eval_count: int = 0
    prompt_eval_duration_ns: int = 0
    load_duration_ns: int = 0
    total_duration_ns: int = 0
    tokens_per_second: float = 0.0
    id: int = -1


@dataclass
class Model:
    """Represents an LLM model's metadata."""

    name: str
    sha256_digest: str = ""
    size_gb: float = 0.0
    quantization: str = ""
    architecture: str = ""
    context_length: int = 0
    family: str = ""


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

    @abc.abstractmethod
    def upsert_model(self, model: "Model") -> None: ...


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
        output_xml_source TEXT,
        temperature REAL,
        seed INTEGER,
        top_p REAL,
        top_k INTEGER
    );

    CREATE TABLE IF NOT EXISTS test_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        test_name TEXT NOT NULL,
        test_status TEXT NOT NULL,
        score REAL,
        tags TEXT,
        question TEXT,
        expected_answer TEXT,
        actual_answer TEXT,
        grading_reason TEXT,
        rfc_version TEXT,
        tag_severity TEXT,
        tag_tier INTEGER,
        tag_verify TEXT,
        thinking_text TEXT,
        thinking_tokens INTEGER,
        reasoning_tokens INTEGER,
        cached_tokens INTEGER,
        accepted_prediction_tokens INTEGER,
        rejected_prediction_tokens INTEGER,
        num_ctx INTEGER,
        num_predict INTEGER,
        eval_count INTEGER,
        eval_duration_ns INTEGER,
        prompt_eval_count INTEGER,
        prompt_eval_duration_ns INTEGER,
        load_duration_ns INTEGER,
        total_duration_ns INTEGER,
        tokens_per_second REAL,
        FOREIGN KEY (run_id) REFERENCES test_runs(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS models (
        name TEXT PRIMARY KEY,
        sha256_digest TEXT,
        size_gb REAL,
        quantization TEXT,
        architecture TEXT,
        context_length INTEGER,
        family TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_test_runs_model ON test_runs(model_name);
    CREATE INDEX IF NOT EXISTS idx_test_runs_timestamp ON test_runs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_test_runs_suite ON test_runs(test_suite);
    CREATE INDEX IF NOT EXISTS idx_test_results_run_id ON test_results(run_id);
    """

    _VIEW_SQL = """
    DROP VIEW IF EXISTS test_results_full;
    CREATE VIEW test_results_full AS
    SELECT
        tr.id AS result_id,
        tr.run_id,
        tr.test_name,
        tr.test_status,
        tr.score,
        tr.tags,
        tr.question,
        tr.expected_answer,
        tr.actual_answer,
        tr.grading_reason,
        tr.rfc_version,
        tr.tag_severity,
        tr.tag_tier,
        tr.tag_verify,
        tr.thinking_text,
        tr.thinking_tokens,
        tr.reasoning_tokens,
        tr.cached_tokens,
        tr.accepted_prediction_tokens,
        tr.rejected_prediction_tokens,
        tr.num_ctx,
        tr.num_predict,
        tr.eval_count,
        tr.eval_duration_ns,
        tr.prompt_eval_count,
        tr.prompt_eval_duration_ns,
        tr.load_duration_ns,
        tr.total_duration_ns,
        tr.tokens_per_second,
        r.timestamp,
        r.model_name,
        r.test_suite,
        r.total_tests,
        r.passed,
        r.failed,
        r.skipped,
        r.duration_seconds,
        r.git_commit,
        r.git_branch,
        r.hostname,
        r.output_xml_url,
        r.output_xml_source,
        r.temperature,
        r.seed,
        r.top_p,
        r.top_k
    FROM test_results tr
    JOIN test_runs r ON tr.run_id = r.id;
    """

    # SQLite migrations for existing databases (new columns added via ALTER TABLE)
    _SQLITE_MIGRATIONS = [
        "ALTER TABLE test_runs ADD COLUMN temperature REAL",
        "ALTER TABLE test_runs ADD COLUMN seed INTEGER",
        "ALTER TABLE test_runs ADD COLUMN top_p REAL",
        "ALTER TABLE test_runs ADD COLUMN top_k INTEGER",
        "ALTER TABLE test_results ADD COLUMN thinking_text TEXT",
        "ALTER TABLE test_results ADD COLUMN thinking_tokens INTEGER",
        "ALTER TABLE test_results ADD COLUMN num_ctx INTEGER",
        "ALTER TABLE test_results ADD COLUMN num_predict INTEGER",
        "ALTER TABLE test_results ADD COLUMN eval_count INTEGER",
        "ALTER TABLE test_results ADD COLUMN eval_duration_ns INTEGER",
        "ALTER TABLE test_results ADD COLUMN prompt_eval_count INTEGER",
        "ALTER TABLE test_results ADD COLUMN prompt_eval_duration_ns INTEGER",
        "ALTER TABLE test_results ADD COLUMN load_duration_ns INTEGER",
        "ALTER TABLE test_results ADD COLUMN total_duration_ns INTEGER",
        "ALTER TABLE test_results ADD COLUMN tokens_per_second REAL",
        "ALTER TABLE test_results ADD COLUMN reasoning_tokens INTEGER",
        "ALTER TABLE test_results ADD COLUMN cached_tokens INTEGER",
        "ALTER TABLE test_results ADD COLUMN accepted_prediction_tokens INTEGER",
        "ALTER TABLE test_results ADD COLUMN rejected_prediction_tokens INTEGER",
    ]

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.executescript(self.SCHEMA)
            # Run migrations for existing databases (idempotent)
            for sql in self._SQLITE_MIGRATIONS:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass  # Column already exists
            conn.executescript(self._VIEW_SQL)

    def add_test_run(self, run: TestRun) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO test_runs
                (timestamp, model_name, test_suite, total_tests, passed,
                 failed, skipped, duration_seconds, git_commit, git_branch,
                 hostname, rfc_version, output_xml_url, output_xml_gz,
                 output_xml_source, temperature, seed, top_p, top_k)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    run.temperature,
                    run.seed,
                    run.top_p,
                    run.top_k,
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
                (run_id, test_name, test_status, score, tags, question,
                 expected_answer, actual_answer, grading_reason,
                 rfc_version, tag_severity, tag_tier, tag_verify,
                 thinking_text, thinking_tokens,
                 reasoning_tokens, cached_tokens,
                 accepted_prediction_tokens, rejected_prediction_tokens,
                 num_ctx, num_predict,
                 eval_count, eval_duration_ns, prompt_eval_count,
                 prompt_eval_duration_ns, load_duration_ns,
                 total_duration_ns, tokens_per_second)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r.run_id,
                        r.test_name,
                        r.test_status,
                        r.score,
                        r.tags,
                        r.question,
                        r.expected_answer,
                        r.actual_answer,
                        r.grading_reason,
                        r.rfc_version,
                        r.tag_severity,
                        r.tag_tier,
                        r.tag_verify,
                        r.thinking_text,
                        r.thinking_tokens,
                        r.reasoning_tokens,
                        r.cached_tokens,
                        r.accepted_prediction_tokens,
                        r.rejected_prediction_tokens,
                        r.num_ctx,
                        r.num_predict,
                        r.eval_count,
                        r.eval_duration_ns,
                        r.prompt_eval_count,
                        r.prompt_eval_duration_ns,
                        r.load_duration_ns,
                        r.total_duration_ns,
                        r.tokens_per_second,
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

    def upsert_model(self, model: Model) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO models
                (name, sha256_digest, size_gb, quantization, architecture,
                 context_length, family)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model.name,
                    model.sha256_digest,
                    model.size_gb,
                    model.quantization,
                    model.architecture,
                    model.context_length,
                    model.family,
                ),
            )


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
        # Add tags column to test_results.
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS tags TEXT",
        # Add structured tag columns.
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS tag_severity VARCHAR(20)",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS tag_tier INTEGER",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS tag_verify VARCHAR(50)",
        # New columns: test_runs inference parameters.
        "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS temperature REAL",
        "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS seed INTEGER",
        "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS top_p REAL",
        "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS top_k INTEGER",
        # New columns: test_results thinking and performance metrics.
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS thinking_text TEXT",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS thinking_tokens INTEGER",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS num_ctx INTEGER",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS num_predict INTEGER",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS eval_count INTEGER",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS eval_duration_ns BIGINT",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS prompt_eval_count INTEGER",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS prompt_eval_duration_ns BIGINT",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS load_duration_ns BIGINT",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS total_duration_ns BIGINT",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS tokens_per_second REAL",
        # OpenAI token detail columns.
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS reasoning_tokens INTEGER",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS cached_tokens INTEGER",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS accepted_prediction_tokens INTEGER",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS rejected_prediction_tokens INTEGER",
        # Models table.
        """CREATE TABLE IF NOT EXISTS models (
            name TEXT PRIMARY KEY,
            sha256_digest TEXT,
            size_gb REAL,
            quantization TEXT,
            architecture TEXT,
            context_length INTEGER,
            family TEXT
        )""",
        # Migrate score column from INTEGER to REAL (float).
        "ALTER TABLE test_results ALTER COLUMN score TYPE REAL USING score::real",
        # Joined view for Superset — one flat dataset with all columns.
        """CREATE OR REPLACE VIEW test_results_full AS
        SELECT
            tr.id AS result_id,
            tr.run_id,
            tr.test_name,
            tr.test_status,
            tr.score,
            tr.tags,
            tr.question,
            tr.expected_answer,
            tr.actual_answer,
            tr.grading_reason,
            tr.rfc_version,
            tr.tag_severity,
            tr.tag_tier,
            tr.tag_verify,
            tr.thinking_text,
            tr.thinking_tokens,
            tr.num_ctx,
            tr.num_predict,
            tr.eval_count,
            tr.eval_duration_ns,
            tr.prompt_eval_count,
            tr.prompt_eval_duration_ns,
            tr.load_duration_ns,
            tr.total_duration_ns,
            tr.tokens_per_second,
            r.timestamp,
            r.model_name,
            r.test_suite,
            r.total_tests,
            r.passed,
            r.failed,
            r.skipped,
            r.duration_seconds,
            r.git_commit,
            r.git_branch,
            r.hostname,
            r.output_xml_url,
            r.output_xml_source,
            r.temperature,
            r.seed,
            r.top_p,
            r.top_k
        FROM test_results tr
        JOIN test_runs r ON tr.run_id = r.id""",
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
            Column("temperature", Float),
            Column("seed", Integer),
            Column("top_p", Float),
            Column("top_k", Integer),
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
            Column("score", Float),
            Column("tags", Text),
            Column("question", Text),
            Column("expected_answer", Text),
            Column("actual_answer", Text),
            Column("grading_reason", Text),
            Column("rfc_version", Text),
            Column("tag_severity", String(20)),
            Column("tag_tier", Integer),
            Column("tag_verify", String(50)),
            Column("thinking_text", Text),
            Column("thinking_tokens", Integer),
            Column("reasoning_tokens", Integer),
            Column("cached_tokens", Integer),
            Column("accepted_prediction_tokens", Integer),
            Column("rejected_prediction_tokens", Integer),
            Column("num_ctx", Integer),
            Column("num_predict", Integer),
            Column("eval_count", Integer),
            Column("eval_duration_ns", Integer),
            Column("prompt_eval_count", Integer),
            Column("prompt_eval_duration_ns", Integer),
            Column("load_duration_ns", Integer),
            Column("total_duration_ns", Integer),
            Column("tokens_per_second", Float),
            Index("idx_test_results_run_id", "run_id"),
        )

        self._models = Table(
            "models",
            self.metadata,
            Column("name", Text, primary_key=True),
            Column("sha256_digest", Text),
            Column("size_gb", Float),
            Column("quantization", Text),
            Column("architecture", Text),
            Column("context_length", Integer),
            Column("family", Text),
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
                    temperature=run.temperature,
                    seed=run.seed,
                    top_p=run.top_p,
                    top_k=run.top_k,
                )
            )
            pk = result.inserted_primary_key
            assert pk is not None, "INSERT did not return a primary key"
            return int(pk[0])

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
                        "tags": r.tags,
                        "question": r.question,
                        "expected_answer": r.expected_answer,
                        "actual_answer": r.actual_answer,
                        "grading_reason": r.grading_reason,
                        "rfc_version": r.rfc_version,
                        "tag_severity": r.tag_severity,
                        "tag_tier": r.tag_tier,
                        "tag_verify": r.tag_verify,
                        "thinking_text": r.thinking_text,
                        "thinking_tokens": r.thinking_tokens,
                        "reasoning_tokens": r.reasoning_tokens,
                        "cached_tokens": r.cached_tokens,
                        "accepted_prediction_tokens": r.accepted_prediction_tokens,
                        "rejected_prediction_tokens": r.rejected_prediction_tokens,
                        "num_ctx": r.num_ctx,
                        "num_predict": r.num_predict,
                        "eval_count": r.eval_count,
                        "eval_duration_ns": r.eval_duration_ns,
                        "prompt_eval_count": r.prompt_eval_count,
                        "prompt_eval_duration_ns": r.prompt_eval_duration_ns,
                        "load_duration_ns": r.load_duration_ns,
                        "total_duration_ns": r.total_duration_ns,
                        "tokens_per_second": r.tokens_per_second,
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

    def upsert_model(self, model: Model) -> None:
        with self.engine.begin() as conn:
            # Try update first, then insert
            result = conn.execute(
                self._models.update()
                .where(self._models.c.name == model.name)
                .values(
                    sha256_digest=model.sha256_digest,
                    size_gb=model.size_gb,
                    quantization=model.quantization,
                    architecture=model.architecture,
                    context_length=model.context_length,
                    family=model.family,
                )
            )
            if result.rowcount == 0:
                conn.execute(
                    self._models.insert().values(
                        name=model.name,
                        sha256_digest=model.sha256_digest,
                        size_gb=model.size_gb,
                        quantization=model.quantization,
                        architecture=model.architecture,
                        context_length=model.context_length,
                        family=model.family,
                    )
                )


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

    def upsert_model(self, model: Model) -> None:
        return self._backend.upsert_model(model)
