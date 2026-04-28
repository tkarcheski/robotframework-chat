"""Tests for rfc.agentic_coding_keywords (Robot-facing wrapper)."""

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from rfc.agentic_coding_keywords import AgenticCodingKeywords


@dataclass
class _StubProvider:
    canned: str = ""
    prompts: list[str] = field(default_factory=list)
    model: str = "stub"
    temperature: float = 0.0
    max_tokens: int = 256
    seed: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    num_ctx: int | None = None
    keep_alive: str | None = None
    last_metrics: dict[str, Any] | None = None

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.canned


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
                    {
                        "argv": [
                            "git",
                            "checkout",
                            "-b",
                            "claude/do-x-ab123",
                            "origin/claude-code-staging",
                        ],
                    },
                    {"argv": ["uv", "run", "pytest"]},
                    {"argv": ["pre-commit", "run", "--all-files"]},
                    {"argv": ["make", "code-quality-check"]},
                    {"argv": ["make", "robot-dryrun"]},
                ],
                "questions": [],
                "commits": [],
            }
        )
    )
    (root / "bad_branch").mkdir()
    (root / "bad_branch" / "run.yaml").write_text(
        yaml.safe_dump(
            {
                "agent_id": "claude-code",
                "scenario_id": "bad_branch",
                "task": "x",
                "base_branch": "main",
                "branch_name": "feature/wrong",
                "commands": [],
                "questions": [],
                "commits": [],
            }
        )
    )
    return root


class TestRunCodingAgentScenario:
    def test_returns_agent_run(self, fixtures_root: Path) -> None:
        kw = AgenticCodingKeywords(fixtures_root=fixtures_root)
        run = kw.run_coding_agent_scenario(
            agent="claude-code", scenario="startup_contract"
        )
        assert run.scenario_id == "startup_contract"

    def test_unknown_scenario_raises(self, fixtures_root: Path) -> None:
        kw = AgenticCodingKeywords(fixtures_root=fixtures_root)
        with pytest.raises(KeyError):
            kw.run_coding_agent_scenario(agent="claude-code", scenario="nope")


class TestBranchAndBaseChecks:
    def test_branch_should_match_contract_passes(self, fixtures_root: Path) -> None:
        kw = AgenticCodingKeywords(fixtures_root=fixtures_root)
        run = kw.run_coding_agent_scenario(
            agent="claude-code", scenario="startup_contract"
        )
        kw.branch_should_match_agent_contract(run)

    def test_bad_branch_fails_assertion(self, fixtures_root: Path) -> None:
        kw = AgenticCodingKeywords(fixtures_root=fixtures_root)
        run = kw.run_coding_agent_scenario(agent="claude-code", scenario="bad_branch")
        with pytest.raises(AssertionError):
            kw.branch_should_match_agent_contract(run)


class TestCommandsShouldAppearInOrder:
    def test_full_startup_sequence_passes(self, fixtures_root: Path) -> None:
        kw = AgenticCodingKeywords(fixtures_root=fixtures_root)
        run = kw.run_coding_agent_scenario(
            agent="claude-code", scenario="startup_contract"
        )
        kw.commands_should_appear_in_order(
            run,
            "git fetch origin claude-code-staging",
            "uv run pytest",
            "pre-commit run --all-files",
            "make code-quality-check",
            "make robot-dryrun",
        )

    def test_missing_command_raises(self, fixtures_root: Path) -> None:
        kw = AgenticCodingKeywords(fixtures_root=fixtures_root)
        run = kw.run_coding_agent_scenario(
            agent="claude-code", scenario="startup_contract"
        )
        with pytest.raises(AssertionError):
            kw.commands_should_appear_in_order(run, "rm -rf /")


class TestNoSourceChangesBefore:
    def test_no_source_changes_before_pytest(self, fixtures_root: Path) -> None:
        kw = AgenticCodingKeywords(fixtures_root=fixtures_root)
        run = kw.run_coding_agent_scenario(
            agent="claude-code", scenario="startup_contract"
        )
        kw.no_source_changes_should_exist_before(
            run, command="uv run pytest", under="src/"
        )


class TestNoForbiddenCommands:
    def test_clean_run_passes(self, fixtures_root: Path) -> None:
        kw = AgenticCodingKeywords(fixtures_root=fixtures_root)
        run = kw.run_coding_agent_scenario(
            agent="claude-code", scenario="startup_contract"
        )
        kw.run_should_not_contain_forbidden_commands(run)


class TestQuestionBehavior:
    def test_zero_questions_on_startup_ok(self, fixtures_root: Path) -> None:
        kw = AgenticCodingKeywords(fixtures_root=fixtures_root)
        run = kw.run_coding_agent_scenario(
            agent="claude-code", scenario="startup_contract"
        )
        kw.should_ask_zero_clarifying_questions(run)


class TestOllamaRunnerDispatch:
    """The keyword routes ``runner: ollama`` agents through OllamaAgentRunner."""

    def test_runs_through_local_model(self, tmp_path: Path) -> None:
        agents_yaml = tmp_path / "local_agents.yaml"
        agents_yaml.write_text(
            yaml.safe_dump(
                {
                    "agents": [
                        {
                            "id": "ollama-local",
                            "runner": "ollama",
                            "model": "phi4:14b",
                            "endpoint": "http://localhost:11434",
                        }
                    ],
                    "executions": [],
                }
            )
        )
        scenarios_root = tmp_path / "fixtures"
        scenarios_root.mkdir()
        scenario = scenarios_root / "smoke"
        scenario.mkdir()
        (scenario / "task.yaml").write_text(
            yaml.safe_dump(
                {
                    "scenario_id": "smoke",
                    "task": "Say hi.",
                    "base_branch": "claude-code-staging",
                }
            )
        )
        canned = textwrap.dedent(
            """\
            ```yaml
            agent_id: ollama-local
            scenario_id: smoke
            task: Say hi.
            base_branch: claude-code-staging
            branch_name: claude/say-hi-12345
            commands: []
            questions: []
            commits: []
            ```
            """
        )
        provider = _StubProvider(canned=canned)
        kw = AgenticCodingKeywords(
            fixtures_root=scenarios_root,
            agents_yaml_path=agents_yaml,
            provider=provider,
        )
        run = kw.run_coding_agent_scenario(agent="ollama-local", scenario="smoke")
        assert run.agent_id == "ollama-local"
        assert run.scenario_id == "smoke"
        assert run.branch_name == "claude/say-hi-12345"
        assert provider.prompts, "the local model should have been called"
