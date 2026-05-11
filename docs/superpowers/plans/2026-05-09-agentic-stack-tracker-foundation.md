# Agentic Stack Tracker — Foundation (Issue #350) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the schema spine (`session_id`-keyed) for the Agentic Stack Tracker — four new tables in a new `harness_db.py` module, dataclasses in `harness_models.py`, plus a nullable `session_id` column on the existing `test_runs` table — without changing observable behaviour anywhere else.

**Architecture:** Mirrors `src/rfc/test_database.py`'s shape: `_HarnessBackend` ABC with `_SQLiteHarnessBackend` and `_SQLAlchemyHarnessBackend` implementations, fronted by a `HarnessDatabase` facade that selects the backend from `db_path=` or `database_url=` keyword args. SQLite is always available; SQLAlchemy is gated behind `HAS_SQLALCHEMY`. Idempotent DDL embedded in `__init__` — no Alembic.

**Tech Stack:** Python 3.11+, sqlite3 stdlib, SQLAlchemy (optional, `superset` extra), pytest, Robot Framework.

**Spec:** [docs/superpowers/specs/2026-05-09-agentic-stack-tracker-foundation-design.md](../specs/2026-05-09-agentic-stack-tracker-foundation-design.md)

**Spec correction noted during planning:** Section 3 of the spec showed `def __init__(self, db_path_or_url: str)`, but the actual `TestDatabase` convention this is mirroring uses keyword-only `db_path=` / `database_url=`. This plan follows the real `TestDatabase` pattern (which is what the spec intended).

**Per-step verification suite (run before every commit):**
```bash
uv run pytest && \
pre-commit run --all-files && \
make code-quality-check && \
make robot-dryrun && \
make robot-agentic-coding
```
The `make robot-dryrun` baseline currently has 12 unrelated Browser Library failures (see `humans/TODO.md`). Treat those as the known baseline — the suite is "green" if no *new* failures appear.

---

## Task 0: Add `robot-agentic-coding` make target

**Files:**
- Modify: `Makefile` (after the existing `robot-agentic-injection` target near line 91, and the `robot-agent` line near 94)

- [ ] **Step 1: Read existing target as template**

Read `Makefile` lines 88–96 to confirm the exact format of `robot-agentic-injection` and `robot-agent`. Expected current text:

```makefile
robot-agentic-injection: ## Run agentic prompt injection resistance tests
	$(ROBOT) -d results/$(VERSION)/agentic_injection $(LISTENER) $(ARGS) robot/agentic_injection/

robot-agent: robot-agentic-injection ## Master agent test suite (currently agentic injection)
```

- [ ] **Step 2: Add `robot-agentic-coding` and update `robot-agent`**

Use Edit on `Makefile`:

`old_string`:
```makefile
robot-agentic-injection: ## Run agentic prompt injection resistance tests
	$(ROBOT) -d results/$(VERSION)/agentic_injection $(LISTENER) $(ARGS) robot/agentic_injection/

robot-agent: robot-agentic-injection ## Master agent test suite (currently agentic injection)
```

`new_string`:
```makefile
robot-agentic-injection: ## Run agentic prompt injection resistance tests
	$(ROBOT) -d results/$(VERSION)/agentic_injection $(LISTENER) $(ARGS) robot/agentic_injection/

robot-agentic-coding: ## Run agentic coding behaviour tests
	$(ROBOT) -d results/$(VERSION)/agentic_coding $(LISTENER) $(ARGS) robot/agentic_coding/

robot-agent: robot-agentic-injection robot-agentic-coding ## Master agent test suite (agentic injection + coding)
```

- [ ] **Step 3: Verify Makefile parses and target appears**

Run: `make help | grep -E "robot-agentic-coding|robot-agent"`
Expected: both lines present, with `robot-agent` listing the new master-suite description.

- [ ] **Step 4: Verify dependency wiring with dry-run**

Run: `make -n robot-agent | head -10`
Expected: output shows the commands for both `robot-agentic-injection` and `robot-agentic-coding`, in that order.

- [ ] **Step 5: Smoke-test the new target (parse-only — Ollama optional)**

