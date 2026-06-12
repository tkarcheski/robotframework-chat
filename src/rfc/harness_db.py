"""HarnessDatabase: schema spine for the Agentic Stack Tracker.

Mirrors the shape of src/rfc/test_database.py. SQLite is always
available; SQLAlchemy is gated behind HAS_SQLALCHEMY (set by the
import guard) so callers can use HarnessDatabase against a SQLite
file even if the superset extra is not installed.
"""

from __future__ import annotations

import abc
import dataclasses
import logging
import os
import sqlite3
import uuid
from typing import Any, Optional, Sequence

from .harness_models import (
    AgenticDecision,
    AgenticHarness,
    AgenticMetric,
    AgenticPlugin,
    AgenticSkill,
    DialogRecording,
    DialogTurn,
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

CREATE TABLE IF NOT EXISTS agentic_decisions (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    test_name       TEXT,
    hook_event      TEXT NOT NULL,
    prompt_model    TEXT NOT NULL,
    prompt_text     TEXT NOT NULL,
    response_text   TEXT,
    proposed_action TEXT,
    applied         INTEGER NOT NULL,
    tokens_used     INTEGER,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agentic_harnesses(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_decisions_session ON agentic_decisions(session_id);
CREATE INDEX IF NOT EXISTS idx_decisions_action  ON agentic_decisions(proposed_action);

CREATE TABLE IF NOT EXISTS dialog_recordings (
    id              TEXT PRIMARY KEY,
    session_id      TEXT,
    source_type     TEXT NOT NULL,
    tool_name       TEXT,
    tool_version    TEXT,
    model_id        TEXT,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    metadata_json   TEXT,
    FOREIGN KEY (session_id) REFERENCES agentic_harnesses(session_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS dialog_turns (
    id                  TEXT PRIMARY KEY,
    recording_id        TEXT NOT NULL,
    turn_number         INTEGER NOT NULL,
    role                TEXT NOT NULL,
    content             TEXT,
    tool_calls_json     TEXT,
    tool_results_json   TEXT,
    timestamp           TEXT NOT NULL,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    latency_ms          REAL,
    FOREIGN KEY (recording_id) REFERENCES dialog_recordings(id) ON DELETE CASCADE,
    UNIQUE (recording_id, turn_number)
);
CREATE INDEX IF NOT EXISTS idx_dialog_turns_recording ON dialog_turns(recording_id);
"""

_SQLITE_MIGRATIONS: list[str] = []  # placeholder for future column adds

# Canonical body of the ``agentic_sessions_full`` view (issue #353).
#
# Denormalizes ``agentic_harnesses`` and pre-pivots the EAV rows in
# ``agentic_metrics`` (tokens_in / tokens_out / latency_ms / grader_score)
# into one row per harness session. The Superset bootstrap
# (superset/bootstrap_dashboards.py) embeds a copy of this SQL in its DDL;
# a drift-guard test in tests/test_bootstrap_dashboards.py keeps the two
# in sync. Written in the portable subset shared by PostgreSQL and SQLite.
AGENTIC_SESSIONS_FULL_VIEW_BODY: str = """\
SELECT
    h.session_id,
    h.tool_name,
    h.tool_version,
    h.model_id,
    h.rfc_version,
    h.branch,
    h.started_at,
    CAST(h.started_at AS TIMESTAMP) AS started_ts,
    h.ended_at,
    h.outcome,
    h.replay_of_recording_id,
    SUM(CASE WHEN m.metric_key = 'tokens_in' THEN m.metric_value END)
        AS tokens_in,
    SUM(CASE WHEN m.metric_key = 'tokens_out' THEN m.metric_value END)
        AS tokens_out,
    AVG(CASE WHEN m.metric_key = 'latency_ms' THEN m.metric_value END)
        AS avg_latency_ms,
    AVG(CASE WHEN m.metric_key = 'grader_score' THEN m.metric_value END)
        AS avg_grader_score
FROM agentic_harnesses h
LEFT JOIN agentic_metrics m ON m.session_id = h.session_id
GROUP BY h.session_id, h.tool_name, h.tool_version, h.model_id,
         h.rfc_version, h.branch, h.started_at, h.ended_at, h.outcome,
         h.replay_of_recording_id"""


def _decision_from_row(row: "Sequence[Any]") -> AgenticDecision:
    """Map a positional (id, session_id, test_name, hook_event, prompt_model,
    prompt_text, response_text, proposed_action, applied, tokens_used,
    recorded_at) row to a dataclass.

    Works for both sqlite3 tuples and SQLAlchemy Row objects (index-able).
    """
    return AgenticDecision(
        session_id=row[1],
        hook_event=row[3],
        prompt_model=row[4],
        prompt_text=row[5],
        recorded_at=row[10],
        test_name=row[2] or "",
        response_text=row[6] or "",
        proposed_action=row[7] or "",
        applied=int(row[8]),
        tokens_used=int(row[9]) if row[9] is not None else -1,
        id=row[0],
    )


def _recording_from_row(row: "Sequence[Any]") -> DialogRecording:
    """Map a positional (id, session_id, source_type, tool_name, tool_version,
    model_id, started_at, ended_at, metadata_json) row to a dataclass.

    Works for both sqlite3 tuples and SQLAlchemy Row objects (index-able).
    """
    return DialogRecording(
        id=row[0],
        session_id=row[1] or "",
        source_type=row[2],
        tool_name=row[3] or "",
        tool_version=row[4] or "",
        model_id=row[5] or "",
        started_at=row[6],
        ended_at=row[7] or "",
        metadata_json=row[8] or "",
    )


def _turn_from_row(row: "Sequence[Any]") -> DialogTurn:
    """Map a positional (id, recording_id, turn_number, role, content,
    tool_calls_json, tool_results_json, timestamp, prompt_tokens,
    completion_tokens, latency_ms) row to a dataclass."""
    return DialogTurn(
        recording_id=row[1],
        turn_number=int(row[2]),
        role=row[3],
        content=row[4] or "",
        tool_calls_json=row[5] or "",
        tool_results_json=row[6] or "",
        timestamp=row[7],
        prompt_tokens=int(row[8]) if row[8] is not None else -1,
        completion_tokens=int(row[9]) if row[9] is not None else -1,
        latency_ms=float(row[10]) if row[10] is not None else -1.0,
        id=row[0],
    )


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
    def save_decision(self, decision: AgenticDecision) -> str: ...

    @abc.abstractmethod
    def save_decisions(self, decisions: list[AgenticDecision]) -> list[str]: ...

    @abc.abstractmethod
    def get_decisions(
        self, session_id: str, *, proposed_action: str = ""
    ) -> list[AgenticDecision]: ...

    @abc.abstractmethod
    def save_recording(self, recording: DialogRecording) -> str: ...

    @abc.abstractmethod
    def end_recording(self, recording_id: str, ended_at: str) -> None: ...

    @abc.abstractmethod
    def get_recording(self, recording_id: str) -> Optional[DialogRecording]: ...

    @abc.abstractmethod
    def save_turns(self, turns: list[DialogTurn]) -> list[str]: ...

    @abc.abstractmethod
    def get_turns(self, recording_id: str) -> list[DialogTurn]: ...

    @abc.abstractmethod
    def get_version(self) -> str: ...

    @abc.abstractmethod
    def get_table_row_count(self, table_name: str) -> int: ...


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------


class _SQLiteHarnessBackend(_HarnessBackend):
    """SQLite backend using the stdlib sqlite3 module."""

    def __init__(self, db_path: str, *, create_missing_dir: bool = True) -> None:
        self.db_path = db_path
        if create_missing_dir:
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

    def save_decision(self, decision: AgenticDecision) -> str:
        return self.save_decisions([decision])[0]

    def save_decisions(self, decisions: list[AgenticDecision]) -> list[str]:
        ids: list[str] = []
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for d in decisions:
                row_id = d.id or uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT INTO agentic_decisions
                    (id, session_id, test_name, hook_event, prompt_model,
                     prompt_text, response_text, proposed_action, applied,
                     tokens_used, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        d.session_id,
                        d.test_name or None,
                        d.hook_event,
                        d.prompt_model,
                        d.prompt_text,
                        d.response_text or None,
                        d.proposed_action or None,
                        d.applied,
                        d.tokens_used if d.tokens_used >= 0 else None,
                        d.recorded_at,
                    ),
                )
                ids.append(row_id)
        return ids

    def get_decisions(
        self, session_id: str, *, proposed_action: str = ""
    ) -> list[AgenticDecision]:
        sql = (
            "SELECT id, session_id, test_name, hook_event, prompt_model, "
            "prompt_text, response_text, proposed_action, applied, "
            "tokens_used, recorded_at "
            "FROM agentic_decisions WHERE session_id = ? "
        )
        params: tuple = (session_id,)
        if proposed_action:
            sql += "AND proposed_action = ? "
            params = params + (proposed_action,)
        sql += "ORDER BY recorded_at, id"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_decision_from_row(r) for r in rows]

    def save_recording(self, recording: DialogRecording) -> str:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                INSERT INTO dialog_recordings
                (id, session_id, source_type, tool_name, tool_version,
                 model_id, started_at, ended_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recording.id,
                    recording.session_id or None,
                    recording.source_type,
                    recording.tool_name or None,
                    recording.tool_version or None,
                    recording.model_id or None,
                    recording.started_at,
                    recording.ended_at or None,
                    recording.metadata_json or None,
                ),
            )
        return recording.id

    def end_recording(self, recording_id: str, ended_at: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE dialog_recordings SET ended_at = ? WHERE id = ?",
                (ended_at, recording_id),
            )
            if cursor.rowcount == 0:
                raise LookupError(f"no recording with id={recording_id!r}")

    def get_recording(self, recording_id: str) -> Optional[DialogRecording]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, session_id, source_type, tool_name, tool_version,
                       model_id, started_at, ended_at, metadata_json
                FROM dialog_recordings WHERE id = ?
                """,
                (recording_id,),
            ).fetchone()
        if row is None:
            return None
        return _recording_from_row(row)

    def save_turns(self, turns: list[DialogTurn]) -> list[str]:
        ids: list[str] = []
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for t in turns:
                row_id = t.id or uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT OR REPLACE INTO dialog_turns
                    (id, recording_id, turn_number, role, content,
                     tool_calls_json, tool_results_json, timestamp,
                     prompt_tokens, completion_tokens, latency_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        t.recording_id,
                        t.turn_number,
                        t.role,
                        t.content or None,
                        t.tool_calls_json or None,
                        t.tool_results_json or None,
                        t.timestamp,
                        t.prompt_tokens if t.prompt_tokens >= 0 else None,
                        t.completion_tokens if t.completion_tokens >= 0 else None,
                        t.latency_ms if t.latency_ms >= 0 else None,
                    ),
                )
                ids.append(row_id)
        return ids

    def get_turns(self, recording_id: str) -> list[DialogTurn]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, recording_id, turn_number, role, content,
                       tool_calls_json, tool_results_json, timestamp,
                       prompt_tokens, completion_tokens, latency_ms
                FROM dialog_turns WHERE recording_id = ? ORDER BY turn_number
                """,
                (recording_id,),
            ).fetchall()
        return [_turn_from_row(r) for r in rows]

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
            "agentic_decisions",
            "dialog_recordings",
            "dialog_turns",
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
            Index,
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
        self._decisions = Table(
            "agentic_decisions",
            self.metadata,
            Column("id", String, primary_key=True),
            Column(
                "session_id",
                String,
                ForeignKey("agentic_harnesses.session_id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("test_name", String),
            Column("hook_event", String, nullable=False),
            Column("prompt_model", String, nullable=False),
            Column("prompt_text", String, nullable=False),
            Column("response_text", String),
            Column("proposed_action", String),
            Column("applied", Integer, nullable=False),
            Column("tokens_used", Integer),
            Column("recorded_at", String, nullable=False),
            Index("idx_decisions_session", "session_id"),
            Index("idx_decisions_action", "proposed_action"),
        )
        self._recordings = Table(
            "dialog_recordings",
            self.metadata,
            Column("id", String, primary_key=True),
            Column(
                "session_id",
                String,
                ForeignKey("agentic_harnesses.session_id", ondelete="SET NULL"),
            ),
            Column("source_type", String, nullable=False),
            Column("tool_name", String),
            Column("tool_version", String),
            Column("model_id", String),
            Column("started_at", String, nullable=False),
            Column("ended_at", String),
            Column("metadata_json", String),
        )
        self._turns = Table(
            "dialog_turns",
            self.metadata,
            Column("id", String, primary_key=True),
            Column(
                "recording_id",
                String,
                ForeignKey("dialog_recordings.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            Column("turn_number", Integer, nullable=False),
            Column("role", String, nullable=False),
            Column("content", String),
            Column("tool_calls_json", String),
            Column("tool_results_json", String),
            Column("timestamp", String, nullable=False),
            Column("prompt_tokens", Integer),
            Column("completion_tokens", Integer),
            Column("latency_ms", Float),
            UniqueConstraint(
                "recording_id", "turn_number", name="uq_turns_recording_number"
            ),
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

    def save_decision(self, decision: AgenticDecision) -> str:
        return self.save_decisions([decision])[0]

    def save_decisions(self, decisions: list[AgenticDecision]) -> list[str]:
        ids: list[str] = []
        with self.engine.begin() as conn:
            for d in decisions:
                row_id = d.id or uuid.uuid4().hex
                conn.execute(
                    self._decisions.insert(),
                    {
                        "id": row_id,
                        "session_id": d.session_id,
                        "test_name": d.test_name or None,
                        "hook_event": d.hook_event,
                        "prompt_model": d.prompt_model,
                        "prompt_text": d.prompt_text,
                        "response_text": d.response_text or None,
                        "proposed_action": d.proposed_action or None,
                        "applied": d.applied,
                        "tokens_used": d.tokens_used if d.tokens_used >= 0 else None,
                        "recorded_at": d.recorded_at,
                    },
                )
                ids.append(row_id)
        return ids

    def get_decisions(
        self, session_id: str, *, proposed_action: str = ""
    ) -> list[AgenticDecision]:
        cols = self._decisions.c
        stmt = self._select(
            cols.id,
            cols.session_id,
            cols.test_name,
            cols.hook_event,
            cols.prompt_model,
            cols.prompt_text,
            cols.response_text,
            cols.proposed_action,
            cols.applied,
            cols.tokens_used,
            cols.recorded_at,
        ).where(cols.session_id == session_id)
        if proposed_action:
            stmt = stmt.where(cols.proposed_action == proposed_action)
        stmt = stmt.order_by(cols.recorded_at, cols.id)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [_decision_from_row(r) for r in rows]

    def save_recording(self, recording: DialogRecording) -> str:
        with self.engine.begin() as conn:
            conn.execute(
                self._recordings.insert(),
                {
                    "id": recording.id,
                    "session_id": recording.session_id or None,
                    "source_type": recording.source_type,
                    "tool_name": recording.tool_name or None,
                    "tool_version": recording.tool_version or None,
                    "model_id": recording.model_id or None,
                    "started_at": recording.started_at,
                    "ended_at": recording.ended_at or None,
                    "metadata_json": recording.metadata_json or None,
                },
            )
        return recording.id

    def end_recording(self, recording_id: str, ended_at: str) -> None:
        with self.engine.begin() as conn:
            result = conn.execute(
                self._recordings.update()
                .where(self._recordings.c.id == recording_id)
                .values(ended_at=ended_at)
            )
            if result.rowcount == 0:
                raise LookupError(f"no recording with id={recording_id!r}")

    def get_recording(self, recording_id: str) -> Optional[DialogRecording]:
        cols = self._recordings.c
        stmt = self._select(
            cols.id,
            cols.session_id,
            cols.source_type,
            cols.tool_name,
            cols.tool_version,
            cols.model_id,
            cols.started_at,
            cols.ended_at,
            cols.metadata_json,
        ).where(cols.id == recording_id)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).fetchone()
        if row is None:
            return None
        return _recording_from_row(row)

    def save_turns(self, turns: list[DialogTurn]) -> list[str]:
        ids: list[str] = []
        with self.engine.begin() as conn:
            for t in turns:
                row_id = t.id or uuid.uuid4().hex
                conn.execute(
                    self._turns.delete().where(
                        (self._turns.c.recording_id == t.recording_id)
                        & (self._turns.c.turn_number == t.turn_number)
                    )
                )
                conn.execute(
                    self._turns.insert(),
                    {
                        "id": row_id,
                        "recording_id": t.recording_id,
                        "turn_number": t.turn_number,
                        "role": t.role,
                        "content": t.content or None,
                        "tool_calls_json": t.tool_calls_json or None,
                        "tool_results_json": t.tool_results_json or None,
                        "timestamp": t.timestamp,
                        "prompt_tokens": t.prompt_tokens
                        if t.prompt_tokens >= 0
                        else None,
                        "completion_tokens": (
                            t.completion_tokens if t.completion_tokens >= 0 else None
                        ),
                        "latency_ms": t.latency_ms if t.latency_ms >= 0 else None,
                    },
                )
                ids.append(row_id)
        return ids

    def get_turns(self, recording_id: str) -> list[DialogTurn]:
        cols = self._turns.c
        stmt = (
            self._select(
                cols.id,
                cols.recording_id,
                cols.turn_number,
                cols.role,
                cols.content,
                cols.tool_calls_json,
                cols.tool_results_json,
                cols.timestamp,
                cols.prompt_tokens,
                cols.completion_tokens,
                cols.latency_ms,
            )
            .where(cols.recording_id == recording_id)
            .order_by(cols.turn_number)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [_turn_from_row(r) for r in rows]

    def get_version(self) -> str:
        return self.engine.dialect.name

    def get_table_row_count(self, table_name: str) -> int:
        table_map = {
            "agentic_harnesses": self._harnesses,
            "agentic_plugins": self._plugins,
            "agentic_skills": self._skills,
            "agentic_metrics": self._metrics,
            "agentic_decisions": self._decisions,
            "dialog_recordings": self._recordings,
            "dialog_turns": self._turns,
        }
        if table_name not in table_map:
            raise ValueError(f"unknown harness table: {table_name}")
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
                # Match SQLAlchemy semantics: a URL pointing into a missing
                # directory is unreachable, not an invitation to mkdir (#439).
                self._backend = _SQLiteHarnessBackend(
                    sqlite_path, create_missing_dir=False
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

    def save_decision(self, decision: AgenticDecision) -> str:
        return self._backend.save_decision(decision)

    def save_decisions(self, decisions: list[AgenticDecision]) -> list[str]:
        return self._backend.save_decisions(decisions)

    def get_decisions(
        self, session_id: str, *, proposed_action: str = ""
    ) -> list[AgenticDecision]:
        return self._backend.get_decisions(session_id, proposed_action=proposed_action)

    def save_recording(self, recording: DialogRecording) -> str:
        """Persist a recording, dropping a dangling ``session_id``.

        With an isolated DIALOG_DATABASE_URL the parent agentic_harnesses
        row lives in the main DB, so the FK target is absent here. Keep
        the recording (skip-and-log per CLAUDE.md) rather than letting
        the FK reject it and lose the dialog.
        """
        if recording.session_id and self.get_harness(recording.session_id) is None:
            logger.warning(
                "save_recording: session_id %r has no agentic_harnesses row "
                "in this database (isolated dialog DB?); saving recording %s "
                "without a session link.",
                recording.session_id,
                recording.id,
            )
            recording = dataclasses.replace(recording, session_id="")
        return self._backend.save_recording(recording)

    def end_recording(self, recording_id: str, ended_at: str) -> None:
        self._backend.end_recording(recording_id, ended_at)

    def get_recording(self, recording_id: str) -> Optional[DialogRecording]:
        return self._backend.get_recording(recording_id)

    def save_turns(self, turns: list[DialogTurn]) -> list[str]:
        return self._backend.save_turns(turns)

    def get_turns(self, recording_id: str) -> list[DialogTurn]:
        return self._backend.get_turns(recording_id)

    def get_version(self) -> str:
        return self._backend.get_version()

    def get_table_row_count(self, table_name: str) -> int:
        return self._backend.get_table_row_count(table_name)
