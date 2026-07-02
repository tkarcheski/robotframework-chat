"""Tests for rfc.generative_listener (#358) — read-only observe mode.

Phase 3 of the Agentic Stack Tracker: when a suite is tagged
``generative:observe`` the listener prompts a configured LLM at hook
events (``start_suite``, ``end_test`` on failure) and writes the
exchange into the ``agentic_decisions`` table with ``applied=0``.
Execution behaviour of the suite is never changed.

Covers:
- ``agentic_decisions`` CRUD on ``HarnessDatabase``
- tagged suite produces decision rows; untagged suite produces none
- token budget cap enforced (synthetic LLM consuming budget rapidly):
  exactly one ``budget_exhausted`` row, then silence
- ``applied=0`` always in this phase
- listener registration in every runner actually in use (lesson from #409)
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

from rfc.generative_listener import (
    GENERATIVE_OBSERVE_TAG,
    GenerativeListener,
)
from rfc.harness_db import HarnessDatabase
from rfc.harness_models import AgenticDecision, AgenticHarness

T0 = "2026-06-12T00:00:00Z"
SESSION = "sess-gen-1"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SyntheticProvider:
    """Stand-in LLM provider satisfying the ``LLMProvider`` protocol shape.

    ``tokens_per_call`` controls how fast the listener's budget drains,
    so the budget-cap tests can exhaust it deterministically.
    """

    def __init__(
        self, tokens_per_call: int = 50, response: str = "observation: nominal"
    ) -> None:
        self.model = "synthetic-test-model"
        self.last_metrics: Optional[Dict[str, Any]] = None
        self.tokens_per_call = tokens_per_call
        self.response = response
        self.calls = 0
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        half = self.tokens_per_call // 2
        self.last_metrics = {
            "prompt_eval_count": half,
            "eval_count": self.tokens_per_call - half,
        }
        return self.response


def _db_url(root: Path) -> str:
    return f"sqlite:///{root / 'h.db'}"


def _seed_harness(root: Path, session_id: str = SESSION) -> HarnessDatabase:
    db = HarnessDatabase(database_url=_db_url(root))
    db.save_harness(
        AgenticHarness(session_id=session_id, tool_name="claude-code", started_at=T0)
    )
    return db


def _suite(tags: list[str], name: str = "Observed Suite") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        tests=[SimpleNamespace(name="t1", tags=list(tags))],
        suites=[],
    )


def _run_suite(
    listener: GenerativeListener,
    *,
    tags: list[str],
    test_results: list[bool],
) -> None:
    """Drive the listener through one suite with the given test outcomes."""
    suite = _suite(tags)
    listener.start_suite(suite, SimpleNamespace())
    for i, passed in enumerate(test_results):
        test = SimpleNamespace(name=f"t{i + 1}", tags=list(tags))
        listener.start_test(test, SimpleNamespace())
        result = SimpleNamespace(
            passed=passed,
            status="PASS" if passed else "FAIL",
            message="" if passed else "boom",
        )
        listener.end_test(test, result)
    listener.end_suite(suite, SimpleNamespace())


@pytest.fixture()
def clean_env(tmp_path, monkeypatch):
    """Isolated cwd with no session / DB / budget env leakage."""
    cwd = tmp_path / "plain"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    for var in (
        "SESSION_ID",
        "DATABASE_URL",
        "HARNESS_DATABASE_URL",
        "RFC_GENERATIVE_BUDGET_TOKENS",
        "RFC_GENERATIVE_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SESSION_ID", SESSION)
    return cwd


# ---------------------------------------------------------------------------
# agentic_decisions CRUD
# ---------------------------------------------------------------------------


class TestAgenticDecisionsCrud:
    def test_save_and_get_roundtrip(self, tmp_path):
        db = _seed_harness(tmp_path)
        decision = AgenticDecision(
            session_id=SESSION,
            hook_event="start_suite",
            prompt_model="synthetic-test-model",
            prompt_text="suite is starting",
            recorded_at=T0,
            test_name="t1",
            response_text="ok",
            proposed_action="observe",
            applied=0,
            tokens_used=42,
        )
        row_id = db.save_decision(decision)
        assert row_id
        rows = db.get_decisions(SESSION)
        assert len(rows) == 1
        got = rows[0]
        assert got.id == row_id
        assert got.session_id == SESSION
        assert got.hook_event == "start_suite"
        assert got.prompt_model == "synthetic-test-model"
        assert got.prompt_text == "suite is starting"
        assert got.response_text == "ok"
        assert got.proposed_action == "observe"
        assert got.applied == 0
        assert got.tokens_used == 42

    def test_filter_by_proposed_action(self, tmp_path):
        db = _seed_harness(tmp_path)
        for action in ("observe", "observe", "budget_exhausted"):
            db.save_decision(
                AgenticDecision(
                    session_id=SESSION,
                    hook_event="end_test",
                    prompt_model="m",
                    prompt_text="p",
                    recorded_at=T0,
                    proposed_action=action,
                )
            )
        assert len(db.get_decisions(SESSION)) == 3
        assert len(db.get_decisions(SESSION, proposed_action="observe")) == 2
        assert len(db.get_decisions(SESSION, proposed_action="budget_exhausted")) == 1

    def test_sentinels_map_to_null(self, tmp_path):
        db = _seed_harness(tmp_path)
        db.save_decision(
            AgenticDecision(
                session_id=SESSION,
                hook_event="start_suite",
                prompt_model="m",
                prompt_text="p",
                recorded_at=T0,
            )
        )
        got = db.get_decisions(SESSION)[0]
        assert got.test_name == ""
        assert got.response_text == ""
        assert got.tokens_used == -1

    def test_foreign_key_enforced(self, tmp_path):
        db = HarnessDatabase(database_url=_db_url(tmp_path))  # no harness row
        with pytest.raises(Exception):
            db.save_decision(
                AgenticDecision(
                    session_id="no-such-session",
                    hook_event="start_suite",
                    prompt_model="m",
                    prompt_text="p",
                    recorded_at=T0,
                )
            )

    def test_table_row_count_knows_decisions(self, tmp_path):
        db = _seed_harness(tmp_path)
        assert db.get_table_row_count("agentic_decisions") == 0

    def test_sqlite_native_backend_parity(self, tmp_path):
        db = HarnessDatabase(db_path=str(tmp_path / "native.db"))
        db.save_harness(
            AgenticHarness(session_id=SESSION, tool_name="cc", started_at=T0)
        )
        db.save_decision(
            AgenticDecision(
                session_id=SESSION,
                hook_event="end_test",
                prompt_model="m",
                prompt_text="p",
                recorded_at=T0,
                proposed_action="observe",
            )
        )
        assert len(db.get_decisions(SESSION)) == 1
        assert db.get_table_row_count("agentic_decisions") == 1


# ---------------------------------------------------------------------------
# Listener: observe mode
# ---------------------------------------------------------------------------


class TestGenerativeListenerObserve:
    def test_tagged_suite_produces_decision_rows(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider()
        listener = GenerativeListener(database_url=_db_url(tmp_path), provider=provider)
        _run_suite(listener, tags=[GENERATIVE_OBSERVE_TAG], test_results=[False])
        rows = db.get_decisions(SESSION)
        assert {r.hook_event for r in rows} == {"start_suite", "end_test"}
        assert all(r.proposed_action == "observe" for r in rows)
        assert all(r.prompt_model == "synthetic-test-model" for r in rows)
        assert provider.calls == 2

    def test_passing_test_only_prompts_at_suite_start(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider()
        listener = GenerativeListener(database_url=_db_url(tmp_path), provider=provider)
        _run_suite(listener, tags=[GENERATIVE_OBSERVE_TAG], test_results=[True, True])
        rows = db.get_decisions(SESSION)
        assert [r.hook_event for r in rows] == ["start_suite"]
        assert provider.calls == 1

    def test_untagged_suite_produces_no_rows(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider()
        listener = GenerativeListener(database_url=_db_url(tmp_path), provider=provider)
        _run_suite(listener, tags=["tier:0"], test_results=[False])
        assert db.get_decisions(SESSION) == []
        assert provider.calls == 0

    def test_applied_is_always_zero(self, clean_env, tmp_path, monkeypatch):
        monkeypatch.setenv("RFC_GENERATIVE_BUDGET_TOKENS", "120")
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(tokens_per_call=100)
        listener = GenerativeListener(database_url=_db_url(tmp_path), provider=provider)
        _run_suite(
            listener,
            tags=[GENERATIVE_OBSERVE_TAG],
            test_results=[False, False, False],
        )
        rows = db.get_decisions(SESSION)
        assert rows  # includes observe and budget_exhausted rows
        assert all(r.applied == 0 for r in rows)

    def test_budget_cap_writes_one_exhausted_row_then_silence(
        self, clean_env, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("RFC_GENERATIVE_BUDGET_TOKENS", "100")
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider(tokens_per_call=10_000)  # drains instantly
        listener = GenerativeListener(database_url=_db_url(tmp_path), provider=provider)
        _run_suite(
            listener,
            tags=[GENERATIVE_OBSERVE_TAG],
            test_results=[False, False, False, False],
        )
        rows = db.get_decisions(SESSION)
        observe = [r for r in rows if r.proposed_action == "observe"]
        exhausted = [r for r in rows if r.proposed_action == "budget_exhausted"]
        # First call lands (budget not yet known to be blown), the next hook
        # writes exactly one budget_exhausted marker, everything after is silent.
        assert len(observe) == 1
        assert len(exhausted) == 1
        assert provider.calls == 1
        assert len(rows) == 2

    def test_budget_default_when_env_unset(self, clean_env, tmp_path):
        listener = GenerativeListener(
            database_url=_db_url(tmp_path), provider=SyntheticProvider()
        )
        listener.start_suite(_suite([GENERATIVE_OBSERVE_TAG]), SimpleNamespace())
        assert listener.budget_tokens == 10_000

    def test_no_harness_row_skips_and_warns(self, clean_env, tmp_path, caplog):
        db = HarnessDatabase(database_url=_db_url(tmp_path))  # no seeded row
        provider = SyntheticProvider()
        listener = GenerativeListener(database_url=_db_url(tmp_path), provider=provider)
        with caplog.at_level("WARNING"):
            _run_suite(listener, tags=[GENERATIVE_OBSERVE_TAG], test_results=[False])
        assert db.get_decisions(SESSION) == []
        assert provider.calls == 0
        assert any("harness" in r.message.lower() for r in caplog.records)

    def test_provider_failure_never_breaks_the_run(self, clean_env, tmp_path, caplog):
        _seed_harness(tmp_path)

        class ExplodingProvider(SyntheticProvider):
            def generate(self, prompt: str) -> str:
                raise RuntimeError("llm down")

        listener = GenerativeListener(
            database_url=_db_url(tmp_path), provider=ExplodingProvider()
        )
        with caplog.at_level("WARNING"):
            _run_suite(listener, tags=[GENERATIVE_OBSERVE_TAG], test_results=[False])
        # No exception escaped; skip-and-log per CLAUDE.md.
        assert listener.persisted_count == 0

    def test_nested_suite_tag_detected(self, clean_env, tmp_path):
        db = _seed_harness(tmp_path)
        provider = SyntheticProvider()
        listener = GenerativeListener(database_url=_db_url(tmp_path), provider=provider)
        root = SimpleNamespace(
            name="Root",
            tests=[],
            suites=[_suite([GENERATIVE_OBSERVE_TAG], name="Child")],
        )
        listener.start_suite(root, SimpleNamespace())
        listener.end_suite(root, SimpleNamespace())
        assert len(db.get_decisions(SESSION)) == 1


# ---------------------------------------------------------------------------
# Registration (lesson from #409: ci.listeners alone is retired)
# ---------------------------------------------------------------------------


class TestListenerRegistration:
    REPO_ROOT = Path(__file__).resolve().parent.parent
    LISTENER = "rfc.generative_listener.GenerativeListener"

    def test_registered_in_test_suites_yaml(self):
        import yaml

        config = yaml.safe_load(
            (self.REPO_ROOT / "config" / "test_suites.yaml").read_text()
        )
        assert self.LISTENER in config["ci"]["listeners"]

    def test_registered_in_local_models_config(self):
        import yaml

        config = yaml.safe_load(
            (self.REPO_ROOT / "config" / "local_models.yaml").read_text()
        )
        assert self.LISTENER in config["execution"]["listeners"]

    def test_registered_in_makefile_listener_var(self):
        makefile = (self.REPO_ROOT / "Makefile").read_text()
        listener_line = next(
            line for line in makefile.splitlines() if line.startswith("LISTENER ")
        )
        assert self.LISTENER in listener_line

    def test_registered_in_tasks_listeners(self):
        import tasks

        assert self.LISTENER in tasks.LISTENERS