Run: `uv run robot --dryrun -d /tmp/agentic-coding-dryrun robot/agentic_coding/`
Expected: prints the suite execution summary; passes count + skipped count > 0; no syntax errors. (Failures from missing keywords would have surfaced — none expected since `agentic_coding/` doesn't use Browser Library.)

- [ ] **Step 6: Run the standard verification suite**

Run:
```bash
uv run pytest && pre-commit run --all-files && make code-quality-check && make robot-dryrun
```
Expected: pytest green, pre-commit green, code-quality green, robot-dryrun has the *known baseline* 12 Browser failures and no others.

- [ ] **Step 7: Commit**

```bash
git add Makefile
git commit -m "$(cat <<'EOF'
chore: add robot-agentic-coding make target, include in robot-agent

The robot/agentic_coding/ suite existed but had no Makefile entry,
so it was never run as part of the standard verification flow.
robot-agent now depends on both agentic_injection and agentic_coding,
giving the master agent suite full coverage of agentic behaviours.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 1: `harness_models.py` — dataclasses

**Files:**
- Create: `src/rfc/harness_models.py`
- Create: `tests/test_harness_models.py`

- [ ] **Step 1: Write failing tests for all four dataclasses**

Create `tests/test_harness_models.py`:

```python
"""Tests for harness dataclasses (CLAUDE.md: no Optional fields)."""

from rfc.harness_models import (
    AgenticHarness,
    AgenticMetric,
    AgenticPlugin,
    AgenticSkill,
)


class TestAgenticHarness:
    def test_required_fields(self) -> None:
        h = AgenticHarness(
            session_id="abc123",
            tool_name="claude-code",
            started_at="2026-05-09T00:00:00Z",
        )
        assert h.session_id == "abc123"
        assert h.tool_name == "claude-code"
        assert h.started_at == "2026-05-09T00:00:00Z"

    def test_default_fields_are_concrete_not_none(self) -> None:
        h = AgenticHarness(
            session_id="abc123",
            tool_name="claude-code",
            started_at="2026-05-09T00:00:00Z",
        )
        assert h.tool_version == ""
        assert h.model_id == ""
        assert h.rfc_version == ""
        assert h.branch == ""
        assert h.ended_at == ""
        assert h.outcome == ""
        assert h.replay_of_recording_id == ""


class TestAgenticPlugin:
    def test_required_fields(self) -> None:
        p = AgenticPlugin(
            session_id="abc123",
            plugin_name="robotframework-browser",
            recorded_at="2026-05-09T00:00:00Z",
        )
        assert p.session_id == "abc123"
        assert p.plugin_name == "robotframework-browser"
        assert p.recorded_at == "2026-05-09T00:00:00Z"

    def test_default_fields(self) -> None:
        p = AgenticPlugin(
            session_id="abc123",
            plugin_name="robotframework-browser",
            recorded_at="2026-05-09T00:00:00Z",
        )
        assert p.semver == ""
        assert p.source == ""
        assert p.id == ""


class TestAgenticSkill:
    def test_required_fields(self) -> None:
        s = AgenticSkill(
            session_id="abc123",
            skill_path="robot/safety/safety.resource",
            recorded_at="2026-05-09T00:00:00Z",
        )
        assert s.session_id == "abc123"
        assert s.skill_path == "robot/safety/safety.resource"

    def test_default_fields(self) -> None:
        s = AgenticSkill(
            session_id="abc123",
            skill_path="robot/safety/safety.resource",
            recorded_at="2026-05-09T00:00:00Z",
        )
        assert s.git_sha == ""
        assert s.skill_name == ""
        assert s.id == ""


class TestAgenticMetric:
    def test_required_fields(self) -> None:
        m = AgenticMetric(
            session_id="abc123",
            metric_key="tokens_in",
            recorded_at="2026-05-09T00:00:00Z",
        )
        assert m.session_id == "abc123"
        assert m.metric_key == "tokens_in"

    def test_sentinel_defaults_match_test_database_convention(self) -> None:
        m = AgenticMetric(
            session_id="abc123",
            metric_key="tokens_in",
            recorded_at="2026-05-09T00:00:00Z",
        )
        # -1 sentinel matches src/rfc/test_database.py TestRun.id convention.
        assert m.test_run_id == -1
        assert m.test_result_id == -1
        assert m.metric_value == 0.0
        assert m.id == ""
```

- [ ] **Step 2: Run the test, verify it fails with ImportError**

Run: `uv run pytest tests/test_harness_models.py -v 2>&1 | tail -20`
Expected: collection error / `ModuleNotFoundError: No module named 'rfc.harness_models'`.

- [ ] **Step 3: Create `src/rfc/harness_models.py`**

```python
"""Dataclasses for the Agentic Stack Tracker.

Pure dataclasses with no DB imports, so downstream modules can use the
types without pulling in sqlite3 / SQLAlchemy. CLAUDE.md forbids
Optional fields on database dataclasses; concrete defaults (empty
string for text, -1 sentinel for int IDs) are used instead.
"""

from dataclasses import dataclass


@dataclass
class AgenticHarness:
    """One row per Claude-Code / Codex / OpenCode session.

    session_id is the spine joining all agentic_* tables and (via a
    nullable column) test_runs. It is also the PRIMARY KEY of
    agentic_harnesses.
    """

    session_id: str
    tool_name: str
    started_at: str  # UTC ISO-8601
    tool_version: str = ""
    model_id: str = ""
    rfc_version: str = ""
    branch: str = ""
    ended_at: str = ""
    outcome: str = ""  # "" while running; 'success' | 'partial' | 'failed' when ended
    replay_of_recording_id: str = ""  # nullable; points at dialog_recordings.id (Phase 2)


@dataclass
class AgenticPlugin:
    """Plugin snapshot at session start. UNIQUE(session_id, plugin_name)."""

    session_id: str
    plugin_name: str
    recorded_at: str
    semver: str = ""
    source: str = ""  # 'pyproject' | 'pip' | 'manual'
    id: str = ""  # backend assigns uuid4().hex when blank


@dataclass
class AgenticSkill:
    """Skill (Robot .resource) snapshot. UNIQUE(session_id, skill_path)."""

    session_id: str
    skill_path: str
    recorded_at: str
    git_sha: str = ""
    skill_name: str = ""
    id: str = ""


@dataclass
class AgenticMetric:
    """EAV metric. test_run_id and test_result_id are -1 when session-level."""

    session_id: str
    metric_key: str
    recorded_at: str
    metric_value: float = 0.0
    test_run_id: int = -1  # -1 sentinel matches TestRun.id convention
    test_result_id: int = -1
    id: str = ""
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `uv run pytest tests/test_harness_models.py -v 2>&1 | tail -25`
Expected: 8 tests pass (2 per dataclass).

- [ ] **Step 5: Run the verification suite**

```bash
uv run pytest && \
pre-commit run --all-files && \
make code-quality-check && \
make robot-dryrun && \
make robot-agentic-coding
```
Expected: pytest green (now 2716 passing), pre-commit green, code-quality green, robot-dryrun shows only the known 12 Browser baseline failures, robot-agentic-coding green (Ollama dependent).

- [ ] **Step 6: Commit**

```bash
git add src/rfc/harness_models.py tests/test_harness_models.py
git commit -m "$(cat <<'EOF'
feat: add agentic harness dataclasses (harness_models.py)

Foundation types for the Agentic Stack Tracker (Issue #350):
AgenticHarness, AgenticPlugin, AgenticSkill, AgenticMetric. Pure
dataclasses with concrete defaults so downstream modules can use the
types without pulling in sqlite3 / SQLAlchemy. Per CLAUDE.md, no
Optional fields — empty string for text, -1 sentinel for int IDs
(matches the TestRun.id convention).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `harness_db.py` — SQLite backend + `HarnessDatabase` facade

**Files:**
- Create: `src/rfc/harness_db.py`
- Create: `tests/test_harness_db.py`

This task builds the SQLite-only backend plus the public facade. SQLAlchemy support is added in Task 3 by parametrizing the existing test fixture; design the test file so that's a small change.

### 2A — Module skeleton + schema initialisation

- [ ] **Step 1: Write failing test for backend init + idempotence**

Create `tests/test_harness_db.py`:

```python
"""Tests for HarnessDatabase. Behavioural tests run against SQLite via
tmp_path. Task 3 parametrises the same tests against a sqlite:/// URL
to exercise the SQLAlchemy backend.
"""

import sqlite3

import pytest

from rfc.harness_db import HarnessDatabase
from rfc.harness_models import (
    AgenticHarness,
    AgenticMetric,
    AgenticPlugin,
    AgenticSkill,
)

NOW = "2026-05-09T00:00:00Z"


@pytest.fixture
def harness_db(tmp_path):
    """SQLite-backed HarnessDatabase. Task 3 will parametrise this."""
    db_file = tmp_path / "harness.db"
    return HarnessDatabase(db_path=str(db_file))


class TestSchema:
    def test_init_creates_tables(self, tmp_path):
        db_file = tmp_path / "harness.db"
        HarnessDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert {
            "agentic_harnesses",
            "agentic_plugins",
            "agentic_skills",
            "agentic_metrics",
        }.issubset(tables)

    def test_init_is_idempotent(self, tmp_path):
        db_file = tmp_path / "harness.db"
        HarnessDatabase(db_path=str(db_file))
        HarnessDatabase(db_path=str(db_file))  # must not raise

    def test_foreign_keys_enabled(self, tmp_path):
        db_file = tmp_path / "harness.db"
        HarnessDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            # Insert into child without parent should fail FK constraint.
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO agentic_plugins (id, session_id, plugin_name, recorded_at) "
                    "VALUES (?, ?, ?, ?)",
                    ("p1", "no-such-session", "robotframework-browser", NOW),
                )
