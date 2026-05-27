"""Test results database manager for robotframework-chat.

Manages test result storage with support for SQLite (default)
and PostgreSQL (for Superset integration). Backend is selected
via DATABASE_URL environment variable or constructor parameter.

Schema (4 tables):
    - ``test_runs``            — lean per-suite metrics
    - ``test_results``         — lean per-test metrics
    - ``test_run_artifacts``   — per-run heavy archive
      (gzip-compressed ``output.xml`` + source path)
    - ``test_result_artifacts`` — per-result heavy archive
      (question / expected_answer / actual_answer / grading_reason /
      thinking_text)

Dashboards query the lean tables directly. Superset drill-down joins
the archive tables via the ``test_results_full`` view (LEFT JOIN).

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
    """Lean per-suite metrics (heavy fields live in TestRunArtifact)."""

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
    session_id: str = ""
    model_harness: str = ""
    id: int = -1


@dataclass
class TestResult:
    """Lean per-test metrics (heavy fields live in TestResultArtifact)."""

    run_id: int
    test_name: str
    test_status: str
    score: float = -1.0
    tags: str = ""
    tag_severity: str = ""
    tag_tier: int = -1
    tag_verify: str = ""
    eval_count: int = 0
    thinking_tokens: int = 0
    id: int = -1


@dataclass
class TestRunArtifact:
    """Per-run heavy archive: output.xml gzip blob and its source path."""

    run_id: int
    output_xml_gz: bytes = b""
    output_xml_source: str = ""


@dataclass
class TestResultArtifact:
    """Per-result heavy archive: question/answer/grading/thinking text."""

    result_id: int
    question: str = ""
    expected_answer: str = ""
    actual_answer: str = ""
    grading_reason: str = ""
    thinking_text: str = ""


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


# Fields the archive row borrows from a test-case dict.  Shared between the
# Robot listener and the XML importer so both write the same columns and
# apply the same "all-empty → skip" policy.
_ARCHIVE_FIELDS: tuple[str, ...] = (
    "question",
    "expected_answer",
    "actual_answer",
    "grading_reason",
    "thinking_text",
)


def build_result_artifacts(
    test_cases: List[Dict[str, Any]],
    result_ids: List[int],
) -> List[TestResultArtifact]:
    """Build per-result archive rows from test-case dicts.

    ``result_ids`` must be positionally aligned with ``test_cases`` —
    i.e. ``result_ids[i]`` is the primary key for ``test_cases[i]``.

    A row is produced for every test case, including ones whose archive
    fields are all empty. A "PASS with no captured data" is itself a
    finding (it usually means the keyword vacuously passed without
    invoking the LLM, or the response capture path has a bug); silently
    dropping the row would hide that signal from Superset.

    Positional matching is mandatory: name-based matching would silently
    collapse duplicate test names (templated tests) onto a single id.
    """
    if len(test_cases) != len(result_ids):
        raise ValueError(
            f"test_cases ({len(test_cases)}) and result_ids ({len(result_ids)}) "
            "must have the same length"
        )
    artifacts: List[TestResultArtifact] = []
    for tc, result_id in zip(test_cases, result_ids):
        artifacts.append(
            TestResultArtifact(
                result_id=result_id,
                question=tc.get("question") or "",
                expected_answer=tc.get("expected_answer") or "",
                actual_answer=tc.get("actual_answer") or "",
                grading_reason=tc.get("grading_reason") or "",
                thinking_text=tc.get("thinking_text") or "",
            )
        )
    return artifacts


# Single source of truth for the ``test_results_full`` view body.  Both
# backends and ``superset/bootstrap_dashboards.py`` render a CREATE VIEW
# statement around this SELECT so the column set cannot drift.
TEST_RESULTS_FULL_VIEW_BODY: str = """\
SELECT
    tr.id AS result_id,
    tr.run_id,
    tr.test_name,
    tr.test_status,
    tr.score,
    tr.tags,
    tr.tag_severity,
    tr.tag_tier,
    tr.tag_verify,
    tr.eval_count,
    tr.thinking_tokens,
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
    r.rfc_version,
    r.session_id,
    r.model_harness,
    ra.output_xml_source,
    rsa.question,
    rsa.expected_answer,
    rsa.actual_answer,
    rsa.grading_reason,
    rsa.thinking_text
