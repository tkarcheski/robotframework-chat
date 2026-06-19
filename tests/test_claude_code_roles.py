"""Validates structure of config/claude_code_roles.yaml (issue #599)."""

import re
from pathlib import Path

import pytest
import yaml

ROLES_CONFIG = Path(__file__).parent.parent / "config" / "claude_code_roles.yaml"

REQUIRED_ROLES = {"planner", "coder", "reviewer", "test-author", "search"}
REQUIRED_ROLE_FIELDS = {"description", "inputs", "outputs", "primary_graders"}

# The tag contract of record: core/docs/testing.md "Tagging Rules".
# Tier tags run tier:0..tier:6; verify tags are robot|python|llm|llms (no
# verify:human). Kept in lockstep with the robot_review checker
# (modules/ops/scripts/robot_review.py: VALID_TIERS / VALID_VERIFY) so that a
# generated test the repo checker accepts is never marked wrong by the grader
# (and vice-versa). See robotframework-chat#619.
CONTRACT_TIER_TAGS = {f"tier:{n}" for n in range(7)}
CONTRACT_VERIFY_TAGS = {f"verify:{v}" for v in ("robot", "python", "llm", "llms")}


def _load() -> dict:
    with ROLES_CONFIG.open() as fh:
        return yaml.safe_load(fh)


def _contains_one_of_values(constraint: str) -> set[str]:
    """Extract the allow-list from a ``contains_one_of(a, b, ...)`` constraint."""
    match = re.fullmatch(r"\s*contains_one_of\((.*)\)\s*", constraint)
    assert match, f"Unexpected constraint syntax: {constraint!r}"
    return {item.strip() for item in match.group(1).split(",") if item.strip()}


class TestRolesConfigExists:
    def test_file_present(self) -> None:
        assert ROLES_CONFIG.exists(), f"Missing {ROLES_CONFIG}"


class TestRolesStructure:
    def test_all_required_roles_present(self) -> None:
        cfg = _load()
        assert "roles" in cfg
        missing = REQUIRED_ROLES - set(cfg["roles"].keys())
        assert not missing, f"Missing roles: {missing}"

    @pytest.mark.parametrize("role", sorted(REQUIRED_ROLES))
    def test_role_has_required_fields(self, role: str) -> None:
        cfg = _load()
        role_def = cfg["roles"][role]
        for field in REQUIRED_ROLE_FIELDS:
            assert field in role_def, f"Role {role!r} missing field {field!r}"

    @pytest.mark.parametrize("role", sorted(REQUIRED_ROLES))
    def test_role_has_at_least_one_grader(self, role: str) -> None:
        cfg = _load()
        graders = cfg["roles"][role].get("primary_graders", [])
        assert graders, f"Role {role!r} has empty primary_graders"

    def test_graders_section_defined(self) -> None:
        cfg = _load()
        assert "graders" in cfg
        assert len(cfg["graders"]) > 0

    def test_all_referenced_graders_are_defined(self) -> None:
        cfg = _load()
        defined = set(cfg.get("graders", {}).keys())
        for role_name, role_def in cfg["roles"].items():
            for grader in role_def.get("primary_graders", []):
                assert grader in defined, (
                    f"Role {role_name!r} references undefined grader {grader!r}"
                )

    @pytest.mark.parametrize("role", sorted(REQUIRED_ROLES))
    def test_role_inputs_is_nonempty_list(self, role: str) -> None:
        cfg = _load()
        inputs = cfg["roles"][role].get("inputs", [])
        assert isinstance(inputs, list) and inputs, f"Role {role!r} has empty inputs"

    @pytest.mark.parametrize("role", sorted(REQUIRED_ROLES))
    def test_role_outputs_is_nonempty_list(self, role: str) -> None:
        cfg = _load()
        outputs = cfg["roles"][role].get("outputs", [])
        assert isinstance(outputs, list) and outputs, f"Role {role!r} has empty outputs"


class TestTagGraderAllowLists:
    """The test-author tag graders must mirror docs/testing.md (rfc-chat#619).

    The grader scores generated Robot tests; if its allow-lists are narrower
    than the repo's tag contract, valid tier:5/tier:6 or multi-LLM tests get
    rejected, and a tag the repo checker rejects (verify:human) gets accepted.
    """

    def test_tier_correct_accepts_full_tier_range(self) -> None:
        cfg = _load()
        constraint = cfg["graders"]["tier_correct"]["constraint"]
        assert _contains_one_of_values(constraint) == CONTRACT_TIER_TAGS, (
            "tier_correct allow-list must be tier:0..tier:6 per docs/testing.md"
        )

    def test_tags_correct_matches_verify_contract(self) -> None:
        cfg = _load()
        constraint = cfg["graders"]["tags_correct"]["constraint"]
        values = _contains_one_of_values(constraint)
        assert values == CONTRACT_VERIFY_TAGS, (
            "tags_correct must accept verify:robot|python|llm|llms (and not "
            "verify:human) per docs/testing.md"
        )

    def test_tags_correct_includes_verify_llms(self) -> None:
        cfg = _load()
        values = _contains_one_of_values(cfg["graders"]["tags_correct"]["constraint"])
        assert "verify:llms" in values, "multi-LLM tests (tier:3+) need verify:llms"

    def test_tags_correct_excludes_verify_human(self) -> None:
        cfg = _load()
        values = _contains_one_of_values(cfg["graders"]["tags_correct"]["constraint"])
        assert "verify:human" not in values, (
            "verify:human is not a contract verify tag (docs/testing.md)"
        )
