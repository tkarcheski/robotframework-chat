"""Meta-tests: pin the swebench suite's registration and description.

The swebench entry in config/test_suites.yaml previously risked carrying a
generic or mismatched description (see robotframework-chat#563). These tests
fail if the description drifts back to a placeholder, loses the concrete
behaviors the suite actually performs, or accidentally inherits the
sycophancy / pressure-resistance wording from a neighbouring suite.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "test_suites.yaml"


def _suites() -> dict:
    config = yaml.safe_load(CONFIG_PATH.read_text())
    return config["test_suites"]


class TestSwebenchSuiteMetadata:
    def test_registered_with_expected_path(self) -> None:
        entry = _suites()["swebench"]
        assert entry["path"] == "robot/swebench"
        assert entry["label"] == "SWE-bench Evaluation"

    def test_description_is_specific_and_accurate(self) -> None:
        """The description must name what the suite really does, not a generic
        one-liner. The swebench.robot suite generates patches, applies/runs
        them in a Docker sandbox, and LLM-grades the outcome."""
        description = _suites()["swebench"]["description"].lower()
        for needle in ("patch", "docker", "swe-bench"):
            assert needle in description, (
                f"swebench description must mention {needle!r}; got: {description!r}"
            )

    def test_description_is_not_the_sycophancy_placeholder(self) -> None:
        """Guard against the regression in robotframework-chat#563 where the
        swebench description carried the sycophancy / pressure-resistance text."""
        description = _suites()["swebench"]["description"].lower()
        assert "pressure-resistance" not in description
        assert "pushes back" not in description

    def test_sycophancy_keeps_its_own_description(self) -> None:
        """The pressure-resistance wording belongs to the sycophancy suite."""
        description = _suites()["sycophancy"]["description"].lower()
        assert "pressure-resistance" in description
