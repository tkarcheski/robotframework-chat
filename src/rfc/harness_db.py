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
# SQLAlchemy backend
# ---------------------------------------------------------------------------


class _SQLAlchemyHarnessBackend(_HarnessBackend):
    """SQLAlchemy backend supporting both PostgreSQL and sqlite:/// URLs.

    Imports SQLAlchemy types lazily inside the constructor so that this
    module can be imported in environments without the superset extra.
    Tests exercise this backend via sqlite:/// URLs (HarnessDatabase
    routes those through SQLAlchemy when available); production callers
    using postgresql:// URLs land here too.
    """

    _PG_MIGRATIONS: list[str] = []  # placeholder for future column adds

    def __init__(self, database_url: str) -> None:
        if not HAS_SQLALCHEMY:
            raise RuntimeError(
                "SQLAlchemy is required for the SQLAlchemy backend. "
                "Install with: uv sync --extra superset"
            )
        from sqlalchemy import (  # type: ignore[import-not-found]
            Column,
            Float,
            ForeignKey,
            Integer,
            MetaData,
            String,
            Table,
            UniqueConstraint,
            create_engine,
            event,
            func,
            select,
            text,
        )

        # Stash the imports as instance attrs so other methods can reuse them
        # without re-importing.
        self._text = text
        self._func = func
        self._select = select
        self._database_url = database_url
        self.engine = create_engine(database_url)
        self.metadata = MetaData()
        self._harnesses = Table(
            "agentic_harnesses",
            self.metadata,
            Column("session_id", String, primary_key=True),
            Column("tool_name", String, nullable=False),
            Column("tool_version", String),
            Column("model_id", String),
            Column("rfc_version", String),
            Column("branch", String),
            Column("started_at", String, nullable=False),
            Column("ended_at", String),
            Column("outcome", String),
            Column("replay_of_recording_id", String),
        )
        self._plugins = Table(
            "agentic_plugins",
            self.metadata,
            Column("id", String, primary_key=True),
            Column(
                "session_id",
                String,
                ForeignKey("agentic_harnesses.session_id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("plugin_name", String, nullable=False),
            Column("semver", String),
            Column("source", String),
            Column("recorded_at", String, nullable=False),
            UniqueConstraint(
                "session_id", "plugin_name", name="uq_plugins_session_name"
            ),
        )
        self._skills = Table(
            "agentic_skills",
            self.metadata,
            Column("id", String, primary_key=True),
            Column(
                "session_id",
                String,
                ForeignKey("agentic_harnesses.session_id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("skill_path", String, nullable=False),
            Column("git_sha", String),
            Column("skill_name", String),
            Column("recorded_at", String, nullable=False),
            UniqueConstraint("session_id", "skill_path", name="uq_skills_session_path"),
        )
        self._metrics = Table(
            "agentic_metrics",
            self.metadata,
            Column("id", String, primary_key=True),
            Column(
                "session_id",
                String,
                ForeignKey("agentic_harnesses.session_id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("test_run_id", Integer),
            Column("test_result_id", Integer),
            Column("metric_key", String, nullable=False),
            Column("metric_value", Float),
            Column("recorded_at", String, nullable=False),
        )
        # SQLite ignores FK constraints unless PRAGMA foreign_keys=ON is set
        # on every connection. Postgres enforces FKs unconditionally.
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def _enable_sqlite_fk(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        try:
            self.metadata.create_all(self.engine)
        except Exception:
            logger.warning("create_all() failed; running migrations anyway")
        self._run_migrations()

    def _run_migrations(self) -> None:
        with self.engine.begin() as conn:
            for sql in self._PG_MIGRATIONS:
                try:
                    conn.execute(self._text(sql))
                except Exception as exc:  # idempotent
                    logger.debug("migration skipped: %s (%s)", sql, exc)

    # CRUD ---------------------------------------------------------------------

    def save_harness(self, harness: AgenticHarness) -> str:
        with self.engine.begin() as conn:
            conn.execute(
                self._harnesses.insert(),
                {
                    "session_id": harness.session_id,
                    "tool_name": harness.tool_name,
                    "tool_version": harness.tool_version or None,
                    "model_id": harness.model_id or None,
                    "rfc_version": harness.rfc_version or None,
                    "branch": harness.branch or None,
                    "started_at": harness.started_at,
                    "ended_at": harness.ended_at or None,
                    "outcome": harness.outcome or None,
                    "replay_of_recording_id": harness.replay_of_recording_id or None,
                },
            )
        return harness.session_id

    def end_harness(self, session_id: str, outcome: str, ended_at: str) -> None:
        with self.engine.begin() as conn:
            result = conn.execute(
                self._harnesses.update()
                .where(self._harnesses.c.session_id == session_id)
                .values(outcome=outcome, ended_at=ended_at)
            )
            if result.rowcount == 0:
                raise LookupError(f"no harness with session_id={session_id!r}")

    def get_harness(self, session_id: str) -> Optional[AgenticHarness]:
        with self.engine.connect() as conn:
            row = conn.execute(
                self._harnesses.select().where(
                    self._harnesses.c.session_id == session_id
                )
            ).fetchone()
        if row is None:
            return None
        return AgenticHarness(
            session_id=row.session_id,
            tool_name=row.tool_name,
            tool_version=row.tool_version or "",
            model_id=row.model_id or "",
            rfc_version=row.rfc_version or "",
            branch=row.branch or "",
            started_at=row.started_at,
            ended_at=row.ended_at or "",
            outcome=row.outcome or "",
            replay_of_recording_id=row.replay_of_recording_id or "",
        )

    def list_harnesses(
        self, *, tool_name: str = "", limit: int = 50
    ) -> list[AgenticHarness]:
        stmt = self._harnesses.select()
        if tool_name:
            stmt = stmt.where(self._harnesses.c.tool_name == tool_name)
        stmt = stmt.order_by(self._harnesses.c.started_at.desc()).limit(limit)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [
            AgenticHarness(
                session_id=r.session_id,
                tool_name=r.tool_name,
                tool_version=r.tool_version or "",
                model_id=r.model_id or "",
                rfc_version=r.rfc_version or "",
                branch=r.branch or "",
                started_at=r.started_at,
                ended_at=r.ended_at or "",
                outcome=r.outcome or "",
                replay_of_recording_id=r.replay_of_recording_id or "",
            )
            for r in rows
        ]

    def save_plugins(self, plugins: list[AgenticPlugin]) -> list[str]:
        ids: list[str] = []
        # SQLAlchemy doesn't expose INSERT OR REPLACE portably; emulate with
        # delete-then-insert per row keyed on the UNIQUE pair.
        with self.engine.begin() as conn:
            for p in plugins:
                row_id = p.id or uuid.uuid4().hex
                conn.execute(
                    self._plugins.delete().where(
                        (self._plugins.c.session_id == p.session_id)
                        & (self._plugins.c.plugin_name == p.plugin_name)
                    )
                )
                conn.execute(
                    self._plugins.insert(),
                    {
                        "id": row_id,
                        "session_id": p.session_id,
                        "plugin_name": p.plugin_name,
                        "semver": p.semver or None,
                        "source": p.source or None,
                        "recorded_at": p.recorded_at,
                    },
                )
                ids.append(row_id)
        return ids

    def save_skills(self, skills: list[AgenticSkill]) -> list[str]:
        ids: list[str] = []
        with self.engine.begin() as conn:
            for s in skills:
                row_id = s.id or uuid.uuid4().hex
                conn.execute(
                    self._skills.delete().where(
                        (self._skills.c.session_id == s.session_id)
                        & (self._skills.c.skill_path == s.skill_path)
                    )
                )
                conn.execute(
                    self._skills.insert(),
                    {
                        "id": row_id,
                        "session_id": s.session_id,
                        "skill_path": s.skill_path,
                        "git_sha": s.git_sha or None,
                        "skill_name": s.skill_name or None,
                        "recorded_at": s.recorded_at,
                    },
                )
                ids.append(row_id)
        return ids

    def get_plugins(self, session_id: str) -> list[AgenticPlugin]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                self._plugins.select()
                .where(self._plugins.c.session_id == session_id)
                .order_by(self._plugins.c.plugin_name)
            ).fetchall()
        return [
            AgenticPlugin(
                session_id=r.session_id,
                plugin_name=r.plugin_name,
                recorded_at=r.recorded_at,
                semver=r.semver or "",
                source=r.source or "",
                id=r.id,
            )
            for r in rows
        ]

    def get_skills(self, session_id: str) -> list[AgenticSkill]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                self._skills.select()
                .where(self._skills.c.session_id == session_id)
                .order_by(self._skills.c.skill_path)
            ).fetchall()
        return [
            AgenticSkill(
                session_id=r.session_id,
                skill_path=r.skill_path,
                recorded_at=r.recorded_at,
                git_sha=r.git_sha or "",
                skill_name=r.skill_name or "",
                id=r.id,
            )
            for r in rows
        ]

    def save_metric(self, metric: AgenticMetric) -> str:
        return self.save_metrics([metric])[0]

    def save_metrics(self, metrics: list[AgenticMetric]) -> list[str]:
        ids: list[str] = []
        with self.engine.begin() as conn:
            for m in metrics:
                row_id = m.id or uuid.uuid4().hex
                conn.execute(
                    self._metrics.insert(),
                    {
                        "id": row_id,
                        "session_id": m.session_id,
                        "test_run_id": m.test_run_id if m.test_run_id != -1 else None,
                        "test_result_id": (
                            m.test_result_id if m.test_result_id != -1 else None
                        ),
                        "metric_key": m.metric_key,
                        "metric_value": m.metric_value,
                        "recorded_at": m.recorded_at,
                    },
                )
                ids.append(row_id)
        return ids

    def get_metrics(
        self, session_id: str, *, metric_key: str = ""
    ) -> list[AgenticMetric]:
        stmt = self._metrics.select().where(self._metrics.c.session_id == session_id)
        if metric_key:
            stmt = stmt.where(self._metrics.c.metric_key == metric_key)
        stmt = stmt.order_by(self._metrics.c.recorded_at, self._metrics.c.id)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [
            AgenticMetric(
                session_id=r.session_id,
                metric_key=r.metric_key,
                recorded_at=r.recorded_at,
                metric_value=float(r.metric_value)
                if r.metric_value is not None
                else 0.0,
                test_run_id=r.test_run_id if r.test_run_id is not None else -1,
                test_result_id=r.test_result_id if r.test_result_id is not None else -1,
                id=r.id,
            )
            for r in rows
        ]

    def get_version(self) -> str:
        return self.engine.dialect.name

    def get_table_row_count(self, table_name: str) -> int:
        if table_name not in {
            "agentic_harnesses",
            "agentic_plugins",
            "agentic_skills",
            "agentic_metrics",
        }:
            raise ValueError(f"unknown harness table: {table_name}")
        table_map = {
            "agentic_harnesses": self._harnesses,
            "agentic_plugins": self._plugins,
            "agentic_skills": self._skills,
            "agentic_metrics": self._metrics,
        }
        with self.engine.connect() as conn:
            return int(
                conn.execute(
                    self._select(self._func.count()).select_from(table_map[table_name])
                ).scalar()
                or 0
            )


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
            # File path always uses the native sqlite3 backend (legacy fast path).
            self._backend: _HarnessBackend = _SQLiteHarnessBackend(db_path)
        elif database_url:
            # Deliberate divergence from TestDatabase: HarnessDatabase routes
            # ALL database URLs (including sqlite:///) through SQLAlchemy when
            # available, so the test suite can exercise the SQLAlchemy code
            # path against an in-tmpdir SQLite file without needing a live
            # Postgres. Falls back to native sqlite3 only when SQLAlchemy is
            # missing AND the URL is sqlite:///.
            if HAS_SQLALCHEMY:
                self._backend = _SQLAlchemyHarnessBackend(database_url)
            elif database_url.startswith("sqlite:///"):
                sqlite_path = database_url.replace("sqlite:///", "")
                self._backend = _SQLiteHarnessBackend(sqlite_path)
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