FROM test_results tr
JOIN test_runs r ON tr.run_id = r.id
LEFT JOIN test_run_artifacts ra ON ra.run_id = r.id
LEFT JOIN test_result_artifacts rsa ON rsa.result_id = tr.id"""


class _Backend(abc.ABC):
    """Abstract interface shared by all database backends."""

    @abc.abstractmethod
    def add_test_run(self, run: TestRun) -> int: ...

    @abc.abstractmethod
    def add_test_results(self, results: List[TestResult]) -> List[int]:
        """Bulk-insert test results and return their primary keys.

        Returned ids are positionally aligned with ``results`` so callers
        can attach per-result archive rows without a name-based lookup.
        """
        ...

    @abc.abstractmethod
    def add_test_run_artifact(self, artifact: TestRunArtifact) -> None: ...

    @abc.abstractmethod
    def add_test_result_artifacts(
        self, artifacts: List[TestResultArtifact]
    ) -> None: ...

    @abc.abstractmethod
    def get_test_run_artifact(self, run_id: int) -> Optional[Dict[str, Any]]: ...

    @abc.abstractmethod
    def get_test_result_artifact(self, result_id: int) -> Optional[Dict[str, Any]]: ...

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
    def update_output_xml(self, run_id: int, output_xml_gz: bytes) -> None: ...

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
        session_id TEXT,
        model_harness TEXT
    );

    CREATE TABLE IF NOT EXISTS test_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        test_name TEXT NOT NULL,
        test_status TEXT NOT NULL,
        score REAL,
        tags TEXT,
        tag_severity TEXT,
        tag_tier INTEGER,
        tag_verify TEXT,
        eval_count INTEGER,
        thinking_tokens INTEGER,
        FOREIGN KEY (run_id) REFERENCES test_runs(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS test_run_artifacts (
        run_id INTEGER PRIMARY KEY,
        output_xml_gz BLOB,
        output_xml_source TEXT,
        FOREIGN KEY (run_id) REFERENCES test_runs(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS test_result_artifacts (
        result_id INTEGER PRIMARY KEY,
        question TEXT,
        expected_answer TEXT,
        actual_answer TEXT,
        grading_reason TEXT,
        thinking_text TEXT,
        FOREIGN KEY (result_id) REFERENCES test_results(id) ON DELETE CASCADE
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

    _VIEW_SQL = (
        "DROP VIEW IF EXISTS test_results_full;\n"
        f"CREATE VIEW test_results_full AS\n{TEST_RESULTS_FULL_VIEW_BODY};\n"
    )

    # Idempotent migrations that drop legacy columns from upgrading databases.
    # SQLite supports DROP COLUMN in 3.35+; older versions will raise and we
    # swallow the error (new databases never had these columns anyway).
    _SQLITE_MIGRATIONS = [
        "ALTER TABLE test_runs DROP COLUMN temperature",
        "ALTER TABLE test_runs DROP COLUMN seed",
        "ALTER TABLE test_runs DROP COLUMN top_p",
        "ALTER TABLE test_runs DROP COLUMN top_k",
        "ALTER TABLE test_runs DROP COLUMN output_xml_gz",
        "ALTER TABLE test_runs DROP COLUMN output_xml_url",
        "ALTER TABLE test_runs DROP COLUMN output_xml_source",
        "ALTER TABLE test_results DROP COLUMN question",
        "ALTER TABLE test_results DROP COLUMN expected_answer",
        "ALTER TABLE test_results DROP COLUMN actual_answer",
        "ALTER TABLE test_results DROP COLUMN grading_reason",
        "ALTER TABLE test_results DROP COLUMN thinking_text",
        "ALTER TABLE test_results DROP COLUMN rfc_version",
        "ALTER TABLE test_results DROP COLUMN reasoning_tokens",
        "ALTER TABLE test_results DROP COLUMN cached_tokens",
        "ALTER TABLE test_results DROP COLUMN accepted_prediction_tokens",
        "ALTER TABLE test_results DROP COLUMN rejected_prediction_tokens",
        "ALTER TABLE test_results DROP COLUMN num_ctx",
        "ALTER TABLE test_results DROP COLUMN num_predict",
        "ALTER TABLE test_results DROP COLUMN eval_duration_ns",
        "ALTER TABLE test_results DROP COLUMN prompt_eval_count",
        "ALTER TABLE test_results DROP COLUMN prompt_eval_duration_ns",
        "ALTER TABLE test_results DROP COLUMN load_duration_ns",
        "ALTER TABLE test_results DROP COLUMN total_duration_ns",
        "ALTER TABLE test_results DROP COLUMN tokens_per_second",
        "ALTER TABLE test_results DROP COLUMN token_retry_count",
        "ALTER TABLE test_results DROP COLUMN token_retry_max_tokens",
        # Issue #350: link test_runs to the active agentic harness session.
        "ALTER TABLE test_runs ADD COLUMN session_id TEXT",
        # Issue #350: record the harness driving the test (e.g. claude-opus-4-7[1m]).
        "ALTER TABLE test_runs ADD COLUMN model_harness TEXT",
        # Databases predating the watermark 5-tuple lack hostname; the
        # test_results_full view selects r.hostname, so add it on upgrade.
        "ALTER TABLE test_runs ADD COLUMN hostname TEXT",
    ]

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.executescript(self.SCHEMA)
            # Drop legacy columns from upgrading databases (idempotent).
            for sql in self._SQLITE_MIGRATIONS:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass  # Column absent or SQLite too old for DROP COLUMN.
            conn.executescript(self._VIEW_SQL)

    def add_test_run(self, run: TestRun) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO test_runs
                (timestamp, model_name, test_suite, total_tests, passed,
                 failed, skipped, duration_seconds, git_commit, git_branch,
                 hostname, rfc_version, session_id, model_harness)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    run.session_id or None,
                    run.model_harness or None,
                ),
            )
            run_id = cursor.lastrowid
            return run_id if run_id is not None else 0

    def add_test_results(self, results: List[TestResult]) -> List[int]:
        if not results:
            return []
        # executemany() cannot report individual ``lastrowid`` values, so
        # loop with per-row execute().  All inserts share one transaction
        # via the context manager, keeping write cost low.
        with sqlite3.connect(self.db_path) as conn:
            inserted_ids: List[int] = []
            for r in results:
                cursor = conn.execute(
                    """
                    INSERT INTO test_results
                    (run_id, test_name, test_status, score, tags,
                     tag_severity, tag_tier, tag_verify,
                     eval_count, thinking_tokens)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r.run_id,
                        r.test_name,
                        r.test_status,
                        r.score,
                        r.tags,
                        r.tag_severity,
                        r.tag_tier,
                        r.tag_verify,
                        r.eval_count,
                        r.thinking_tokens,
                    ),
                )
                row_id = cursor.lastrowid
                assert row_id is not None, "INSERT did not return a row id"
                inserted_ids.append(int(row_id))
            return inserted_ids

    def add_test_run_artifact(self, artifact: TestRunArtifact) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO test_run_artifacts
                (run_id, output_xml_gz, output_xml_source)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    output_xml_gz = excluded.output_xml_gz,
                    output_xml_source = excluded.output_xml_source
                """,
                (
                    artifact.run_id,
                    artifact.output_xml_gz,
                    artifact.output_xml_source,
                ),
            )

    def add_test_result_artifacts(self, artifacts: List[TestResultArtifact]) -> None:
        if not artifacts:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO test_result_artifacts
                (result_id, question, expected_answer, actual_answer,
                 grading_reason, thinking_text)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(result_id) DO UPDATE SET
                    question = excluded.question,
                    expected_answer = excluded.expected_answer,
                    actual_answer = excluded.actual_answer,
                    grading_reason = excluded.grading_reason,
                    thinking_text = excluded.thinking_text
                """,
                [
                    (
                        a.result_id,
                        a.question,
                        a.expected_answer,
                        a.actual_answer,
                        a.grading_reason,
                        a.thinking_text,
                    )
                    for a in artifacts
                ],
            )

    def get_test_run_artifact(self, run_id: int) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM test_run_artifacts WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_test_result_artifact(self, result_id: int) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM test_result_artifacts WHERE result_id = ?",
                (result_id,),
            ).fetchone()
            return dict(row) if row else None

    def update_output_xml(self, run_id: int, output_xml_gz: bytes) -> None:
        """Upsert the per-run archive row with the given gzip blob.

        Silently no-ops on a missing run_id via ``WHERE EXISTS`` — SQLite
        does not enforce foreign keys by default, so relying on the FK
        alone would create orphan artifact rows.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO test_run_artifacts (run_id, output_xml_gz)
                SELECT ?, ?
                WHERE EXISTS (SELECT 1 FROM test_runs WHERE id = ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    output_xml_gz = excluded.output_xml_gz
                """,
                (run_id, output_xml_gz, run_id),
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

    # Idempotent DDL migrations run after create_all().  They first drop
    # the legacy view, then drop the heavy columns, then (re)create the
    # archive tables, and finally rebuild the denormalised view.
    _PG_MIGRATIONS: list[str] = [
        # Drop old tables from pre-redesign schema.
        "DROP TABLE IF EXISTS keyword_results CASCADE",
        "DROP TABLE IF EXISTS ollama_metrics CASCADE",
        "DROP TABLE IF EXISTS host_info CASCADE",
        "DROP TABLE IF EXISTS pipeline_results CASCADE",
        "DROP TABLE IF EXISTS robot_dry_run_results CASCADE",
        "DROP TABLE IF EXISTS analytics_model_trends CASCADE",
        "DROP TABLE IF EXISTS analytics_test_stability CASCADE",
        "DROP TABLE IF EXISTS analytics_model_comparison CASCADE",
        "DROP TABLE IF EXISTS analytics_regression_alerts CASCADE",
        "DROP TABLE IF EXISTS analytics_performance_fingerprints CASCADE",
        # The denormalised view depends on many of the columns we are
        # about to drop, so take it down first.
        "DROP VIEW IF EXISTS test_results_full",
        # Drop inference-parameter columns from test_runs (never queried).
        "ALTER TABLE test_runs DROP COLUMN IF EXISTS temperature",
        "ALTER TABLE test_runs DROP COLUMN IF EXISTS seed",
        "ALTER TABLE test_runs DROP COLUMN IF EXISTS top_p",
        "ALTER TABLE test_runs DROP COLUMN IF EXISTS top_k",
        # Drop output.xml columns from test_runs (moved to test_run_artifacts).
        "ALTER TABLE test_runs DROP COLUMN IF EXISTS output_xml_gz",
        "ALTER TABLE test_runs DROP COLUMN IF EXISTS output_xml_url",
        "ALTER TABLE test_runs DROP COLUMN IF EXISTS output_xml_source",
        # Drop heavy text columns from test_results (moved to
        # test_result_artifacts).
        "ALTER TABLE test_results DROP COLUMN IF EXISTS question",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS expected_answer",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS actual_answer",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS grading_reason",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS thinking_text",
        # Drop duplicated version column (lives on test_runs only now).
        "ALTER TABLE test_results DROP COLUMN IF EXISTS rfc_version",
        # Drop never-queried numeric metrics from test_results.
        "ALTER TABLE test_results DROP COLUMN IF EXISTS reasoning_tokens",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS cached_tokens",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS accepted_prediction_tokens",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS rejected_prediction_tokens",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS num_ctx",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS num_predict",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS eval_duration_ns",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS prompt_eval_count",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS prompt_eval_duration_ns",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS load_duration_ns",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS total_duration_ns",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS tokens_per_second",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS token_retry_count",
        "ALTER TABLE test_results DROP COLUMN IF EXISTS token_retry_max_tokens",
        # Ensure structured tag columns are present (for databases that
        # were created before the tag-split migration).
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS tags TEXT",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS tag_severity VARCHAR(20)",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS tag_tier INTEGER",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS tag_verify VARCHAR(50)",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS eval_count INTEGER",
        "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS thinking_tokens INTEGER",
        # Archive tables.
        """CREATE TABLE IF NOT EXISTS test_run_artifacts (
            run_id INTEGER PRIMARY KEY REFERENCES test_runs(id)
                ON DELETE CASCADE,
            output_xml_gz BYTEA,
            output_xml_source TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS test_result_artifacts (
            result_id INTEGER PRIMARY KEY REFERENCES test_results(id)
                ON DELETE CASCADE,
            question TEXT,
            expected_answer TEXT,
            actual_answer TEXT,
            grading_reason TEXT,
            thinking_text TEXT
        )""",
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
        # Issue #350: link test_runs to the active agentic harness session.
        "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS session_id TEXT",
        # Issue #350: record the harness driving the test (e.g. claude-opus-4-7[1m]).
        "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS model_harness TEXT",
        # Joined view for Superset — lean columns + archive LEFT JOIN.
        f"CREATE VIEW test_results_full AS {TEST_RESULTS_FULL_VIEW_BODY}",
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
            Column("session_id", String, nullable=True),
            Column("model_harness", String, nullable=True),
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
            Column("tag_severity", String(20)),
            Column("tag_tier", Integer),
            Column("tag_verify", String(50)),
            Column("eval_count", Integer),
            Column("thinking_tokens", Integer),
            Index("idx_test_results_run_id", "run_id"),
        )

        self._test_run_artifacts = Table(
            "test_run_artifacts",
            self.metadata,
            Column(
                "run_id",
                Integer,
                ForeignKey("test_runs.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            Column("output_xml_gz", LargeBinary),
            Column("output_xml_source", Text),
        )

        self._test_result_artifacts = Table(
            "test_result_artifacts",
            self.metadata,
            Column(
                "result_id",
                Integer,
                ForeignKey("test_results.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            Column("question", Text),
            Column("expected_answer", Text),
            Column("actual_answer", Text),
            Column("grading_reason", Text),
            Column("thinking_text", Text),
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
                    session_id=run.session_id or None,
                    model_harness=run.model_harness or None,
                )
            )
            pk = result.inserted_primary_key
            assert pk is not None, "INSERT did not return a primary key"
            return int(pk[0])

    def add_test_results(self, results: List[TestResult]) -> List[int]:
        if not results:
            return []
        # PG supports RETURNING with multi-row inserts via SQLAlchemy 2.0's
        # insertmanyvalues; rows come back in the same order we submitted.
        payload = [
            {
                "run_id": r.run_id,
                "test_name": r.test_name,
                "test_status": r.test_status,
                "score": r.score,
                "tags": r.tags,
                "tag_severity": r.tag_severity,
                "tag_tier": r.tag_tier,
                "tag_verify": r.tag_verify,
                "eval_count": r.eval_count,
                "thinking_tokens": r.thinking_tokens,
            }
            for r in results
        ]
        with self.engine.begin() as conn:
            result = conn.execute(
                self._test_results.insert().returning(self._test_results.c.id),
                payload,
            )
            return [int(row.id) for row in result]

    def add_test_run_artifact(self, artifact: TestRunArtifact) -> None:
        # PostgreSQL ON CONFLICT syntax — we deliberately do not use
        # SQLAlchemy Core Postgres dialect helpers to keep this module
        # dialect-agnostic at import time.
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO test_run_artifacts
                        (run_id, output_xml_gz, output_xml_source)
                    VALUES (:run_id, :gz, :src)
                    ON CONFLICT (run_id) DO UPDATE SET
                        output_xml_gz = EXCLUDED.output_xml_gz,
                        output_xml_source = EXCLUDED.output_xml_source
                    """
                ),
                {
                    "run_id": artifact.run_id,
                    "gz": artifact.output_xml_gz,
                    "src": artifact.output_xml_source,
                },
            )

    def add_test_result_artifacts(self, artifacts: List[TestResultArtifact]) -> None:
        if not artifacts:
            return
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO test_result_artifacts
                        (result_id, question, expected_answer, actual_answer,
                         grading_reason, thinking_text)
                    VALUES (:result_id, :question, :expected_answer,
                            :actual_answer, :grading_reason, :thinking_text)
                    ON CONFLICT (result_id) DO UPDATE SET
                        question = EXCLUDED.question,
                        expected_answer = EXCLUDED.expected_answer,
                        actual_answer = EXCLUDED.actual_answer,
                        grading_reason = EXCLUDED.grading_reason,
                        thinking_text = EXCLUDED.thinking_text
                    """
                ),
                [
                    {
                        "result_id": a.result_id,
                        "question": a.question,
                        "expected_answer": a.expected_answer,
                        "actual_answer": a.actual_answer,
                        "grading_reason": a.grading_reason,
                        "thinking_text": a.thinking_text,
                    }
                    for a in artifacts
                ],
            )

    def get_test_run_artifact(self, run_id: int) -> Optional[Dict[str, Any]]:
        with self.engine.connect() as conn:
            row = conn.execute(
                self._test_run_artifacts.select().where(
                    self._test_run_artifacts.c.run_id == run_id
                )
            ).fetchone()
            return dict(row._mapping) if row else None

    def get_test_result_artifact(self, result_id: int) -> Optional[Dict[str, Any]]:
        with self.engine.connect() as conn:
            row = conn.execute(
                self._test_result_artifacts.select().where(
                    self._test_result_artifacts.c.result_id == result_id
                )
            ).fetchone()
            return dict(row._mapping) if row else None

    def update_output_xml(self, run_id: int, output_xml_gz: bytes) -> None:
        """Upsert the per-run archive row with the given gzip blob.

        ``WHERE EXISTS`` gives SQLite-identical "silently no-op if the
        run is missing" semantics while staying in a single round trip.
        """
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO test_run_artifacts (run_id, output_xml_gz)
                    SELECT :run_id, :gz
                    WHERE EXISTS (SELECT 1 FROM test_runs WHERE id = :run_id)
                    ON CONFLICT (run_id) DO UPDATE SET
                        output_xml_gz = EXCLUDED.output_xml_gz
                    """
                ),
                {"run_id": run_id, "gz": output_xml_gz},
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
                    from .exceptions import MissingDependencyError

                    raise MissingDependencyError(
                        package="sqlalchemy",
                        install_hint="uv sync --extra superset",
                    )
            else:
                from .exceptions import MissingEnvironmentError

                raise MissingEnvironmentError(variable="DATABASE_URL")

    def add_test_run(self, run: TestRun) -> int:
        return self._backend.add_test_run(run)

    def add_test_results(self, results: List[TestResult]) -> List[int]:
        return self._backend.add_test_results(results)

    def add_test_run_artifact(self, artifact: TestRunArtifact) -> None:
        self._backend.add_test_run_artifact(artifact)

    def add_test_result_artifacts(self, artifacts: List[TestResultArtifact]) -> None:
        self._backend.add_test_result_artifacts(artifacts)

    def get_test_run_artifact(self, run_id: int) -> Optional[Dict[str, Any]]:
        return self._backend.get_test_run_artifact(run_id)

    def get_test_result_artifact(self, result_id: int) -> Optional[Dict[str, Any]]:
        return self._backend.get_test_result_artifact(result_id)

    def update_output_xml(self, run_id: int, output_xml_gz: bytes) -> None:
        self._backend.update_output_xml(run_id, output_xml_gz)

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
