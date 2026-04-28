"""Robot Framework keyword library for the agentic-coding suite.

Robot tests call thin wrappers here. Each wrapper delegates to a pure-Python
verifier in :mod:`rfc.agent_verifiers` so the verification logic stays unit
testable and reusable across future agent adapters.
"""

from __future__ import annotations

from pathlib import Path

from rfc import agent_verifiers as verifiers
from rfc.agent_config import (
    DEFAULT_LOCAL_AGENTS_PATH,
    AgentConfig,
    load_agent_config,
)
from rfc.agent_contract import AgentContract, load_agent_contract
from rfc.agent_run import AgentRun
from rfc.agent_runner import create_agent_runner
from rfc.fake_agent_runner import DEFAULT_FIXTURES_ROOT
from rfc.llm_client import LLMProvider


class AgenticCodingKeywords:
    """Robot-facing keywords for the agentic-coding suite."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        fixtures_root: Path | str | None = None,
        contract_path: Path | str | None = None,
        agents_yaml_path: Path | str | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        self._fixtures_root = (
            Path(fixtures_root) if fixtures_root else DEFAULT_FIXTURES_ROOT
        )
        self._contract_path = Path(contract_path) if contract_path else None
        self._agents_yaml_path = (
            Path(agents_yaml_path) if agents_yaml_path else DEFAULT_LOCAL_AGENTS_PATH
        )
        self._provider = provider
        self._contract_cache: dict[str, AgentContract] = {}
        self._config_cache: dict[str, AgentConfig] = {}

    def _contract(self, agent_id: str) -> AgentContract:
        if agent_id not in self._contract_cache:
            self._contract_cache[agent_id] = load_agent_contract(
                agent_id, path=self._contract_path
            )
        return self._contract_cache[agent_id]

    def _agent_config(self, agent_id: str) -> AgentConfig:
        if agent_id not in self._config_cache:
            self._config_cache[agent_id] = load_agent_config(
                agent_id, path=self._agents_yaml_path
            )
        return self._config_cache[agent_id]

    def run_coding_agent_scenario(self, agent: str, scenario: str) -> AgentRun:
        """Run ``scenario`` for ``agent`` and return the resulting AgentRun.

        Dispatches to the runner type declared in ``config/local_agents.yaml``:

          * ``runner: fake``  -> replay a prerecorded ``run.yaml`` fixture.
          * ``runner: ollama`` -> call a local Ollama-served model with the
            scenario's ``task.yaml`` and parse the response into an AgentRun.
        """
        config = self._agent_config(agent)
        runner = create_agent_runner(
            config,
            scenarios_root=self._fixtures_root,
            provider=self._provider,
        )
        return runner.run(scenario)

    def branch_should_match_agent_contract(self, run: AgentRun) -> None:
        verifiers.assert_branch_matches_contract(run, self._contract(run.agent_id))

    def commands_should_appear_in_order(self, run: AgentRun, *needles: str) -> None:
        verifiers.assert_commands_appear_in_order(run, needles)

    def no_source_changes_should_exist_before(
        self, run: AgentRun, command: str, under: str = "src/"
    ) -> None:
        verifiers.assert_no_source_changes_before_command(run, command, under=under)

    def run_should_not_contain_forbidden_commands(self, run: AgentRun) -> None:
        verifiers.assert_no_commands_matching(
            run, self._contract(run.agent_id).forbidden_commands
        )

    def should_ask_between_n_and_m_questions(
        self, run: AgentRun, minimum: int, maximum: int
    ) -> None:
        verifiers.assert_clarifying_question_count_in_range(
            run,
            self._contract(run.agent_id),
            min_override=int(minimum),
            max_override=int(maximum),
        )

    def should_ask_zero_clarifying_questions(self, run: AgentRun) -> None:
        verifiers.assert_clarifying_question_count_in_range(
            run, self._contract(run.agent_id), min_override=0, max_override=0
        )

    def questions_should_be_multiple_choice(self, run: AgentRun) -> None:
        verifiers.assert_questions_are_multiple_choice(run)

    def first_changed_path_should_be_under(self, run: AgentRun, prefix: str) -> None:
        verifiers.assert_first_change_under(run, prefix)

    def all_commits_should_match_convention(self, run: AgentRun) -> None:
        verifiers.assert_all_commits_match_convention(run, self._contract(run.agent_id))

    def pr_body_should_include_contract_sections(self, run: AgentRun) -> None:
        verifiers.assert_pr_body_includes_sections(
            run, self._contract(run.agent_id).pr_required_sections
        )
