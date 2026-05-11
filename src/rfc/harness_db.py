"""HarnessDatabase: schema spine for the Agentic Stack Tracker.

Mirrors the shape of src/rfc/test_database.py. SQLite is always
available; SQLAlchemy is gated behind HAS_SQLALCHEMY (set by the
import guard) so callers can use HarnessDatabase against a SQLite
file even if the superset extra is not installed.
"""

from __future__ import annotations

import abc
import logging
import os
import sqlite3
import uuid
from typing import Optional

from .harness_models import (
    AgenticHarness,
    AgenticMetric,
    AgenticPlugin,
    AgenticSkill,
)

logger = logging.getLogger(__name__)

try:
    import sqlalchemy as _sqlalchemy_check  # type: ignore[import-not-found]  # noqa: F401

    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

# SQLAlchemy types are imported inside _SQLAlchemyHarnessBackend in Task 3
# so that an environment without the superset extra still imports this module
# cleanly and ruff doesn't flag pre-emptive top-level imports as unused.


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS agentic_harnesses (
    session_id              TEXT PRIMARY KEY,
    tool_name               TEXT NOT NULL,
    tool_version            TEXT,
    model_id                TEXT,
    rfc_version             TEXT,
    branch                  TEXT,
    started_at              TEXT NOT NULL,
    ended_at                TEXT,
    outcome                 TEXT,
    replay_of_recording_id  TEXT
);
CREATE INDEX IF NOT EXISTS idx_harnesses_tool ON agentic_harnesses(tool_name);

CREATE TABLE IF NOT EXISTS agentic_plugins (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    plugin_name     TEXT NOT NULL,
    semver          TEXT,
    source          TEXT,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agentic_harnesses(session_id) ON DELETE CASCADE,
    UNIQUE (session_id, plugin_name)
);
CREATE INDEX IF NOT EXISTS idx_plugins_session ON agentic_plugins(session_id);

CREATE TABLE IF NOT EXISTS agentic_skills (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    skill_path      TEXT NOT NULL,
    git_sha         TEXT,
    skill_name      TEXT,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agentic_harnesses(session_id) ON DELETE CASCADE,
    UNIQUE (session_id, skill_path)
);
CREATE INDEX IF NOT EXISTS idx_skills_session ON agentic_skills(session_id);

