"""Robot Framework keywords for testing AgentSkill behaviors.

Wraps an LLM client and a :class:`SkillGrader` so Robot suites can:

  * load a SKILL.md from disk (file or directory containing ``SKILL.md``),
  * ask the LLM a prompt with the skill content prepended as context,
  * grade the response against a list of expected and prohibited behaviors,
  * assert the result and raise a detailed ``AssertionError`` on failure.

The keywords are designed for tier:2 verify:llm suites where the response
is graded by an LLM-as-judge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword
from robot.libraries.BuiltIn import BuiltIn

from .llm_client import create_provider, resolve_timeout
from .skill_grader import SkillGradeResult, SkillGrader
from .thinking import parse_thinking


class SkillKeywords:
    """Robot Framework keywords for AgentSkill behavioral testing."""

    def __init__(
        self,
        timeout: Optional[int] = None,
        pass_threshold: float = 0.8,
        hide_thinking: bool | str = True,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout)
        self.grader = SkillGrader(self.client, pass_threshold=float(pass_threshold))
        self._hide_thinking: bool = (
            hide_thinking.lower() not in ("false", "0", "no")
            if isinstance(hide_thinking, str)
            else bool(hide_thinking)
        )
        self._skill_cache: Dict[str, str] = {}

    def _load_skill(self, skill_path: str) -> str:
        """Read a SKILL.md from a file or a directory and cache by path."""
        path = Path(skill_path).expanduser()
        resolved = str(path.resolve())

        if resolved in self._skill_cache:
            return self._skill_cache[resolved]

        if not path.exists():
            raise FileNotFoundError(f"Skill path does not exist: {skill_path}")

        if path.is_dir():
            skill_file = path / "SKILL.md"
            if not skill_file.exists():
                raise FileNotFoundError(
                    f"Directory {skill_path} does not contain SKILL.md"
                )
            content = skill_file.read_text(encoding="utf-8")
        else:
            content = path.read_text(encoding="utf-8")

        self._skill_cache[resolved] = content
        return content

    @staticmethod
    def _skill_available(skill_path: str) -> bool:
        """Return True when *skill_path* resolves to a usable SKILL.md."""
        path = Path(skill_path).expanduser()
        if path.is_dir():
            return (path / "SKILL.md").is_file()
        return path.is_file()

    @staticmethod
    def _build_skill_prompt(skill_content: str, user_prompt: str) -> str:
        return f"[SKILL CONTEXT]\n{skill_content}\n[/SKILL CONTEXT]\n\n{user_prompt}"

    @keyword("Skip Unless Skill Available")
    def skip_unless_skill_available(self, skill_path: str) -> None:
        """Skip the suite when no skill is present at *skill_path*.

        Lets a suite be registered in the local-model runner without
        deterministically hard-failing: when the skill has not been checked
        out, the suite is skipped with a clear message instead of every test
        raising FileNotFoundError.
        """
        if self._skill_available(skill_path):
            logger.info(f"Skill available at {skill_path}")
            return
        BuiltIn().skip(
            f"Skill not found at '{skill_path}'. Set the SKILL_PATH environment "
            f"variable to a checkout of the skill to run this suite."
        )

    @keyword("Load Skill")
    def load_skill(self, skill_path: str) -> str:
        """Load SKILL.md content from a file or directory."""
        content = self._load_skill(skill_path)
        logger.info(f"Loaded skill from {skill_path} ({len(content)} chars)")
        return content

    @keyword("Ask With Skill")
    def ask_with_skill(self, skill_path: str, prompt: str) -> str:
        """Send a prompt with skill content prepended as context."""
        skill_content = self._load_skill(skill_path)
        full_prompt = self._build_skill_prompt(skill_content, prompt)
        raw = self.client.generate(full_prompt)
        clean, _ = parse_thinking(raw, strip_unclosed=self._hide_thinking)
        logger.info(clean)
        return clean

    @keyword("Grade Skill Response")
    def grade_skill_response(
        self,
        response: str,
        test_id: str,
        expected_behaviors: List[str],
        must_not: Optional[List[str]] = None,
    ) -> SkillGradeResult:
        """Grade a response against expected and prohibited behaviors."""
        return self.grader.grade(
            test_id=test_id,
            response=response,
            expected_behaviors=list(expected_behaviors),
            must_not=list(must_not or []),
        )

    @keyword("Assert Skill Grade Passed")
    def assert_skill_grade_passed(self, result: SkillGradeResult) -> None:
        """Assert that a SkillGradeResult passed; raise with detail otherwise."""
        if result.passed:
            return

        lines = [
            f"Skill test '{result.test_id}' failed.",
            f"  behavior_pass_rate={result.behavior_pass_rate:.3f} "
            f"threshold={self.grader.pass_threshold:.3f}",
        ]
        if result.must_not_violations:
            lines.append("  must_not violations:")
            for v in result.must_not_violations:
                lines.append(f"    - {v.assertion}: {v.reason}")
        failed_behaviors = [r for r in result.behavior_results if not r.passed]
        if failed_behaviors:
            lines.append("  failed expected behaviors:")
            for r in failed_behaviors:
                lines.append(f"    - {r.assertion} (score={r.score:.2f}): {r.reason}")
        raise AssertionError("\n".join(lines))

    @keyword("Run Skill Test Case")
    def run_skill_test_case(
        self, skill_path: str, test_case: Dict[str, Any]
    ) -> SkillGradeResult:
        """End-to-end: ask with skill, grade, return the result.

        ``test_case`` must contain ``id`` and ``prompt`` keys; optional keys
        are ``expected_behaviors`` (list[str]) and ``must_not`` (list[str]).
        """
        test_id = str(test_case["id"])
        prompt = str(test_case["prompt"])
        expected_behaviors = list(test_case.get("expected_behaviors", []))
        must_not = list(test_case.get("must_not", []))

        response = self.ask_with_skill(skill_path, prompt)
        return self.grade_skill_response(
            response=response,
            test_id=test_id,
            expected_behaviors=expected_behaviors,
            must_not=must_not,
        )
