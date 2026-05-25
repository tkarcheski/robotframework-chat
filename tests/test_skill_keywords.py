"""Unit tests for :mod:`rfc.skill_keywords`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rfc.skill_grader import BehaviorResult, SkillGradeResult
from rfc.skill_keywords import SkillKeywords


@pytest.fixture
def keywords() -> SkillKeywords:
    """Construct a SkillKeywords with mocked client and grader."""
    with patch("rfc.skill_keywords.create_provider") as fake_provider:
        fake_provider.return_value = MagicMock()
        kw = SkillKeywords()
    kw.client = MagicMock()
    kw.grader = MagicMock()
    kw.grader.pass_threshold = 0.8
    return kw


# ---------------------------------------------------------------------------
# _load_skill / Load Skill
# ---------------------------------------------------------------------------


class TestLoadSkill:
    def test_directory_path_reads_skill_md(
        self, keywords: SkillKeywords, tmp_path: Path
    ) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Skill\nhello")
        content = keywords._load_skill(str(skill_dir))
        assert content == "# Skill\nhello"

    def test_direct_file_path(self, keywords: SkillKeywords, tmp_path: Path) -> None:
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("# Direct file")
        content = keywords._load_skill(str(skill_file))
        assert content == "# Direct file"

    def test_caching_avoids_second_read(
        self, keywords: SkillKeywords, tmp_path: Path
    ) -> None:
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("first")
        first = keywords._load_skill(str(skill_file))
        # Mutate the file on disk; a cached read must return the original.
        skill_file.write_text("second")
        second = keywords._load_skill(str(skill_file))
        assert first == second == "first"

    def test_missing_directory_raises(
        self, keywords: SkillKeywords, tmp_path: Path
    ) -> None:
        missing = tmp_path / "does-not-exist"
        with pytest.raises(FileNotFoundError):
            keywords._load_skill(str(missing))

    def test_directory_without_skill_md_raises(
        self, keywords: SkillKeywords, tmp_path: Path
    ) -> None:
        empty_dir = tmp_path / "empty-skill"
        empty_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            keywords._load_skill(str(empty_dir))


# ---------------------------------------------------------------------------
# _build_skill_prompt
# ---------------------------------------------------------------------------


class TestBuildSkillPrompt:
    def test_format(self) -> None:
        out = SkillKeywords._build_skill_prompt("SKILL BODY", "user question")
        assert out.startswith("[SKILL CONTEXT]")
        assert "SKILL BODY" in out
        assert "[/SKILL CONTEXT]" in out
        assert out.rstrip().endswith("user question")


# ---------------------------------------------------------------------------
# hide_thinking string parsing
# ---------------------------------------------------------------------------


class TestHideThinkingParsing:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("false", False),
            ("False", False),
            ("0", False),
            ("no", False),
            ("true", True),
            ("True", True),
            ("1", True),
            ("yes", True),
        ],
    )
    def test_string_values(self, value: str, expected: bool) -> None:
        with patch("rfc.skill_keywords.create_provider") as fake_provider:
            fake_provider.return_value = MagicMock()
            kw = SkillKeywords(hide_thinking=value)
        assert kw._hide_thinking is expected


# ---------------------------------------------------------------------------
# assert_skill_grade_passed
# ---------------------------------------------------------------------------


def _make_result(
    *,
    passed: bool,
    test_id: str = "TP-X",
    behavior_pass_rate: float = 1.0,
    must_not_violations: list[BehaviorResult] | None = None,
    behavior_results: list[BehaviorResult] | None = None,
) -> SkillGradeResult:
    return SkillGradeResult(
        test_id=test_id,
        passed=passed,
        behavior_pass_rate=behavior_pass_rate,
        must_not_violations=list(must_not_violations or []),
        behavior_results=list(behavior_results or []),
        response="some response",
    )


class TestAssertSkillGradePassed:
    def test_passes_silently_when_passed(self, keywords: SkillKeywords) -> None:
        result = _make_result(passed=True)
        keywords.assert_skill_grade_passed(result)  # no raise

    def test_failed_includes_test_id(self, keywords: SkillKeywords) -> None:
        result = _make_result(
            passed=False,
            test_id="TP-42",
            behavior_pass_rate=0.5,
            behavior_results=[
                BehaviorResult(
                    assertion="asks questions",
                    passed=False,
                    score=0.1,
                    reason="did not ask",
                )
            ],
        )
        with pytest.raises(AssertionError) as exc_info:
            keywords.assert_skill_grade_passed(result)
        assert "TP-42" in str(exc_info.value)

    def test_must_not_violation_in_message(self, keywords: SkillKeywords) -> None:
        violation = BehaviorResult(
            assertion="lectures the user",
            passed=False,
            score=0.0,
            reason="response was a lecture",
        )
        result = _make_result(
            passed=False,
            must_not_violations=[violation],
            behavior_pass_rate=1.0,
        )
        with pytest.raises(AssertionError) as exc_info:
            keywords.assert_skill_grade_passed(result)
        msg = str(exc_info.value)
        assert "must_not violations" in msg
        assert "lectures the user" in msg
        assert "response was a lecture" in msg