CREATE TABLE IF NOT EXISTS agentic_metrics (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    test_run_id     INTEGER,
    test_result_id  INTEGER,
    metric_key      TEXT NOT NULL,
    metric_value    REAL,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agentic_harnesses(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_metrics_session ON agentic_metrics(session_id);
CREATE INDEX IF NOT EXISTS idx_metrics_key     ON agentic_metrics(metric_key);
CREATE INDEX IF NOT EXISTS idx_metrics_run     ON agentic_metrics(test_run_id);
"""

_SQLITE_MIGRATIONS: list[str] = []  # placeholder for future column adds


# ---------------------------------------------------------------------------
# Backend ABC
# ---------------------------------------------------------------------------


class _HarnessBackend(abc.ABC):
    """Abstract interface shared by SQLite and SQLAlchemy backends."""

    @abc.abstractmethod
    def save_harness(self, harness: AgenticHarness) -> str: ...

    @abc.abstractmethod
    def end_harness(self, session_id: str, outcome: str, ended_at: str) -> None: ...

    @abc.abstractmethod
    def get_harness(self, session_id: str) -> Optional[AgenticHarness]: ...

    @abc.abstractmethod
    def list_harnesses(
        self, *, tool_name: str = "", limit: int = 50
    ) -> list[AgenticHarness]: ...

    @abc.abstractmethod
    def save_plugins(self, plugins: list[AgenticPlugin]) -> list[str]: ...

    @abc.abstractmethod
    def save_skills(self, skills: list[AgenticSkill]) -> list[str]: ...

    @abc.abstractmethod
    def get_plugins(self, session_id: str) -> list[AgenticPlugin]: ...

    @abc.abstractmethod
    def get_skills(self, session_id: str) -> list[AgenticSkill]: ...

    @abc.abstractmethod
    def save_metric(self, metric: AgenticMetric) -> str: ...

    @abc.abstractmethod
    def save_metrics(self, metrics: list[AgenticMetric]) -> list[str]: ...

    @abc.abstractmethod
    def get_metrics(
        self, session_id: str, *, metric_key: str = ""
    ) -> list[AgenticMetric]: ...

    @abc.abstractmethod
    def get_version(self) -> str: ...

    @abc.abstractmethod
    def get_table_row_count(self, table_name: str) -> int: ...


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------


class _SQLiteHarnessBackend(_HarnessBackend):
    """SQLite backend using the stdlib sqlite3 module."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(_SQLITE_SCHEMA)
            for sql in _SQLITE_MIGRATIONS:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass  # idempotent: column already present, etc.

    # CRUD methods are added incrementally below as TDD cycles complete.
    # Placeholders raise NotImplementedError until each cycle wires them up.

    def save_harness(self, harness: AgenticHarness) -> str:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                INSERT INTO agentic_harnesses
                (session_id, tool_name, tool_version, model_id, rfc_version,
                 branch, started_at, ended_at, outcome, replay_of_recording_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    harness.session_id,
                    harness.tool_name,
                    harness.tool_version or None,
                    harness.model_id or None,
                    harness.rfc_version or None,
                    harness.branch or None,
                    harness.started_at,
                    harness.ended_at or None,
                    harness.outcome or None,
                    harness.replay_of_recording_id or None,
                ),
            )
        return harness.session_id

    def end_harness(self, session_id: str, outcome: str, ended_at: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE agentic_harnesses SET outcome = ?, ended_at = ? WHERE session_id = ?",
                (outcome, ended_at, session_id),
            )
            if cursor.rowcount == 0:
                raise LookupError(f"no harness with session_id={session_id!r}")

    def get_harness(self, session_id: str) -> Optional[AgenticHarness]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT session_id, tool_name, tool_version, model_id, rfc_version,
                       branch, started_at, ended_at, outcome, replay_of_recording_id
                FROM agentic_harnesses WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return AgenticHarness(
            session_id=row[0],
            tool_name=row[1],
            tool_version=row[2] or "",
            model_id=row[3] or "",
            rfc_version=row[4] or "",
            branch=row[5] or "",
            started_at=row[6],
            ended_at=row[7] or "",
            outcome=row[8] or "",
            replay_of_recording_id=row[9] or "",
        )

    def list_harnesses(
        self, *, tool_name: str = "", limit: int = 50
    ) -> list[AgenticHarness]:
        sql = (
            "SELECT session_id, tool_name, tool_version, model_id, rfc_version, "
            "branch, started_at, ended_at, outcome, replay_of_recording_id "
            "FROM agentic_harnesses "
        )
        params: tuple = ()
        if tool_name:
            sql += "WHERE tool_name = ? "
            params = (tool_name,)
        sql += "ORDER BY started_at DESC LIMIT ?"
        params = params + (limit,)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            AgenticHarness(
                session_id=r[0],
                tool_name=r[1],
                tool_version=r[2] or "",
                model_id=r[3] or "",
                rfc_version=r[4] or "",
                branch=r[5] or "",
                started_at=r[6],
                ended_at=r[7] or "",
                outcome=r[8] or "",
                replay_of_recording_id=r[9] or "",
            )
            for r in rows
        ]

    def save_plugins(self, plugins: list[AgenticPlugin]) -> list[str]:
        ids: list[str] = []
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for p in plugins:
                row_id = p.id or uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT OR REPLACE INTO agentic_plugins
                    (id, session_id, plugin_name, semver, source, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        p.session_id,
                        p.plugin_name,
                        p.semver or None,
                        p.source or None,
                        p.recorded_at,
                    ),
                )
                ids.append(row_id)
        return ids

    def save_skills(self, skills: list[AgenticSkill]) -> list[str]:
        ids: list[str] = []
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for s in skills:
                row_id = s.id or uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT OR REPLACE INTO agentic_skills
                    (id, session_id, skill_path, git_sha, skill_name, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        s.session_id,
                        s.skill_path,
                        s.git_sha or None,
                        s.skill_name or None,
                        s.recorded_at,
                    ),
                )
                ids.append(row_id)
        return ids

    def get_plugins(self, session_id: str) -> list[AgenticPlugin]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, session_id, plugin_name, semver, source, recorded_at "
                "FROM agentic_plugins WHERE session_id = ? ORDER BY plugin_name",
                (session_id,),
            ).fetchall()
        return [
            AgenticPlugin(
                session_id=r[1],
                plugin_name=r[2],
                recorded_at=r[5],
                semver=r[3] or "",
                source=r[4] or "",
                id=r[0],
            )
            for r in rows
        ]

    def get_skills(self, session_id: str) -> list[AgenticSkill]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, session_id, skill_path, git_sha, skill_name, recorded_at "
                "FROM agentic_skills WHERE session_id = ? ORDER BY skill_path",
                (session_id,),
            ).fetchall()
        return [
            AgenticSkill(
                session_id=r[1],
                skill_path=r[2],
                recorded_at=r[5],
                git_sha=r[3] or "",
                skill_name=r[4] or "",
                id=r[0],
            )
            for r in rows
        ]

    def save_metric(self, metric: AgenticMetric) -> str:
        return self.save_metrics([metric])[0]

    def save_metrics(self, metrics: list[AgenticMetric]) -> list[str]:
        ids: list[str] = []
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for m in metrics:
                row_id = m.id or uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT INTO agentic_metrics
                    (id, session_id, test_run_id, test_result_id,
                     metric_key, metric_value, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        m.session_id,
                        m.test_run_id if m.test_run_id != -1 else None,
                        m.test_result_id if m.test_result_id != -1 else None,
                        m.metric_key,
                        m.metric_value,
                        m.recorded_at,
                    ),
                )
                ids.append(row_id)
        return ids

    def get_metrics(
        self, session_id: str, *, metric_key: str = ""
    ) -> list[AgenticMetric]:
        sql = (
            "SELECT id, session_id, test_run_id, test_result_id, "
            "metric_key, metric_value, recorded_at "
            "FROM agentic_metrics WHERE session_id = ? "
        )
        params: tuple = (session_id,)
        if metric_key:
            sql += "AND metric_key = ? "
            params = params + (metric_key,)
        sql += "ORDER BY recorded_at, id"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            AgenticMetric(
                session_id=r[1],
                metric_key=r[4],
                recorded_at=r[6],
                metric_value=float(r[5]) if r[5] is not None else 0.0,
                test_run_id=r[2] if r[2] is not None else -1,
                test_result_id=r[3] if r[3] is not None else -1,
                id=r[0],
            )
            for r in rows
        ]

    def get_version(self) -> str:
        with sqlite3.connect(self.db_path) as conn:
            return str(conn.execute("SELECT sqlite_version()").fetchone()[0])

    def get_table_row_count(self, table_name: str) -> int:
        # Table name allow-listed to prevent SQL injection via the parameter.
        if table_name not in {
            "agentic_harnesses",
            "agentic_plugins",
            "agentic_skills",
            "agentic_metrics",
        }:
            raise ValueError(f"unknown harness table: {table_name}")
        with sqlite3.connect(self.db_path) as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class HarnessDatabase:
    """Public facade. Selects backend at construction time.

    Mirrors src/rfc/test_database.py::TestDatabase calling convention:
    pass either ``db_path=`` (SQLite file) or ``database_url=``
    (sqlite:/// or postgresql://).
    """

    def __init__(
        self,
        *,
        db_path: Optional[str] = None,
        database_url: Optional[str] = None,
    ) -> None:
        if db_path:
            self._backend: _HarnessBackend = _SQLiteHarnessBackend(db_path)
        elif database_url:
            if database_url.startswith("sqlite:///"):
                sqlite_path = database_url.replace("sqlite:///", "")
                self._backend = _SQLiteHarnessBackend(sqlite_path)
            elif HAS_SQLALCHEMY:
                # _SQLAlchemyHarnessBackend added in Task 3.
                raise NotImplementedError(
                    "SQLAlchemy backend lands in Task 3 of the foundation plan"
                )
            else:
                raise RuntimeError(
                    "SQLAlchemy is required for non-sqlite database URLs. "
                    "Install with: uv sync --extra superset"
                )
        else:
            env_url = os.environ.get("DATABASE_URL")
            if env_url:
                self.__init__(database_url=env_url)  # type: ignore[misc]
            else:
                raise RuntimeError(
                    "HarnessDatabase requires db_path=, database_url=, or DATABASE_URL env var."
                )

    # Delegating facade methods --------------------------------------------------

    def save_harness(self, harness: AgenticHarness) -> str:
        return self._backend.save_harness(harness)

    def end_harness(self, session_id: str, outcome: str, ended_at: str) -> None:
        self._backend.end_harness(session_id, outcome, ended_at)

    def get_harness(self, session_id: str) -> Optional[AgenticHarness]:
        return self._backend.get_harness(session_id)

    def list_harnesses(
        self, *, tool_name: str = "", limit: int = 50
    ) -> list[AgenticHarness]:
        return self._backend.list_harnesses(tool_name=tool_name, limit=limit)

    def save_plugins(self, plugins: list[AgenticPlugin]) -> list[str]:
        return self._backend.save_plugins(plugins)

    def save_skills(self, skills: list[AgenticSkill]) -> list[str]:
        return self._backend.save_skills(skills)

    def get_plugins(self, session_id: str) -> list[AgenticPlugin]:
        return self._backend.get_plugins(session_id)

    def get_skills(self, session_id: str) -> list[AgenticSkill]:
        return self._backend.get_skills(session_id)

    def save_metric(self, metric: AgenticMetric) -> str:
        return self._backend.save_metric(metric)

    def save_metrics(self, metrics: list[AgenticMetric]) -> list[str]:
        return self._backend.save_metrics(metrics)

    def get_metrics(
        self, session_id: str, *, metric_key: str = ""
    ) -> list[AgenticMetric]:
        return self._backend.get_metrics(session_id, metric_key=metric_key)

    def get_version(self) -> str:
        return self._backend.get_version()

    def get_table_row_count(self, table_name: str) -> int:
        return self._backend.get_table_row_count(table_name)