```

- [ ] **Step 2: Run the test, verify it fails with ModuleNotFoundError**

Run: `uv run pytest tests/test_harness_db.py -v 2>&1 | tail -10`
Expected: `ModuleNotFoundError: No module named 'rfc.harness_db'`.

- [ ] **Step 3: Create `src/rfc/harness_db.py` with module skeleton + SQLite backend init**

```python
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
    from sqlalchemy import (  # type: ignore[import-not-found]
        Column,
        Float,
        Integer,
        MetaData,
        String,
        Table,
        UniqueConstraint,
        create_engine,
        text,
    )
    from sqlalchemy.engine import Engine  # type: ignore[import-not-found]

    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


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

    # CRUD methods added in subsequent steps. raise NotImplementedError for now
    # so the test_init tests pass without us implementing everything yet.

    def save_harness(self, harness: AgenticHarness) -> str:
        raise NotImplementedError

    def end_harness(self, session_id: str, outcome: str, ended_at: str) -> None:
        raise NotImplementedError

    def get_harness(self, session_id: str) -> Optional[AgenticHarness]:
        raise NotImplementedError

    def list_harnesses(
        self, *, tool_name: str = "", limit: int = 50
    ) -> list[AgenticHarness]:
        raise NotImplementedError

    def save_plugins(self, plugins: list[AgenticPlugin]) -> list[str]:
        raise NotImplementedError

    def save_skills(self, skills: list[AgenticSkill]) -> list[str]:
        raise NotImplementedError

    def get_plugins(self, session_id: str) -> list[AgenticPlugin]:
        raise NotImplementedError

    def get_skills(self, session_id: str) -> list[AgenticSkill]:
        raise NotImplementedError

    def save_metric(self, metric: AgenticMetric) -> str:
        raise NotImplementedError

    def save_metrics(self, metrics: list[AgenticMetric]) -> list[str]:
        raise NotImplementedError

    def get_metrics(
        self, session_id: str, *, metric_key: str = ""
    ) -> list[AgenticMetric]:
        raise NotImplementedError

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
```

- [ ] **Step 4: Run the schema tests, verify they pass**

Run: `uv run pytest tests/test_harness_db.py::TestSchema -v 2>&1 | tail -15`
Expected: 3 tests pass (`test_init_creates_tables`, `test_init_is_idempotent`, `test_foreign_keys_enabled`).

### 2B — Harness lifecycle CRUD

- [ ] **Step 5: Add failing tests for harness lifecycle**

Append to `tests/test_harness_db.py`:

```python
class TestHarnessLifecycle:
    def test_save_and_get(self, harness_db):
        h = AgenticHarness(
            session_id="s1", tool_name="claude-code", started_at=NOW,
            tool_version="4.7", model_id="claude-opus-4-7",
        )
        sid = harness_db.save_harness(h)
        assert sid == "s1"
        fetched = harness_db.get_harness("s1")
        assert fetched is not None
        assert fetched.tool_name == "claude-code"
        assert fetched.tool_version == "4.7"
        assert fetched.outcome == ""  # not None — concrete default

    def test_get_harness_returns_none_if_missing(self, harness_db):
        assert harness_db.get_harness("nope") is None

    def test_end_harness_sets_outcome_and_ended_at(self, harness_db):
        harness_db.save_harness(
            AgenticHarness(session_id="s1", tool_name="claude-code", started_at=NOW)
        )
        harness_db.end_harness("s1", outcome="success", ended_at="2026-05-09T01:00:00Z")
        fetched = harness_db.get_harness("s1")
        assert fetched is not None
        assert fetched.outcome == "success"
        assert fetched.ended_at == "2026-05-09T01:00:00Z"

    def test_end_harness_raises_if_missing(self, harness_db):
        with pytest.raises(LookupError):
            harness_db.end_harness("nope", outcome="failed", ended_at=NOW)

    def test_list_harnesses_reverse_chronological(self, harness_db):
        harness_db.save_harness(
            AgenticHarness(session_id="s1", tool_name="claude-code", started_at="2026-05-09T00:00:00Z")
        )
        harness_db.save_harness(
            AgenticHarness(session_id="s2", tool_name="codex", started_at="2026-05-09T01:00:00Z")
        )
        rows = harness_db.list_harnesses()
        assert [r.session_id for r in rows] == ["s2", "s1"]

    def test_list_harnesses_filter_by_tool(self, harness_db):
        harness_db.save_harness(
            AgenticHarness(session_id="s1", tool_name="claude-code", started_at="2026-05-09T00:00:00Z")
        )
        harness_db.save_harness(
            AgenticHarness(session_id="s2", tool_name="codex", started_at="2026-05-09T01:00:00Z")
        )
        rows = harness_db.list_harnesses(tool_name="codex")
        assert [r.session_id for r in rows] == ["s2"]

    def test_list_harnesses_respects_limit(self, harness_db):
        for i in range(5):
            harness_db.save_harness(
                AgenticHarness(
                    session_id=f"s{i}", tool_name="claude-code",
                    started_at=f"2026-05-09T0{i}:00:00Z",
                )
            )
        assert len(harness_db.list_harnesses(limit=3)) == 3
