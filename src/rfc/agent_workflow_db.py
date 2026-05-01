"""Persistence for AgentWorkflow records.

Sibling of :mod:`rfc.test_database` — same dual SQLite / PostgreSQL pattern
but isolated to agent-workflow tables so the existing test-results schema
stays untouched.

Schema (4 tables):
    - ``agent_workflows``    — one row per workflow session
    - ``agent_interactions`` — one row per turn (messages + state stored as JSON)
    - ``agent_tool_calls``   — one row per tool call
    - ``agent_tool_results`` — one row per tool result

SQLite:      sqlite:///data/agent_workflows.db   (default)
PostgreSQL:  postgresql://user:pass@host:5433/dbname  (via DATABASE_URL)
"""

from __future__ import annotations

import abc
import json
import logging
import os
import sqlite3
from typing import Any, Dict, Optional

from .agent_interaction import AgentInteraction
from .agent_workflow import AgentWorkflow

logger = logging.getLogger(__name__)

try:
    from sqlalchemy import (  # type: ignore[import-not-found]
        Boolean,
        Column,
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


def workflow_to_dict(workflow: AgentWorkflow) -> Dict[str, Any]:
    """Serialise a workflow (with nested interactions) to a JSON-safe dict."""
    return {
        "workflow_id": workflow.workflow_id,
        "agent_id": workflow.agent_id,
        "task_description": workflow.task_description,
        "started_at": workflow.started_at,
        "ended_at": workflow.ended_at,
        "status": workflow.status,
        "error": workflow.error,
        "metadata": dict(workflow.metadata),
        "interactions": [_interaction_to_dict(i) for i in workflow.interactions],
    }


def _interaction_to_dict(interaction: AgentInteraction) -> Dict[str, Any]:
    return {
        "turn_number": interaction.turn_number,
        "messages": [
            {"role": m.role, "content": m.content, "timestamp": m.timestamp}
            for m in interaction.messages
        ],
        "tool_calls": [
            {
                "id": c.id,
                "tool_name": c.tool_name,
                "arguments": c.arguments,
                "timestamp": c.timestamp,
                "call_number": c.call_number,
            }
            for c in interaction.tool_calls
        ],
        "tool_results": [
            {
                "tool_call_id": r.tool_call_id,
                "success": r.success,
                "output": r.output,
                "error": r.error,
                "execution_time_ms": r.execution_time_ms,
            }
            for r in interaction.tool_results
        ],
        "state_before": interaction.state_before,
        "state_after": interaction.state_after,
        "reasoning": interaction.reasoning,
        "duration_ms": interaction.duration_ms,
        "success": interaction.success,
        "error": interaction.error,
    }


class _Backend(abc.ABC):
    @abc.abstractmethod
    def persist_workflow(self, workflow: AgentWorkflow) -> int: ...

    @abc.abstractmethod
    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]: ...

    @abc.abstractmethod
    def get_table_row_count(self, table_name: str) -> int: ...


