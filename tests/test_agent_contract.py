"""Tests for rfc.agent_contract loader."""

from pathlib import Path

import pytest
import yaml

from rfc.agent_contract import AgentContract, load_agent_contract


class TestLoadAgentContract:
    def test_loads_claude_code_contract(self) -> None:
        contract = load_agent_contract("claude-code")
        assert contract.agent_id == "claude-code"
        assert contract.base_branch == "claude-code-staging"

    def test_branch_regex_matches_claude_format(self) -> None:
        contract = load_agent_contract("claude-code")
        assert contract.branch_matches("claude/setup-test-suite-config-l1nrg")
        assert contract.branch_matches("claude/fix-bug-ab123")

    def test_branch_regex_rejects_wrong_format(self) -> None:
        contract = load_agent_contract("claude-code")
        assert not contract.branch_matches("main")
        assert not contract.branch_matches("feature/foo")
        assert not contract.branch_matches("claude/no-random-suffix")

    def test_startup_checks_are_listed_in_order(self) -> None:
        contract = load_agent_contract("claude-code")
        assert contract.startup_checks == (
            "uv run pytest",
            "pre-commit run --all-files",
            "make code-quality-check",
            "make robot-dryrun",
        )

    def test_pr_required_sections_present(self) -> None:
        contract = load_agent_contract("claude-code")
        for section in ["Summary", "How to review", "Evidence of testing", "Checklist"]:
            assert section in contract.pr_required_sections

    def test_commit_subject_regex_matches_conventional(self) -> None:
        contract = load_agent_contract("claude-code")
        assert contract.commit_subject_matches("feat: add new keyword")
        assert contract.commit_subject_matches("test: red test for parser")
        assert contract.commit_subject_matches("chore: bump version")

    def test_commit_subject_regex_rejects_non_conventional(self) -> None:
        contract = load_agent_contract("claude-code")
        assert not contract.commit_subject_matches("WIP")
        assert not contract.commit_subject_matches("add feature")
        assert not contract.commit_subject_matches("random: unknown type")

    def test_clarifying_question_bounds(self) -> None:
        contract = load_agent_contract("claude-code")
        assert contract.min_clarifying_questions == 2
        assert contract.max_clarifying_questions == 4

    def test_forbidden_commands_include_push_to_main(self) -> None:
        contract = load_agent_contract("claude-code")
        assert any(
            "push" in cmd and "main" in cmd for cmd in contract.forbidden_commands
        )
        assert "--no-verify" in contract.forbidden_commands

    def test_missing_agent_raises(self) -> None:
        with pytest.raises(KeyError, match="no-such-agent"):
            load_agent_contract("no-such-agent")

    def test_custom_path_override(self, tmp_path: Path) -> None:
        custom = tmp_path / "agent_contract.yaml"
        custom.write_text(
            yaml.safe_dump(
                {
                    "fake-agent": {
                        "base_branch": "main",
                        "branch_regex": "^fake/.+$",
                        "startup_checks": [],
                        "pr_template_path": "TEMPLATE.md",
                        "pr_required_sections": [],
                        "commit_types": ["feat"],
                        "commit_subject_regex": "^feat: .+",
                        "min_clarifying_questions": 0,
                        "max_clarifying_questions": 0,
                        "forbidden_commands": [],
                    }
                }
            )
        )
        contract = load_agent_contract("fake-agent", path=custom)
        assert contract.base_branch == "main"


class TestAgentContractShape:
    def test_is_frozen_dataclass(self) -> None:
        contract = load_agent_contract("claude-code")
        with pytest.raises((AttributeError, TypeError)):
            contract.base_branch = "something-else"  # type: ignore[misc]

    def test_contract_has_agent_id(self) -> None:
        contract = load_agent_contract("claude-code")
        assert isinstance(contract, AgentContract)
        assert contract.agent_id == "claude-code"
