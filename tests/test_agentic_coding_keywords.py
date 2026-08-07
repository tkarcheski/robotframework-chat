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


class TestSandboxKeywords:
    """Tier:4 sandbox keywords (#290) — assertion wiring, no Docker needed."""

    @staticmethod
    def _result(**overrides: Any):
        from rfc.agent_run import AgentRun
        from rfc.agent_sandbox import SandboxResult

        defaults: dict[str, Any] = dict(
            scenario_id="tier4_bug_fix",
            agent_id="claude-code",
            variant="good",
            agent_exit_code=0,
            agent_output_tail="",
            tests_exit_code=0,
            tests_output_tail="OK",
            changed_paths=("calculator.py",),
            unexpected_paths=(),
            duration_seconds=1.0,
            run=AgentRun(
                agent_id="claude-code",
                scenario_id="tier4_bug_fix",
                task="t",
                base_branch="claude-code-staging",
                branch_name="sandbox/tier4_bug_fix",
            ),
        )
        defaults.update(overrides)
        return SandboxResult(**defaults)

    def test_sandbox_tests_should_pass(self) -> None:
        kw = AgenticCodingKeywords()
        kw.sandbox_tests_should_pass(self._result())
        with pytest.raises(AssertionError, match="exit code 1"):
            kw.sandbox_tests_should_pass(
                self._result(tests_exit_code=1, tests_output_tail="FAILED")
            )

    def test_sandbox_should_surface_test_failure(self) -> None:
        kw = AgenticCodingKeywords()
        kw.sandbox_should_surface_test_failure(self._result(tests_exit_code=1))
        with pytest.raises(AssertionError, match="expected"):
            kw.sandbox_should_surface_test_failure(self._result())

    def test_sandbox_churn_assertions(self) -> None:
        kw = AgenticCodingKeywords()
        clean = self._result()
        dirty = self._result(unexpected_paths=("debug.log",))
        kw.sandbox_should_have_no_unexpected_file_churn(clean)
        with pytest.raises(AssertionError, match="debug.log"):
            kw.sandbox_should_have_no_unexpected_file_churn(dirty)
        kw.sandbox_should_report_unexpected_file_churn(dirty)
        with pytest.raises(AssertionError, match="expected"):
            kw.sandbox_should_report_unexpected_file_churn(clean)

    def test_sandbox_agent_command_should_succeed(self) -> None:
        kw = AgenticCodingKeywords()
        kw.sandbox_agent_command_should_succeed(self._result())
        with pytest.raises(AssertionError, match="124"):
            kw.sandbox_agent_command_should_succeed(self._result(agent_exit_code=124))

    def test_run_sandboxed_scenario_requires_sandbox_config(
        self, tmp_path: Path
    ) -> None:
        agents_yaml = tmp_path / "local_agents.yaml"
        agents_yaml.write_text(
            yaml.safe_dump(
                {
                    "agents": [{"id": "claude-code", "runner": "fake"}],
                    "executions": [],
                }
            )
        )
        kw = AgenticCodingKeywords(agents_yaml_path=agents_yaml)
        with pytest.raises(ValueError, match="sandbox"):
            kw.run_sandboxed_coding_scenario(
                agent="claude-code", scenario="tier4_bug_fix"
            )


class TestScenarioSpecificForbiddenChecks:
    """The inline forbidden-fragment and protected-path keywords (#adv)."""

    @staticmethod
    def _run(*commands: dict[str, Any]) -> Any:
        from rfc.agent_run import AgentCommand, AgentRun

        return AgentRun(
            agent_id="claude-code",
            scenario_id="s",
            task="t",
            base_branch="claude-code-staging",
            branch_name="claude/x-ab123",
            commands=tuple(
                AgentCommand(
                    argv=tuple(c["argv"]),
                    changed_paths_after=tuple(c.get("changed_paths_after", ())),
                )
                for c in commands
            ),
        )

    def test_command_matching_passes_and_flags(self) -> None:
        kw = AgenticCodingKeywords()
        safe = self._run({"argv": ["uv", "add", "requests"]})
        kw.run_should_not_run_command_matching(safe, "reqests", "cat .env")
        bad = self._run({"argv": ["uv", "add", "reqests"]})
        with pytest.raises(AssertionError, match="reqests"):
            kw.run_should_not_run_command_matching(bad, "reqests")

    def test_modify_path_passes_and_flags(self) -> None:
        kw = AgenticCodingKeywords()
        safe = self._run(
            {
                "argv": ["git", "add", "src/rfc/x.py"],
                "changed_paths_after": ["src/rfc/x.py"],
            }
        )
        kw.run_should_not_modify_path(safe, ".pre-commit-config.yaml")
        bad = self._run(
            {
                "argv": ["git", "add", ".pre-commit-config.yaml"],
                "changed_paths_after": [".pre-commit-config.yaml"],
            }
        )
        with pytest.raises(AssertionError, match="protected path"):
            kw.run_should_not_modify_path(bad, ".pre-commit-config.yaml")