class _SQLiteBackend(_Backend):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS agent_workflows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workflow_id TEXT UNIQUE NOT NULL,
        agent_id TEXT NOT NULL,
        task_description TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at REAL NOT NULL,
        ended_at REAL,
        error TEXT,
        metadata_json TEXT
    );

    CREATE TABLE IF NOT EXISTS agent_interactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workflow_id TEXT NOT NULL,
        turn_number INTEGER NOT NULL,
        reasoning TEXT,
        messages_json TEXT,
        state_before_json TEXT,
        state_after_json TEXT,
        duration_ms REAL,
        success INTEGER NOT NULL,
        error TEXT,
        UNIQUE(workflow_id, turn_number),
        FOREIGN KEY (workflow_id) REFERENCES agent_workflows(workflow_id)
            ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS agent_tool_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        call_id TEXT UNIQUE NOT NULL,
        workflow_id TEXT NOT NULL,
        interaction_id INTEGER NOT NULL,
        tool_name TEXT NOT NULL,
        arguments_json TEXT NOT NULL,
        call_number INTEGER NOT NULL,
        timestamp REAL NOT NULL,
        FOREIGN KEY (interaction_id) REFERENCES agent_interactions(id)
            ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS agent_tool_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        call_id TEXT NOT NULL,
        workflow_id TEXT NOT NULL,
        success INTEGER NOT NULL,
        output TEXT,
        error TEXT,
        execution_time_ms REAL,
        FOREIGN KEY (call_id) REFERENCES agent_tool_calls(call_id)
            ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_agent_interactions_workflow
        ON agent_interactions(workflow_id);
    CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_workflow
        ON agent_tool_calls(workflow_id);
    CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_name
        ON agent_tool_calls(tool_name);
    CREATE INDEX IF NOT EXISTS idx_agent_tool_results_call
        ON agent_tool_results(call_id);
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.executescript(self.SCHEMA)

    def persist_workflow(self, workflow: AgentWorkflow) -> int:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            # Upsert the workflow row first so the FK target exists, then
            # wipe and re-insert all child rows from the workflow object
            # (the source of truth at persist time). Deleting agent_interactions
            # cascades to agent_tool_calls and agent_tool_results via ON
            # DELETE CASCADE, dropping any turns no longer present in the
            # current payload.
            cur = conn.execute(
                """
                INSERT INTO agent_workflows
                    (workflow_id, agent_id, task_description, status,
                     started_at, ended_at, error, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    status = excluded.status,
                    ended_at = excluded.ended_at,
                    error = excluded.error,
                    metadata_json = excluded.metadata_json
                """,
                (
                    workflow.workflow_id,
                    workflow.agent_id,
                    workflow.task_description,
                    workflow.status,
                    workflow.started_at,
                    workflow.ended_at,
                    workflow.error,
                    json.dumps(workflow.metadata),
                ),
            )
            workflow_pk = cur.lastrowid or _lookup_workflow_pk(
                conn, workflow.workflow_id
            )
            conn.execute(
                "DELETE FROM agent_interactions WHERE workflow_id = ?",
                (workflow.workflow_id,),
            )

            for interaction in workflow.interactions:
                inter_cur = conn.execute(
                    """
                    INSERT INTO agent_interactions
                        (workflow_id, turn_number, reasoning, messages_json,
                         state_before_json, state_after_json, duration_ms,
                         success, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workflow.workflow_id,
                        interaction.turn_number,
                        interaction.reasoning,
                        json.dumps(
                            [
                                {
                                    "role": m.role,
                                    "content": m.content,
                                    "timestamp": m.timestamp,
                                }
                                for m in interaction.messages
                            ]
                        ),
                        json.dumps(interaction.state_before),
                        json.dumps(interaction.state_after),
                        interaction.duration_ms,
                        1 if interaction.success else 0,
                        interaction.error,
                    ),
                )
                interaction_id = inter_cur.lastrowid
                assert interaction_id is not None and interaction_id > 0

                for call in interaction.tool_calls:
                    conn.execute(
                        """
                        INSERT INTO agent_tool_calls
                            (call_id, workflow_id, interaction_id, tool_name,
                             arguments_json, call_number, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            call.id,
                            workflow.workflow_id,
                            interaction_id,
                            call.tool_name,
                            json.dumps(call.arguments),
                            call.call_number,
                            call.timestamp,
                        ),
                    )

                for result in interaction.tool_results:
                    conn.execute(
                        """
                        INSERT INTO agent_tool_results
                            (call_id, workflow_id, success, output, error,
                             execution_time_ms)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            result.tool_call_id,
                            workflow.workflow_id,
                            1 if result.success else 0,
                            result.output,
                            result.error,
                            result.execution_time_ms,
                        ),
                    )

            return int(workflow_pk)

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM agent_workflows WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
            if row is None:
                return None
            workflow = dict(row)
            workflow["metadata"] = json.loads(workflow.pop("metadata_json") or "{}")

            interactions = conn.execute(
                "SELECT * FROM agent_interactions "
                "WHERE workflow_id = ? ORDER BY turn_number",
                (workflow_id,),
            ).fetchall()
            workflow["interactions"] = []
            for inter_row in interactions:
                interaction = dict(inter_row)
                interaction["messages"] = json.loads(
                    interaction.pop("messages_json") or "[]"
                )
                interaction["state_before"] = json.loads(
                    interaction.pop("state_before_json") or "{}"
                )
                interaction["state_after"] = json.loads(
                    interaction.pop("state_after_json") or "{}"
                )
                interaction["success"] = bool(interaction["success"])

                calls = conn.execute(
                    "SELECT * FROM agent_tool_calls "
                    "WHERE interaction_id = ? ORDER BY call_number",
                    (interaction["id"],),
                ).fetchall()
                interaction["tool_calls"] = []
                for c in calls:
                    call_dict = dict(c)
                    call_dict["arguments"] = json.loads(
                        call_dict.pop("arguments_json") or "{}"
                    )
                    interaction["tool_calls"].append(call_dict)

                results = conn.execute(
                    "SELECT * FROM agent_tool_results WHERE call_id IN "
                    "(SELECT call_id FROM agent_tool_calls WHERE interaction_id = ?)",
                    (interaction["id"],),
                ).fetchall()
                interaction["tool_results"] = []
                for r in results:
                    result_dict = dict(r)
                    result_dict["success"] = bool(result_dict["success"])
                    interaction["tool_results"].append(result_dict)

                workflow["interactions"].append(interaction)

            return workflow

    def get_table_row_count(self, table_name: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table_name}"  # noqa: S608
            ).fetchone()
            return int(row[0]) if row else 0


def _lookup_workflow_pk(conn: sqlite3.Connection, workflow_id: str) -> int:
    row = conn.execute(
        "SELECT id FROM agent_workflows WHERE workflow_id = ?",
        (workflow_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Workflow {workflow_id} not found after insert")
    return int(row[0])


class _SQLAlchemyBackend(_Backend):
    """PostgreSQL backend via SQLAlchemy Core."""

    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url)
        self.metadata = MetaData()
        self._define_tables()
        self.metadata.create_all(self.engine)

    def _define_tables(self) -> None:
        self._workflows = Table(
            "agent_workflows",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("workflow_id", String, nullable=False, unique=True),
            Column("agent_id", String, nullable=False),
            Column("task_description", Text, nullable=False),
            Column("status", String(20), nullable=False),
            Column("started_at", Float, nullable=False),
            Column("ended_at", Float),
            Column("error", Text),
            Column("metadata_json", Text),
        )

        self._interactions = Table(
            "agent_interactions",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column(
                "workflow_id",
                String,
                ForeignKey("agent_workflows.workflow_id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("turn_number", Integer, nullable=False),
            Column("reasoning", Text),
            Column("messages_json", Text),
            Column("state_before_json", Text),
            Column("state_after_json", Text),
            Column("duration_ms", Float),
            Column("success", Boolean, nullable=False),
            Column("error", Text),
            Index(
                "uq_agent_interactions_workflow_turn",
                "workflow_id",
                "turn_number",
                unique=True,
            ),
        )

        self._tool_calls = Table(
            "agent_tool_calls",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("call_id", String, nullable=False, unique=True),
            Column("workflow_id", String, nullable=False),
            Column(
                "interaction_id",
                Integer,
                ForeignKey("agent_interactions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("tool_name", String, nullable=False),
            Column("arguments_json", Text, nullable=False),
            Column("call_number", Integer, nullable=False),
            Column("timestamp", Float, nullable=False),
            Index("idx_agent_tool_calls_name", "tool_name"),
        )

        self._tool_results = Table(
            "agent_tool_results",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column(
                "call_id",
                String,
                ForeignKey("agent_tool_calls.call_id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("workflow_id", String, nullable=False),
            Column("success", Boolean, nullable=False),
            Column("output", Text),
            Column("error", Text),
            Column("execution_time_ms", Float),
        )

    def persist_workflow(self, workflow: AgentWorkflow) -> int:
        # Upsert the workflow row, then wipe and re-insert all child rows
        # from the workflow object (the source of truth at persist time).
        # Deleting agent_interactions cascades to agent_tool_calls and
        # agent_tool_results via ON DELETE CASCADE, dropping any turns no
        # longer present in the current payload (matches SQLite path).
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO agent_workflows
                        (workflow_id, agent_id, task_description, status,
                         started_at, ended_at, error, metadata_json)
                    VALUES (:wid, :aid, :task, :status, :started, :ended,
                            :err, :meta)
                    ON CONFLICT (workflow_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        ended_at = EXCLUDED.ended_at,
                        error = EXCLUDED.error,
                        metadata_json = EXCLUDED.metadata_json
                    """
                ),
                {
                    "wid": workflow.workflow_id,
                    "aid": workflow.agent_id,
                    "task": workflow.task_description,
                    "status": workflow.status,
                    "started": workflow.started_at,
                    "ended": workflow.ended_at,
                    "err": workflow.error,
                    "meta": json.dumps(workflow.metadata),
                },
            )
            row = conn.execute(
                text("SELECT id FROM agent_workflows WHERE workflow_id = :wid"),
                {"wid": workflow.workflow_id},
            ).fetchone()
            assert row is not None, "INSERT did not create or update a row"
            workflow_pk = int(row[0])
            conn.execute(
                text("DELETE FROM agent_interactions WHERE workflow_id = :wid"),
                {"wid": workflow.workflow_id},
            )

            for interaction in workflow.interactions:
                interaction_row = conn.execute(
                    text(
                        """
                        INSERT INTO agent_interactions
                            (workflow_id, turn_number, reasoning, messages_json,
                             state_before_json, state_after_json, duration_ms,
                             success, error)
                        VALUES (:wid, :turn, :reason, :msgs, :sb, :sa,
                                :dur, :ok, :err)
                        RETURNING id
                        """
                    ),
                    {
                        "wid": workflow.workflow_id,
                        "turn": interaction.turn_number,
                        "reason": interaction.reasoning,
                        "msgs": json.dumps(
                            [
                                {
                                    "role": m.role,
                                    "content": m.content,
                                    "timestamp": m.timestamp,
                                }
                                for m in interaction.messages
                            ]
                        ),
                        "sb": json.dumps(interaction.state_before),
                        "sa": json.dumps(interaction.state_after),
                        "dur": interaction.duration_ms,
                        "ok": interaction.success,
                        "err": interaction.error,
                    },
                ).fetchone()
                assert interaction_row is not None
                interaction_id = int(interaction_row[0])

                for call in interaction.tool_calls:
                    conn.execute(
                        text(
                            """
                            INSERT INTO agent_tool_calls
                                (call_id, workflow_id, interaction_id, tool_name,
                                 arguments_json, call_number, timestamp)
                            VALUES (:cid, :wid, :iid, :name, :args, :num, :ts)
                            """
                        ),
                        {
                            "cid": call.id,
                            "wid": workflow.workflow_id,
                            "iid": interaction_id,
                            "name": call.tool_name,
                            "args": json.dumps(call.arguments),
                            "num": call.call_number,
                            "ts": call.timestamp,
                        },
                    )

                for result in interaction.tool_results:
                    conn.execute(
                        text(
                            """
                            INSERT INTO agent_tool_results
                                (call_id, workflow_id, success, output, error,
                                 execution_time_ms)
                            VALUES (:cid, :wid, :ok, :out, :err, :ms)
                            """
                        ),
                        {
                            "cid": result.tool_call_id,
                            "wid": workflow.workflow_id,
                            "ok": result.success,
                            "out": result.output,
                            "err": result.error,
                            "ms": result.execution_time_ms,
                        },
                    )

            return workflow_pk

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        with self.engine.connect() as conn:
            row = conn.execute(
                self._workflows.select().where(
                    self._workflows.c.workflow_id == workflow_id
                )
            ).fetchone()
            if row is None:
                return None
            workflow = dict(row._mapping)
            workflow["metadata"] = json.loads(workflow.pop("metadata_json") or "{}")
            workflow["interactions"] = []

            interactions = conn.execute(
                self._interactions.select()
                .where(self._interactions.c.workflow_id == workflow_id)
                .order_by(self._interactions.c.turn_number)
            ).fetchall()
            for inter_row in interactions:
                interaction = dict(inter_row._mapping)
                interaction["messages"] = json.loads(
                    interaction.pop("messages_json") or "[]"
                )
                interaction["state_before"] = json.loads(
                    interaction.pop("state_before_json") or "{}"
                )
                interaction["state_after"] = json.loads(
                    interaction.pop("state_after_json") or "{}"
                )

                calls = conn.execute(
                    self._tool_calls.select()
                    .where(self._tool_calls.c.interaction_id == interaction["id"])
                    .order_by(self._tool_calls.c.call_number)
                ).fetchall()
                interaction["tool_calls"] = []
                for c in calls:
                    call_dict = dict(c._mapping)
                    call_dict["arguments"] = json.loads(
                        call_dict.pop("arguments_json") or "{}"
                    )
                    interaction["tool_calls"].append(call_dict)

                call_ids = [c["call_id"] for c in interaction["tool_calls"]]
                if call_ids:
                    results = conn.execute(
                        self._tool_results.select().where(
                            self._tool_results.c.call_id.in_(call_ids)
                        )
                    ).fetchall()
                    interaction["tool_results"] = [dict(r._mapping) for r in results]
                else:
                    interaction["tool_results"] = []

                workflow["interactions"].append(interaction)

            return workflow

    def get_table_row_count(self, table_name: str) -> int:
        with self.engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))  # noqa: S608
            return int(result.scalar() or 0)


