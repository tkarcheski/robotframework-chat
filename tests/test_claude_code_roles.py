"""Validates structure of config/claude_code_roles.yaml (issue #599)."""

from pathlib import Path

import pytest
import yaml

ROLES_CONFIG = Path(__file__).parent.parent / "config" / "claude_code_roles.yaml"

REQUIRED_ROLES = {"planner", "coder", "reviewer", "test-author", "search"}
REQUIRED_ROLE_FIELDS = {"description", "inputs", "outputs", "primary_graders"}


def _load() -> dict:
    with ROLES_CONFIG.open() as fh:
        return yaml.safe_load(fh)


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