```

- [ ] **Step 6: Run the new tests, verify they fail with NotImplementedError**

Run: `uv run pytest tests/test_harness_db.py::TestHarnessLifecycle -v 2>&1 | tail -25`
Expected: 7 failures, each raising NotImplementedError.

- [ ] **Step 7: Implement harness lifecycle in `_SQLiteHarnessBackend`**

In `src/rfc/harness_db.py`, replace the `save_harness`, `end_harness`, `get_harness`, and `list_harnesses` placeholder methods on `_SQLiteHarnessBackend`:

```python
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
```

- [ ] **Step 8: Run lifecycle tests, verify pass**

Run: `uv run pytest tests/test_harness_db.py::TestHarnessLifecycle -v 2>&1 | tail -15`
Expected: 7 tests pass.

### 2C — Plugin and skill snapshots

- [ ] **Step 9: Add failing tests for snapshots**

Append to `tests/test_harness_db.py`:

```python
class TestSnapshots:
    @pytest.fixture(autouse=True)
    def _seed_session(self, harness_db):
        # All snapshot tests need a parent harness row for FK validity.
        harness_db.save_harness(
            AgenticHarness(session_id="s1", tool_name="claude-code", started_at=NOW)
        )

    def test_save_plugins_assigns_uuid_when_id_blank(self, harness_db):
        ids = harness_db.save_plugins(
            [
                AgenticPlugin(session_id="s1", plugin_name="robotframework-browser",
                              recorded_at=NOW),
                AgenticPlugin(session_id="s1", plugin_name="anthropic", recorded_at=NOW),
            ]
        )
        assert all(len(i) == 32 for i in ids)  # uuid4().hex
        assert ids[0] != ids[1]

    def test_save_plugins_preserves_explicit_id(self, harness_db):
        ids = harness_db.save_plugins(
            [
                AgenticPlugin(session_id="s1", plugin_name="robotframework-browser",
                              recorded_at=NOW, id="explicit-id-1"),
            ]
        )
        assert ids == ["explicit-id-1"]

    def test_save_plugins_idempotent_on_session_plus_name(self, harness_db):
        # Insert twice with same (session_id, plugin_name) → second wins via OR REPLACE.
        harness_db.save_plugins(
            [AgenticPlugin(session_id="s1", plugin_name="anthropic",
                           recorded_at=NOW, semver="0.40.0")]
        )
        harness_db.save_plugins(
            [AgenticPlugin(session_id="s1", plugin_name="anthropic",
                           recorded_at=NOW, semver="0.41.0")]
        )
        plugins = harness_db.get_plugins("s1")
        assert len(plugins) == 1
        assert plugins[0].semver == "0.41.0"

    def test_get_plugins_empty(self, harness_db):
        assert harness_db.get_plugins("s1") == []

    def test_save_skills_returns_ids_in_input_order(self, harness_db):
        ids = harness_db.save_skills(
            [
                AgenticSkill(session_id="s1", skill_path="robot/safety/safety.resource",
                             recorded_at=NOW),
                AgenticSkill(session_id="s1", skill_path="robot/math/math.resource",
                             recorded_at=NOW),
                AgenticSkill(session_id="s1", skill_path="robot/docker/bash/bash.resource",
                             recorded_at=NOW),
            ]
        )
        assert len(ids) == 3
        # Re-fetch by id to verify positional alignment.
        skills = harness_db.get_skills("s1")
        skills_by_path = {s.skill_path: s.id for s in skills}
        assert skills_by_path["robot/safety/safety.resource"] == ids[0]
        assert skills_by_path["robot/math/math.resource"] == ids[1]
        assert skills_by_path["robot/docker/bash/bash.resource"] == ids[2]
```

- [ ] **Step 10: Run snapshot tests, verify they fail (NotImplementedError)**

Run: `uv run pytest tests/test_harness_db.py::TestSnapshots -v 2>&1 | tail -15`
Expected: 5 failures.

- [ ] **Step 11: Implement snapshot CRUD on `_SQLiteHarnessBackend`**

Replace the `save_plugins`, `save_skills`, `get_plugins`, `get_skills` placeholders:

```python
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
```

- [ ] **Step 12: Run snapshot tests, verify pass**

Run: `uv run pytest tests/test_harness_db.py::TestSnapshots -v 2>&1 | tail -15`
Expected: 5 tests pass.

### 2D — Metrics

- [ ] **Step 13: Add failing tests for metrics**

Append to `tests/test_harness_db.py`:

```python
class TestMetrics:
    @pytest.fixture(autouse=True)
    def _seed_session(self, harness_db):
        harness_db.save_harness(
            AgenticHarness(session_id="s1", tool_name="claude-code", started_at=NOW)
        )

    def test_save_metric_session_only(self, harness_db):
        mid = harness_db.save_metric(
            AgenticMetric(session_id="s1", metric_key="tokens_in",
                          recorded_at=NOW, metric_value=1234.0)
        )
        assert len(mid) == 32  # uuid4().hex
        metrics = harness_db.get_metrics("s1")
        assert len(metrics) == 1
        assert metrics[0].metric_key == "tokens_in"
        assert metrics[0].metric_value == 1234.0
        assert metrics[0].test_run_id == -1   # NULL → sentinel
        assert metrics[0].test_result_id == -1

    def test_save_metric_with_test_run_id(self, harness_db):
        harness_db.save_metric(
            AgenticMetric(session_id="s1", metric_key="latency_ms",
                          recorded_at=NOW, metric_value=42.5, test_run_id=7)
        )
        m = harness_db.get_metrics("s1")[0]
        assert m.test_run_id == 7
        assert m.test_result_id == -1

    def test_save_metrics_bulk_returns_ids_in_order(self, harness_db):
        ids = harness_db.save_metrics(
            [
                AgenticMetric(session_id="s1", metric_key="tokens_in",
                              recorded_at=NOW, metric_value=100.0),
                AgenticMetric(session_id="s1", metric_key="tokens_out",
                              recorded_at=NOW, metric_value=50.0),
            ]
        )
        assert len(ids) == 2
        assert ids[0] != ids[1]

    def test_get_metrics_filtered_by_key(self, harness_db):
        harness_db.save_metrics(
            [
                AgenticMetric(session_id="s1", metric_key="tokens_in",
                              recorded_at=NOW, metric_value=100.0),
                AgenticMetric(session_id="s1", metric_key="tokens_out",
                              recorded_at=NOW, metric_value=50.0),
                AgenticMetric(session_id="s1", metric_key="tokens_in",
                              recorded_at=NOW, metric_value=200.0),
            ]
        )
        in_only = harness_db.get_metrics("s1", metric_key="tokens_in")
        assert len(in_only) == 2
        assert {m.metric_value for m in in_only} == {100.0, 200.0}
