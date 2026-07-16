"""Tests for rfc.fake_agent_runner (prerecorded AgentRun replay)."""

from pathlib import Path

import pytest
import yaml

from rfc.fake_agent_runner import (
    DEFAULT_FIXTURES_ROOT,
    FakeAgentRunner,
    run_scenario,
)


@pytest.fixture
def fixtures_root(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    root.mkdir()
    (root / "startup_contract").mkdir()
    (root / "startup_contract" / "run.yaml").write_text(
        yaml.safe_dump(
            {
                "agent_id": "claude-code",
                "scenario_id": "startup_contract",
                "task": "Do X.",
                "base_branch": "claude-code-staging",
                "branch_name": "claude/do-x-ab123",
                "commands": [
                    {"argv": ["git", "fetch", "origin", "claude-code-staging"]},
                    {"argv": ["uv", "run", "pytest"]},
                ],
                "questions": [],
                "commits": [],
            }
        )
    )
    (root / "another_scenario").mkdir()
    (root / "another_scenario" / "run.yaml").write_text(
        yaml.safe_dump(
            {
                "agent_id": "codex",
                "scenario_id": "another_scenario",
                "task": "x",
                "base_branch": "main",
                "branch_name": "codex/x-ab123",
                "commands": [],
                "questions": [],
                "commits": [],
            }
        )
    )
    return root


class TestFakeAgentRunner:
    def test_lists_available_scenarios(self, fixtures_root: Path) -> None:
        runner = FakeAgentRunner(fixtures_root=fixtures_root)
        assert set(runner.list_scenarios()) == {"startup_contract", "another_scenario"}

    def test_loads_scenario_by_id(self, fixtures_root: Path) -> None:
        runner = FakeAgentRunner(fixtures_root=fixtures_root)
        run = runner.run("startup_contract")
        assert run.scenario_id == "startup_contract"
        assert run.agent_id == "claude-code"
        assert len(run.commands) == 2

    def test_unknown_scenario_raises(self, fixtures_root: Path) -> None:
        runner = FakeAgentRunner(fixtures_root=fixtures_root)
        with pytest.raises(KeyError, match="unknown-scenario"):
            runner.run("unknown-scenario")

    def test_fixture_without_run_yaml_is_ignored(self, fixtures_root: Path) -> None:
        (fixtures_root / "not_a_scenario").mkdir()
        (fixtures_root / "not_a_scenario" / "readme.md").write_text("")
        runner = FakeAgentRunner(fixtures_root=fixtures_root)
        assert "not_a_scenario" not in runner.list_scenarios()

    def test_run_scenario_module_helper(self, fixtures_root: Path) -> None:
        run = run_scenario("startup_contract", fixtures_root=fixtures_root)
        assert run.scenario_id == "startup_contract"

    def test_agent_id_filter(self, fixtures_root: Path) -> None:
        runner = FakeAgentRunner(fixtures_root=fixtures_root, agent_id="claude-code")
        assert runner.list_scenarios() == ["startup_contract"]
        with pytest.raises(KeyError, match="not available for agent"):
            runner.run("another_scenario")


class TestDefaultFixturesRoot:
    """Regression guard for #384.

    The tier-renumbering migration (``robot/agentic_coding/...`` →
    ``robot/40__tier4/agentic_coding/...``) left ``DEFAULT_FIXTURES_ROOT``
    pointing at the deleted pre-migration path, so a default
    :class:`FakeAgentRunner` resolved every prerecorded scenario under a
    nonexistent directory and the agentic-coding suite failed with unknown
    scenarios. These assertions fail fast the next time the fixtures move
    without the constant being updated.

    Note: asserting the runner actually *lists scenarios* (not merely that the
    directory ``exists()``) is deliberate — a stale ``__pycache__``-only
    directory can linger at the old path and would satisfy a bare existence
    check while yielding zero scenarios, exactly the failure #384 describes.
    """

    def test_default_fixtures_root_is_a_directory(self) -> None:
        assert DEFAULT_FIXTURES_ROOT.is_dir(), (
            f"DEFAULT_FIXTURES_ROOT points at a nonexistent directory: "
            f"{DEFAULT_FIXTURES_ROOT}. Repoint it at the current tier-numbered "
            "fixtures location (see #384)."
        )

    def test_default_runner_lists_real_scenarios(self) -> None:
        scenarios = FakeAgentRunner().list_scenarios()
        assert scenarios, (
            "FakeAgentRunner() found no scenarios under DEFAULT_FIXTURES_ROOT "
            f"({DEFAULT_FIXTURES_ROOT}); the constant likely points at a stale "
            "or empty path (see #384)."
        )

    def test_default_runner_loads_a_scenario(self) -> None:
        runner = FakeAgentRunner()
        scenario_id = runner.list_scenarios()[0]
        run = runner.run(scenario_id)
        assert run.scenario_id == scenario_id