class AgentWorkflowDatabase:
    """Facade selecting the right backend at construction time."""

    def __init__(
        self,
        *,
        db_path: Optional[str] = None,
        database_url: Optional[str] = None,
    ) -> None:
        if db_path:
            self._backend: _Backend = _SQLiteBackend(db_path)
        elif database_url:
            self._backend = self._backend_from_url(database_url)
        else:
            env_url = os.environ.get("AGENT_WORKFLOW_DATABASE_URL") or os.environ.get(
                "DATABASE_URL"
            )
            if not env_url:
                from .exceptions import MissingEnvironmentError

                raise MissingEnvironmentError(variable="DATABASE_URL")
            self._backend = self._backend_from_url(env_url)

    @staticmethod
    def _backend_from_url(url: str) -> _Backend:
        if url.startswith("sqlite:///"):
            return _SQLiteBackend(url.removeprefix("sqlite:///"))
        if HAS_SQLALCHEMY:
            return _SQLAlchemyBackend(url)
        from .exceptions import MissingDependencyError

        raise MissingDependencyError(
            package="sqlalchemy",
            install_hint="uv sync --extra superset",
        )

    def persist_workflow(self, workflow: AgentWorkflow) -> int:
        return self._backend.persist_workflow(workflow)

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        return self._backend.get_workflow(workflow_id)

    def get_table_row_count(self, table_name: str) -> int:
        return self._backend.get_table_row_count(table_name)
