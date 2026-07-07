"""Meta-tests: enforce tags and registration for the agentic-coding suite.

These tests fail if a future change drops a required tag from a Robot test,
forgets to register the suite in config/test_suites.yaml, or lets a Tier 1
test import LLM grading libraries (which would violate ai/testing.md).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SUITE_ROOT = REPO_ROOT / "robot" / "40__tier4" / "agentic_coding"
SUITE_TESTS = SUITE_ROOT

TIER_PATTERN = re.compile(r"\btier:\d\b")
VERIFY_PATTERN = re.compile(r"\bverify:(robot|python|llm|llms)\b")
TEST_CASE_HEADER = re.compile(r"^\*\*\*\s+Test Cases\s+\*\*\*\s*$", re.MULTILINE)
TAGS_LINE = re.compile(r"^\s*\[Tags\]\s+(.+)$", re.MULTILINE)


def _robot_test_files() -> list[Path]:
    # rglob so nested suites (e.g. tests/test_sandboxed.robot,
    # tests/test_workflow.robot) cannot dodge the tag and fixture checks.
    return sorted(p for p in SUITE_TESTS.rglob("*.robot") if p.name != "__init__.robot")


def _iter_test_cases(robot_file: Path) -> list[tuple[str, str]]:
    """Yield (test_name, tag_line) for each test case in a .robot file."""
    text = robot_file.read_text()
    split = TEST_CASE_HEADER.split(text)
    if len(split) < 2:
        return []
    body = split[-1]
    # Stop at next *** Section
    body = re.split(r"^\*\*\*\s+\w", body, maxsplit=1, flags=re.MULTILINE)[0]

    cases: list[tuple[str, str]] = []
    current_name: str | None = None
    for line in body.splitlines():
        if (
            line
            and not line.startswith(" ")
            and not line.startswith("\t")
            and line.strip()
        ):
            current_name = line.strip()
        tag_match = TAGS_LINE.match(line)
        if tag_match and current_name is not None:
            cases.append((current_name, tag_match.group(1)))
            current_name = None
    return cases


class TestAgenticCodingRobotTagging:
    def test_suite_dir_exists(self) -> None:
        assert SUITE_TESTS.is_dir(), f"{SUITE_TESTS} must exist"

    def test_at_least_three_robot_files(self) -> None:
        files = _robot_test_files()
        assert len(files) >= 3, f"Expected >=3 .robot test files, found {len(files)}"

    @pytest.mark.parametrize("robot_file", _robot_test_files(), ids=lambda p: p.name)
    def test_each_test_has_exactly_one_tier_tag(self, robot_file: Path) -> None:
        cases = _iter_test_cases(robot_file)
        assert cases, f"{robot_file.name} contains no test cases"
        for name, tags in cases:
            matches = TIER_PATTERN.findall(tags)
            assert len(matches) == 1, (
                f"{robot_file.name}::{name} must have exactly one tier:* tag, got {matches}"
            )

    @pytest.mark.parametrize("robot_file", _robot_test_files(), ids=lambda p: p.name)
    def test_each_test_has_exactly_one_verify_tag(self, robot_file: Path) -> None:
        cases = _iter_test_cases(robot_file)
        assert cases, f"{robot_file.name} contains no test cases"
        for name, tags in cases:
            matches = VERIFY_PATTERN.findall(tags)
            assert len(matches) == 1, (
                f"{robot_file.name}::{name} must have exactly one verify:* tag, got {matches}"
            )

    @pytest.mark.parametrize("robot_file", _robot_test_files(), ids=lambda p: p.name)
    def test_tier_1_files_do_not_import_llm_graders(self, robot_file: Path) -> None:
        """Per ai/testing.md: tier:0-1 tests must not pull in LLM grading keywords."""
        cases = _iter_test_cases(robot_file)
        tiers = {
            int(TIER_PATTERN.search(tags).group().split(":")[1])  # type: ignore[union-attr]
            for _, tags in cases
            if TIER_PATTERN.search(tags)
        }
        if not tiers or max(tiers) >= 2:
            pytest.skip("Not a pure tier:0-1 file")
        forbidden = [
            "Library    rfc.grader.",
            "Library    rfc.multi_grader.",
            "rfc.bias_grader",
        ]
        text = robot_file.read_text()
        for needle in forbidden:
            assert needle not in text, (
                f"{robot_file.name} is tier:1 but imports LLM grader: {needle!r}"
            )


class TestAgenticCodingConfigRegistration:
    def test_registered_in_test_suites_yaml(self) -> None:
        config = yaml.safe_load((REPO_ROOT / "config" / "test_suites.yaml").read_text())
        assert "agentic-coding" in config["test_suites"], (
            "agentic-coding suite must be registered in config/test_suites.yaml"
        )
        entry = config["test_suites"]["agentic-coding"]
        assert entry["path"] == "robot/40__tier4/agentic_coding"

    def test_registered_in_local_agents_yaml(self) -> None:
        config = yaml.safe_load(
            (REPO_ROOT / "config" / "local_agents.yaml").read_text()
        )
        suite_ids = {ex["suite"] for ex in config.get("executions", [])}
        assert "agentic-coding" in suite_ids, (
            "agentic-coding must appear in config/local_agents.yaml executions"
        )
        agent_ids = {a["id"] for a in config.get("agents", [])}
        assert "claude-code" in agent_ids

    def test_claude_code_contract_is_loadable(self) -> None:
        from rfc.agent_contract import load_agent_contract

        contract = load_agent_contract("claude-code")
        assert contract.base_branch == "claude-code-staging"
        assert contract.branch_regex.startswith("^claude/")


class TestAgenticCodingFixtures:
    def test_each_referenced_scenario_has_a_fixture(self) -> None:
        """Every scenario:* tag referenced in a Robot test must have a run.yaml."""
        fixtures_dir = SUITE_ROOT / "fixtures"
        assert fixtures_dir.is_dir()

        referenced: set[str] = set()
        for robot_file in _robot_test_files():
            for match in re.finditer(
                r"scenario:([a-zA-Z0-9_]+)", robot_file.read_text()
            ):
                referenced.add(match.group(1))

        assert referenced, "Expected at least one scenario:* tag in Robot tests"
        for scenario_id in referenced:
            assert (fixtures_dir / scenario_id / "run.yaml").is_file(), (
                f"Scenario {scenario_id!r} is tagged but has no fixtures/{scenario_id}/run.yaml"
            )