```

- [ ] **Step 14: Run metric tests, verify they fail (NotImplementedError)**

Run: `uv run pytest tests/test_harness_db.py::TestMetrics -v 2>&1 | tail -15`
Expected: 4 failures.

- [ ] **Step 15: Implement metric CRUD on `_SQLiteHarnessBackend`**

Replace the `save_metric`, `save_metrics`, `get_metrics` placeholders:

```python
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
```

- [ ] **Step 16: Run metric tests, verify pass**

Run: `uv run pytest tests/test_harness_db.py::TestMetrics -v 2>&1 | tail -15`
Expected: 4 tests pass.

### 2E — Cascade and introspection

- [ ] **Step 17: Add failing tests for cascade + introspection**

Append to `tests/test_harness_db.py`:

```python
class TestCascades:
    def test_delete_harness_cascades_to_children(self, harness_db, tmp_path):
        harness_db.save_harness(
            AgenticHarness(session_id="s1", tool_name="claude-code", started_at=NOW)
        )
        harness_db.save_plugins(
            [AgenticPlugin(session_id="s1", plugin_name="anthropic", recorded_at=NOW)]
        )
        harness_db.save_skills(
            [AgenticSkill(session_id="s1", skill_path="robot/safety/safety.resource",
                          recorded_at=NOW)]
        )
        harness_db.save_metric(
            AgenticMetric(session_id="s1", metric_key="tokens_in",
                          recorded_at=NOW, metric_value=100.0)
        )
        # Delete via direct SQL (no public delete API).
        # Reach into the SQLite backend to get the path.
        backend = harness_db._backend  # type: ignore[attr-defined]
        with sqlite3.connect(backend.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("DELETE FROM agentic_harnesses WHERE session_id = ?", ("s1",))
        assert harness_db.get_plugins("s1") == []
        assert harness_db.get_skills("s1") == []
        assert harness_db.get_metrics("s1") == []


class TestIntrospection:
    def test_get_version_returns_sqlite_version(self, harness_db):
        v = harness_db.get_version()
        assert v.count(".") >= 2  # e.g., '3.45.1'

    def test_get_table_row_count(self, harness_db):
        assert harness_db.get_table_row_count("agentic_harnesses") == 0
        harness_db.save_harness(
            AgenticHarness(session_id="s1", tool_name="claude-code", started_at=NOW)
        )
        assert harness_db.get_table_row_count("agentic_harnesses") == 1

    def test_get_table_row_count_rejects_unknown_table(self, harness_db):
        with pytest.raises(ValueError):
            harness_db.get_table_row_count("test_runs")  # not a harness table
```

- [ ] **Step 18: Run new tests, verify pass (cascade + introspection were already implemented)**

Run: `uv run pytest tests/test_harness_db.py::TestCascades tests/test_harness_db.py::TestIntrospection -v 2>&1 | tail -15`
Expected: 4 tests pass. (Cascade works because `PRAGMA foreign_keys = ON` is set and the `ON DELETE CASCADE` is in the schema; introspection methods were implemented in step 3.)

### 2F — Final verification + commit

- [ ] **Step 19: Run the full new-test file**

Run: `uv run pytest tests/test_harness_db.py -v 2>&1 | tail -30`
Expected: 23 tests pass (3 schema + 7 lifecycle + 5 snapshots + 4 metrics + 1 cascade + 3 introspection).

- [ ] **Step 20: Run the verification suite**

```bash
uv run pytest && \
pre-commit run --all-files && \
make code-quality-check && \
make robot-dryrun && \
make robot-agentic-coding
```
Expected: pytest green (now ≈2739 passing), pre-commit green, code-quality green, robot-dryrun shows only the known 12 Browser baseline failures, robot-agentic-coding green.

- [ ] **Step 21: Commit**

```bash
git add src/rfc/harness_db.py tests/test_harness_db.py
git commit -m "$(cat <<'EOF'
feat: add HarnessDatabase SQLite backend (harness_db.py)

Implements the schema spine for the Agentic Stack Tracker (Issue #350)
with full SQLite-backed CRUD for AgenticHarness, AgenticPlugin,
AgenticSkill, and AgenticMetric. HarnessDatabase facade mirrors
TestDatabase's calling convention (db_path= or database_url=).

Schema highlights:
- session_id is the PRIMARY KEY of agentic_harnesses (the spine).
- agentic_metrics carries optional test_run_id / test_result_id for
  per-test linkage; both nullable so session-level metrics share the
  table.
- UNIQUE(session_id, plugin_name) and UNIQUE(session_id, skill_path)
  give snapshot calls idempotent INSERT OR REPLACE semantics.
- ON DELETE CASCADE on every child FK; PRAGMA foreign_keys = ON.

SQLAlchemy backend lands in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: SQLAlchemy backend

**Files:**
- Modify: `src/rfc/harness_db.py` (add `_SQLAlchemyHarnessBackend`, wire it into `HarnessDatabase.__init__`)
- Modify: `tests/test_harness_db.py` (parametrise `harness_db` fixture)

- [ ] **Step 1: Parametrise the test fixture and add a SQLAlchemy-skip guard**

Edit `tests/test_harness_db.py`. Replace the existing `harness_db` fixture with the parametrised version:

```python
from rfc.harness_db import HarnessDatabase, HAS_SQLALCHEMY


@pytest.fixture(params=["file_path", "sqlite_url"])
def harness_db(request, tmp_path):
    """Parametrised: SQLite via file_path AND via sqlite:/// URL.

    file_path → _SQLiteHarnessBackend.
    sqlite:/// URL → _SQLAlchemyHarnessBackend (skipped if sqlalchemy missing).
    """
    db_file = tmp_path / "harness.db"
    if request.param == "file_path":
        return HarnessDatabase(db_path=str(db_file))
    if not HAS_SQLALCHEMY:
        pytest.skip("sqlalchemy not installed (install with: uv sync --extra superset)")
    return HarnessDatabase(database_url=f"sqlite:///{db_file}")
```

The cascade test reaches into `harness_db._backend.db_path`, which only exists on the SQLite backend. Update it to skip on the SQLAlchemy parametrisation:

```python
class TestCascades:
    def test_delete_harness_cascades_to_children(self, harness_db, tmp_path):
        backend = harness_db._backend  # type: ignore[attr-defined]
        if not isinstance(backend, _SQLiteHarnessBackend):
            pytest.skip("cascade test reaches into SQLite backend internals")
        # ... rest of the test unchanged ...
```

Add the import at the top of `tests/test_harness_db.py`:

```python
from rfc.harness_db import HarnessDatabase, HAS_SQLALCHEMY, _SQLiteHarnessBackend
```

- [ ] **Step 2: Run the parametrised tests, verify SQLAlchemy parametrisation fails with NotImplementedError**

Run: `uv run pytest tests/test_harness_db.py -v 2>&1 | tail -50`
Expected: file_path parametrisations all pass; sqlite_url parametrisations fail because `HarnessDatabase.__init__` raises `NotImplementedError("SQLAlchemy backend lands in Task 3 of the foundation plan")`.

- [ ] **Step 3: Implement `_SQLAlchemyHarnessBackend`**

Edit `src/rfc/harness_db.py`. Add the SQLAlchemy backend class **after** `_SQLiteHarnessBackend` and **before** `class HarnessDatabase`:

```python
# ---------------------------------------------------------------------------
# SQLAlchemy backend
# ---------------------------------------------------------------------------


class _SQLAlchemyHarnessBackend(_HarnessBackend):
    """SQLAlchemy backend supporting both PostgreSQL and sqlite:/// URLs.

    The Postgres production path uses idempotent ALTER TABLE ... IF NOT
    EXISTS migrations; the sqlite:/// path is exercised by the test
    suite to confirm the SQLAlchemy CRUD methods themselves work.
    """

    _PG_MIGRATIONS: list[str] = []  # placeholder for future column adds

    def __init__(self, database_url: str) -> None:
        if not HAS_SQLALCHEMY:
            raise RuntimeError(
                "SQLAlchemy is required for non-sqlite database URLs. "
                "Install with: uv sync --extra superset"
            )
        self.engine: Engine = create_engine(database_url)
        self.metadata = MetaData()
        self._define_tables()
        try:
            self.metadata.create_all(self.engine)
        except Exception:
            logger.warning("create_all() failed; running migrations anyway")
        self._run_migrations()

    def _define_tables(self) -> None:
        self._harnesses = Table(
            "agentic_harnesses", self.metadata,
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
            "agentic_plugins", self.metadata,
            Column("id", String, primary_key=True),
            Column("session_id", String, nullable=False),
            Column("plugin_name", String, nullable=False),
            Column("semver", String),
            Column("source", String),
            Column("recorded_at", String, nullable=False),
            UniqueConstraint("session_id", "plugin_name",
                             name="uq_plugins_session_name"),
        )
        self._skills = Table(
            "agentic_skills", self.metadata,
            Column("id", String, primary_key=True),
            Column("session_id", String, nullable=False),
            Column("skill_path", String, nullable=False),
            Column("git_sha", String),
            Column("skill_name", String),
            Column("recorded_at", String, nullable=False),
            UniqueConstraint("session_id", "skill_path",
                             name="uq_skills_session_path"),
        )
        self._metrics = Table(
            "agentic_metrics", self.metadata,
            Column("id", String, primary_key=True),
            Column("session_id", String, nullable=False),
            Column("test_run_id", Integer),
            Column("test_result_id", Integer),
            Column("metric_key", String, nullable=False),
            Column("metric_value", Float),
            Column("recorded_at", String, nullable=False),
        )

    def _run_migrations(self) -> None:
        with self.engine.begin() as conn:
            for sql in self._PG_MIGRATIONS:
                try:
                    conn.execute(text(sql))
                except Exception as exc:  # idempotent: column already present, etc.
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
                metric_value=float(r.metric_value) if r.metric_value is not None else 0.0,
                test_run_id=r.test_run_id if r.test_run_id is not None else -1,
                test_result_id=r.test_result_id if r.test_result_id is not None else -1,
                id=r.id,
            )
            for r in rows
        ]

    def get_version(self) -> str:
        with self.engine.connect() as conn:
            return str(conn.execute(text("SELECT 1")).scalar())  # placeholder; engine-specific version inspection out of scope

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
            return int(conn.execute(table_map[table_name].count()).scalar() or 0)
```

Then update `HarnessDatabase.__init__` to use the new backend. Replace:

```python
            elif HAS_SQLALCHEMY:
                # _SQLAlchemyHarnessBackend added in Task 3.
                raise NotImplementedError(
                    "SQLAlchemy backend lands in Task 3 of the foundation plan"
                )
```

with:

```python
            elif HAS_SQLALCHEMY:
                self._backend = _SQLAlchemyHarnessBackend(database_url)
```

- [ ] **Step 4: Adjust `test_get_version_returns_sqlite_version` for SQLAlchemy**

The existing `TestIntrospection.test_get_version_returns_sqlite_version` asserts a dotted version string, but the SQLAlchemy backend's `get_version` returns `'1'`. Update the test:

```python
    def test_get_version_returns_something(self, harness_db):
        v = harness_db.get_version()
        assert v  # any non-empty string; backends return different shapes
```

- [ ] **Step 5: Run the parametrised tests, verify both backends pass**

Run: `uv run pytest tests/test_harness_db.py -v 2>&1 | tail -60`
Expected: 23 file_path tests pass + 22 sqlite_url tests pass (cascade is skipped for SQLAlchemy parametrisation) = 45 results, 1 skip.

- [ ] **Step 6: Run the verification suite**

```bash
uv run pytest && \
pre-commit run --all-files && \
make code-quality-check && \
make robot-dryrun && \
make robot-agentic-coding
```
Expected: pytest green (now ≈2761 passing), pre-commit green, code-quality green, robot-dryrun shows only the known 12 Browser baseline failures, robot-agentic-coding green.

- [ ] **Step 7: Commit**

```bash
git add src/rfc/harness_db.py tests/test_harness_db.py
git commit -m "$(cat <<'EOF'
feat: add HarnessDatabase SQLAlchemy backend

Mirrors the SQLite backend's behaviour against any database URL the
existing TestDatabase facade understands (postgresql:// in production,
sqlite:/// in tests). Snapshot save_plugins / save_skills emulate
INSERT OR REPLACE via a delete-then-insert pair keyed on the UNIQUE
pair, since SQLAlchemy doesn't expose REPLACE portably.

Tests are parametrised across both backends through the existing
harness_db fixture, exercising all CRUD methods on both code paths.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `test_runs.session_id` migration + view body update

**Files:**
- Modify: `src/rfc/test_database.py`
- Create: `tests/test_test_database_migration.py`

- [ ] **Step 1: Write failing migration tests**

Create `tests/test_test_database_migration.py`:

```python
"""Tests for the test_runs.session_id migration added in Issue #350."""

import sqlite3
from datetime import datetime

import pytest

from rfc.test_database import TestDatabase, TestRun


class TestSessionIdColumn:
    def test_fresh_db_has_session_id_column(self, tmp_path):
        db_file = tmp_path / "test.db"
        TestDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(test_runs)")}
        assert "session_id" in cols

    def test_session_id_added_to_existing_pre_migration_db(self, tmp_path):
        db_file = tmp_path / "test.db"
        # Build a pre-migration test_runs schema (no session_id) by hand,
        # mirroring the production SCHEMA minus the new column.
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute(
                """
                CREATE TABLE test_runs (
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
                    rfc_version TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO test_runs (timestamp, model_name, test_suite) VALUES (?, ?, ?)",
                ("2026-01-01T00:00:00", "llama3", "math"),
            )
        # Re-init via TestDatabase — should ALTER and preserve the row.
        TestDatabase(db_path=str(db_file))
        with sqlite3.connect(str(db_file)) as conn:
            rows = conn.execute(
                "SELECT id, model_name, session_id FROM test_runs"
            ).fetchall()
        assert rows == [(1, "llama3", None)]

    def test_migration_is_idempotent(self, tmp_path):
        db_file = tmp_path / "test.db"
        TestDatabase(db_path=str(db_file))
        TestDatabase(db_path=str(db_file))  # second init must not raise

    def test_view_exposes_session_id(self, tmp_path):
        db_file = tmp_path / "test.db"
        db = TestDatabase(db_path=str(db_file))
        # Insert a TestRun with session_id and a TestResult row.
        from rfc.test_database import TestResult
        run = TestRun(
            timestamp=datetime(2026, 5, 9, 0, 0, 0),
            model_name="llama3",
            test_suite="math",
            total_tests=1,
            passed=1,
            failed=0,
            skipped=0,
            duration_seconds=1.0,
            session_id="my-session-abc",
        )
        run_id = db.add_test_run(run)
        db.add_test_results([
            TestResult(run_id=run_id, test_name="t1", test_status="PASS")
        ])
        with sqlite3.connect(str(db_file)) as conn:
            row = conn.execute(
                "SELECT session_id FROM test_results_full WHERE test_name = 't1'"
            ).fetchone()
        assert row[0] == "my-session-abc"


class TestTestRunDataclass:
    def test_session_id_default_is_empty_string(self):
        run = TestRun(
            timestamp=datetime(2026, 5, 9, 0, 0, 0),
            model_name="llama3",
            test_suite="math",
            total_tests=0,
            passed=0,
            failed=0,
            skipped=0,
            duration_seconds=0.0,
        )
        assert run.session_id == ""
```

- [ ] **Step 2: Run the new tests, verify they fail**

Run: `uv run pytest tests/test_test_database_migration.py -v 2>&1 | tail -30`
Expected: failures because:
- `TestRun` has no `session_id` field (`AttributeError` / `TypeError` in TestTestRunDataclass).
- `test_runs` has no `session_id` column on fresh init (`TestSessionIdColumn.test_fresh_db_has_session_id_column` fails the assertion).
- The migration test fails because there's no ALTER yet.
- The view test fails because the view doesn't expose the column.

- [ ] **Step 3: Update `TestRun` dataclass with `session_id`**

Edit `src/rfc/test_database.py`. Find the `TestRun` dataclass (around lines 57–73) and add `session_id: str = ""` immediately before the `id: int = -1` line:

`old_string`:
```python
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
    id: int = -1
```

`new_string`:
```python
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
    id: int = -1
```

- [ ] **Step 4: Add `session_id` to `_SQLiteBackend.SCHEMA`**

Find the `test_runs` CREATE TABLE in `_SQLiteBackend.SCHEMA` (around line 271–286). Add `session_id TEXT,` immediately after the `rfc_version TEXT` line:

`old_string`:
```python
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
        rfc_version TEXT
    );
```

`new_string`:
```python
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
        session_id TEXT
    );
```

- [ ] **Step 5: Append the SQLite ALTER migration**

Find `_SQLITE_MIGRATIONS` (around line 344). Append the new migration to the end of the list:

`old_string`:
```python
        "ALTER TABLE test_results DROP COLUMN token_retry_max_tokens",
    ]
```

`new_string`:
```python
        "ALTER TABLE test_results DROP COLUMN token_retry_max_tokens",
        # Issue #350: link test_runs to the active agentic harness session.
        "ALTER TABLE test_runs ADD COLUMN session_id TEXT",
    ]
```

- [ ] **Step 6: Append the Postgres ALTER migration**

Find `_PG_MIGRATIONS` (around line 617). Find the closing `]` and add the new ALTER right before it. The cleanest place is just before the view re-creation (the last entry):

`old_string`:
```python
        # Migrate score column from INTEGER to REAL (float).
        "ALTER TABLE test_results ALTER COLUMN score TYPE REAL USING score::real",
        # Joined view for Superset — lean columns + archive LEFT JOIN.
        f"CREATE VIEW test_results_full AS {TEST_RESULTS_FULL_VIEW_BODY}",
    ]
```

`new_string`:
```python
        # Migrate score column from INTEGER to REAL (float).
        "ALTER TABLE test_results ALTER COLUMN score TYPE REAL USING score::real",
        # Issue #350: link test_runs to the active agentic harness session.
        "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS session_id TEXT",
        # Joined view for Superset — lean columns + archive LEFT JOIN.
        f"CREATE VIEW test_results_full AS {TEST_RESULTS_FULL_VIEW_BODY}",
    ]
```

- [ ] **Step 7: Add `session_id` to `TEST_RESULTS_FULL_VIEW_BODY`**

Find the view body (around line 180–214). Add `r.session_id,` immediately after the `r.rfc_version,` line:

`old_string`:
```python
    r.git_branch,
    r.hostname,
    r.rfc_version,
    ra.output_xml_source,
```

`new_string`:
```python
    r.git_branch,
    r.hostname,
    r.rfc_version,
    r.session_id,
    ra.output_xml_source,
```

- [ ] **Step 8: Add `session_id` Column to the SQLAlchemy `test_runs` Table**

Find `_SQLAlchemyBackend._define_tables` (around line 717). Locate the `test_runs` Table definition and add a `Column("session_id", String, nullable=True)` line in the appropriate position (after `rfc_version`).

First read the exact existing block to find the insertion point:

```bash
grep -n "rfc_version\|self._test_runs = Table" src/rfc/test_database.py | head -10
```

Then add the column with Edit. The pattern will be similar to:

`old_string`:
```python
            Column("hostname", String),
            Column("rfc_version", String),
        )
```

`new_string`:
```python
            Column("hostname", String),
            Column("rfc_version", String),
            Column("session_id", String, nullable=True),
        )
```

(If the actual layout differs, adjust the surrounding lines to make the `old_string` unique; the principle is "add `session_id` after `rfc_version` in the `test_runs` Table definition.")

- [ ] **Step 9: Update `_SQLiteBackend.add_test_run` to write `session_id`**

The existing `add_test_run` SQL (around line 388) inserts `(timestamp, model_name, test_suite, total_tests, passed, failed, skipped, duration_seconds, git_commit, git_branch, hostname, rfc_version)`. Update it to include `session_id`:

First, read lines 387–415 of `src/rfc/test_database.py` to confirm the exact INSERT statement, then Edit to add `session_id` to both the column list and the values tuple. The pattern:

```python
            cursor = conn.execute(
                """
                INSERT INTO test_runs
                (timestamp, model_name, test_suite, total_tests, passed,
                 failed, skipped, duration_seconds, git_commit, git_branch,
                 hostname, rfc_version, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
```

- [ ] **Step 10: Update `_SQLAlchemyBackend.add_test_run` similarly**

In the SQLAlchemy backend, find `add_test_run` (search for `def add_test_run` in the `_SQLAlchemyBackend` class). The implementation uses `self._test_runs.insert()` with a value dict. Add `"session_id": run.session_id or None` to the dict.

To find the exact location:
```bash
grep -nE "def add_test_run" src/rfc/test_database.py
```

Then Edit to add the field. The pattern:

`new addition to the values dict`: `"session_id": run.session_id or None,`

- [ ] **Step 11: Run the migration tests, verify pass**

Run: `uv run pytest tests/test_test_database_migration.py -v 2>&1 | tail -25`
Expected: 5 tests pass.

- [ ] **Step 12: Run the existing `test_test_database.py` to confirm no regression**

Run: `uv run pytest tests/test_test_database.py -v 2>&1 | tail -30`
Expected: all existing tests still pass. (The `session_id` field has a `""` default, so no test that constructs a `TestRun` without it should break.)

- [ ] **Step 13: Run the verification suite**

```bash
uv run pytest && \
pre-commit run --all-files && \
make code-quality-check && \
make robot-dryrun && \
make robot-agentic-coding
```
Expected: pytest green (now ≈2766 passing), pre-commit green, code-quality green, robot-dryrun shows only the known 12 Browser baseline failures, robot-agentic-coding green.

- [ ] **Step 14: Commit**

```bash
git add src/rfc/test_database.py tests/test_test_database_migration.py
git commit -m "$(cat <<'EOF'
feat: add session_id to test_runs and test_results_full view

Closes the schema work for Issue #350 by joining the existing
test_results_full view to the new agentic harness session id. New
columns:
- test_runs.session_id (TEXT, nullable) on both backends.
- TestRun.session_id dataclass field (default "").
- test_results_full view exposes session_id.

The SQLite SCHEMA now declares session_id at CREATE time so fresh DBs
get the column without an ALTER; the appended _SQLITE_MIGRATIONS entry
is the upgrade path for pre-existing databases. Postgres uses ADD
COLUMN IF NOT EXISTS for native idempotency.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Version bump

**Files:**
- Modify: `pyproject.toml` (line with `version = "..."`)
- Modify: `src/rfc/__init__.py` (line with `__version__ = "..."`)

- [ ] **Step 1: Inspect current version**

Run: `make version` or `grep -E "version" pyproject.toml | head -3`
Note the current version (e.g., `1.10.3`).

- [ ] **Step 2: Bump patch version in `pyproject.toml`**

Use Edit to change `version = "1.10.3"` (or whatever the current value is) to the next patch (`1.10.4`). The `old_string` should be the exact line including its quotes; if there are multiple `version = ...` lines, scope by the surrounding `[project]` block.

- [ ] **Step 3: Bump `__version__` in `src/rfc/__init__.py`**

Same change to `__version__ = "1.10.3"` → `"1.10.4"`.

- [ ] **Step 4: Run the verification suite**

```bash
uv run pytest && \
pre-commit run --all-files && \
make code-quality-check && \
make robot-dryrun && \
make robot-agentic-coding
```
Expected: all green (against the established baseline).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/rfc/__init__.py
git commit -m "$(cat <<'EOF'
chore: bump version to 1.10.4

Patch bump for Issue #350 (Agentic Stack Tracker foundation): adds
new internal modules (harness_db.py, harness_models.py) and a
nullable session_id column on test_runs. No public-API change to
existing keywords or graders.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

(Substitute the actual next version number for `1.10.4`.)

---

## Final verification

- [ ] **Run the full PR-readiness suite**

```bash
git fetch origin claude-code-staging && \
git rebase origin/claude-code-staging && \
git diff origin/claude-code-staging...HEAD --stat && \
uv run pytest 2>&1 | tee /tmp/pr-pytest.txt && \
pre-commit run --all-files 2>&1 | tee /tmp/pr-precommit.txt && \
make code-quality-check 2>&1 | tee /tmp/pr-quality.txt && \
make robot-dryrun 2>&1 | tee /tmp/pr-dryrun.txt && \
make robot-agentic-coding 2>&1 | tee /tmp/pr-agentic-coding.txt
```

Expected:
- Rebase clean (no conflicts).
- `git diff --stat` shows: `Makefile`, `src/rfc/harness_db.py` (new), `src/rfc/harness_models.py` (new), `src/rfc/test_database.py` (modified), `src/rfc/__init__.py` (version), `pyproject.toml` (version), `tests/test_harness_db.py` (new), `tests/test_harness_models.py` (new), `tests/test_test_database_migration.py` (new), `humans/TODO.md` (Browser baseline note from session startup), and the two docs files in `docs/superpowers/`.
- All check outputs end with success markers (pytest "passed", pre-commit "Passed" lines, robot-dryrun has *only* the known 12 Browser baseline failures).

- [ ] **Open the PR**

Follow the workflow in CLAUDE.md § PR workflow (use `gh pr create` with the project's `.github/PULL_REQUEST_TEMPLATE.md`). The "How to review" section should direct the reviewer to:

1. Start at `src/rfc/harness_models.py` (5-minute scan — pure dataclasses).
2. Then `src/rfc/harness_db.py` SQLite backend SCHEMA + CRUD methods (the meat).
3. Then `src/rfc/harness_db.py` `_SQLAlchemyHarnessBackend` (mostly mechanical mirror of SQLite).
4. Finally the `src/rfc/test_database.py` diff (the migration to existing schema).
5. Tests should be skimmable; they exist to lock the contracts.

Mechanical/ignorable: the docs commit and the Browser-baseline TODO note (already on `claude-code-staging` via merged predecessor commits — they will not appear in this PR's diff if they were committed pre-rebase; if they do, call them out as "session startup hygiene, not part of the feature").

---

## Self-Review

**Spec coverage check (against `docs/superpowers/specs/2026-05-09-agentic-stack-tracker-foundation-design.md`):**

| Spec section | Implemented in |
|---|---|
| 1.1 New tables (4 × `agentic_*`) | Task 2A step 3 (SCHEMA constant) |
| 1.2 `test_runs.session_id` migration | Task 4 steps 4–6 |
| 1.3 `TEST_RESULTS_FULL_VIEW_BODY` update | Task 4 step 7 |
| 2.1 `harness_models.py` dataclasses | Task 1 step 3 |
| 2.1 `harness_db.py` module + backends | Tasks 2A–2F (SQLite) + Task 3 (SQLAlchemy) |
| 2.2 `test_database.py` six additions | Task 4 steps 3, 4, 5, 6, 7, 8/10 |
| 2.3 `Makefile` `robot-agentic-coding` target | Task 0 |
| 3 Public API surface | All CRUD methods covered in Task 2A–2D + Task 3 |
| 4 Migration strategy (idempotent + view rebuild) | Task 2A step 3 (`CREATE … IF NOT EXISTS`), Task 4 (ALTER guard via `try/except OperationalError` and `IF NOT EXISTS`), view rebuilt by existing test_database.py logic |
| 5.1 `test_harness_models.py` | Task 1 step 1 |
| 5.2 `test_harness_db.py` parametrised | Task 2A step 1 + Task 3 step 1 |
| 5.3 `test_test_database_migration.py` | Task 4 step 1 |
| 5.4 Per-commit verification | Each task ends with the suite |
| 6 Build sequence (5 commits) | Tasks 0–4 (one commit each) |

No gaps.

**Placeholder scan:** Reviewed — no `TBD`, `TODO`, "implement later", or vague "appropriate" / "as needed" prose in implementation steps. All code blocks are complete and runnable.

**Type consistency check:**

- `_SQLiteHarnessBackend` and `_SQLAlchemyHarnessBackend` both implement every abstractmethod on `_HarnessBackend`. Method signatures match (verified by walking each abstractmethod and grep'ing both implementations).
- `AgenticMetric.test_run_id` is `int = -1` everywhere; the SQL persistence path converts `-1 → NULL` and read path converts `NULL → -1`. Symmetric in both backends.
- Dataclass field names match between `harness_models.py` definitions and the column lists in INSERTs/SELECTs across both backends.
- `HarnessDatabase.__init__` signature (`*, db_path=None, database_url=None`) matches the existing `TestDatabase.__init__` convention; this is an explicit spec correction noted at the top of the plan.

**No issues found.**
