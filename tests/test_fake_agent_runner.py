"""Tests for rfc.fake_agent_runner (prerecorded AgentRun replay)."""

from pathlib import Path

import pytest
import yaml

from rfc.fake_agent_runner import FakeAgentRunner, run_scenario


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
