"""Unit tests for :mod:`rfc.skill_grader`."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from rfc.skill_grader import (
    BehaviorResult,
    SkillGradeResult,
    SkillGrader,
    _coerce_bool,
)


def make_client(*responses: str) -> MagicMock:
    """Build a mock LLM client whose ``generate()`` returns *responses* in order."""
    client = MagicMock()
    client.generate.side_effect = list(responses)
    return client


def batch_json(*entries: tuple[int, float, bool, str]) -> str:
    return json.dumps(
        {
            "results": [
                {
                    "index": idx,
                    "score": score,
                    "passed": passed,
                    "reason": reason,
                }
                for idx, score, passed, reason in entries
            ]
        }
    )


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestSkillGraderConstructor:
    def test_pass_threshold_zero_raises(self) -> None:
        with pytest.raises(ValueError):
            SkillGrader(MagicMock(), pass_threshold=0.0)

    def test_pass_threshold_above_one_raises(self) -> None:
        with pytest.raises(ValueError):
            SkillGrader(MagicMock(), pass_threshold=1.1)

    def test_pass_threshold_one_is_valid(self) -> None:
        grader = SkillGrader(MagicMock(), pass_threshold=1.0)
        assert grader.pass_threshold == 1.0

    def test_none_llm_client_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            SkillGrader(None)


# ---------------------------------------------------------------------------
# grade() behavior
# ---------------------------------------------------------------------------


class TestSkillGraderGrade:
    def test_empty_response_short_circuits(self) -> None:
        client = MagicMock()
        grader = SkillGrader(client)

        result = grader.grade(
            test_id="TP-01",
            response="",
            expected_behaviors=["asks a clarifying question"],
            must_not=["jumps to a solution"],
        )

        assert result.passed is False
        assert result.behavior_pass_rate == 0.0
        assert result.behavior_results[0].passed is False
        assert result.behavior_results[0].score == 0.0
        client.generate.assert_not_called()

    def test_whitespace_only_response_short_circuits(self) -> None:
        client = MagicMock()
        grader = SkillGrader(client)
        result = grader.grade("TP-X", "   \n\t  ", ["does X"], must_not=[])
        assert result.passed is False
        client.generate.assert_not_called()

    def test_all_behaviors_pass(self) -> None:
        client = make_client(
            batch_json((1, 1.0, True, "good"), (2, 0.9, True, "also good")),
        )
        grader = SkillGrader(client)
        result = grader.grade(
            test_id="TP-02",
            response="hello world",
            expected_behaviors=["b1", "b2"],
            must_not=[],
        )
        assert result.passed is True
        assert result.behavior_pass_rate == 1.0
        assert all(r.passed for r in result.behavior_results)

    def test_below_threshold_one_of_three_passes(self) -> None:
        client = make_client(
            batch_json(
                (1, 0.9, True, "ok"),
                (2, 0.2, False, "no"),
                (3, 0.1, False, "no"),
            )
        )
        grader = SkillGrader(client, pass_threshold=0.8)
        result = grader.grade(
            test_id="TP-03",
            response="response text",
            expected_behaviors=["b1", "b2", "b3"],
            must_not=[],
        )
        assert result.behavior_pass_rate == pytest.approx(1 / 3, rel=1e-3)
        assert result.passed is False

    def test_must_not_violation_fails(self) -> None:
        client = make_client(
            json.dumps({"violated": True, "reason": "lectured the user"}),
            batch_json((1, 1.0, True, "good")),
        )
        grader = SkillGrader(client)
        result = grader.grade(
            test_id="TP-04",
            response="response",
            expected_behaviors=["b1"],
            must_not=["lectures the user"],
        )
        assert result.passed is False
        assert len(result.must_not_violations) == 1
        assert result.must_not_violations[0].assertion == "lectures the user"

    def test_must_not_passes_when_not_violated(self) -> None:
        client = make_client(
            json.dumps({"violated": False, "reason": "no violation"}),
            batch_json((1, 1.0, True, "good")),
        )
        grader = SkillGrader(client)
        result = grader.grade(
            test_id="TP-05",
            response="response",
            expected_behaviors=["b1"],
            must_not=["lectures the user"],
        )
        assert result.must_not_violations == []
        assert result.passed is True

    def test_invalid_batch_json_falls_back_to_fail(self) -> None:
        client = make_client("not json at all")
        grader = SkillGrader(client)
        result = grader.grade(
            test_id="TP-06",
            response="response",
            expected_behaviors=["b1", "b2"],
            must_not=[],
        )
        assert result.passed is False
        assert all(not r.passed for r in result.behavior_results)
        assert all(r.score == 0.0 for r in result.behavior_results)

    def test_invalid_must_not_json_treated_as_violation(self) -> None:
        client = make_client(
            "this is not json",
            batch_json((1, 1.0, True, "good")),
        )
        grader = SkillGrader(client)
        result = grader.grade(
            test_id="TP-07",
            response="response",
            expected_behaviors=["b1"],
            must_not=["does X"],
        )
        assert result.passed is False
        assert len(result.must_not_violations) == 1

    def test_pass_rate_exactly_at_threshold_passes(self) -> None:
        # 4 out of 5 = 0.8, threshold 0.8 → passes.
        client = make_client(
            batch_json(
                (1, 1.0, True, "ok"),
                (2, 1.0, True, "ok"),
                (3, 1.0, True, "ok"),
                (4, 1.0, True, "ok"),
                (5, 0.2, False, "no"),
            )
        )
        grader = SkillGrader(client, pass_threshold=0.8)
        result = grader.grade(
            test_id="TP-08",
            response="response",
            expected_behaviors=["b1", "b2", "b3", "b4", "b5"],
            must_not=[],
        )
        assert result.behavior_pass_rate == 0.8
        assert result.passed is True


# ---------------------------------------------------------------------------
# Dataclass validation
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_skill_grade_result_passed_must_be_bool(self) -> None:
        with pytest.raises(TypeError):
            SkillGradeResult(
                test_id="X",
                passed="yes",  # type: ignore[arg-type]
                behavior_pass_rate=1.0,
                must_not_violations=[],
                behavior_results=[],
                response="r",
            )

    def test_skill_grade_result_behavior_pass_rate_range(self) -> None:
        with pytest.raises(ValueError):
            SkillGradeResult(
                test_id="X",
                passed=True,
                behavior_pass_rate=1.5,
                must_not_violations=[],
                behavior_results=[],
                response="r",
            )

    def test_behavior_result_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError):
            BehaviorResult(assertion="b", passed=True, score=1.5, reason="r")


# ---------------------------------------------------------------------------
# Boolean coercion of judge output
# ---------------------------------------------------------------------------


class TestCoerceBool:
    @pytest.mark.parametrize(
        "value,default,expected",
        [
            (True, False, True),
            (False, True, False),
            ("true", False, True),
            ("True", False, True),
            ("  TRUE  ", False, True),
            ("false", True, False),
            ("False", True, False),
            ("yes", False, True),
            ("no", True, False),
            ("1", False, True),
            ("0", True, False),
            (1, False, True),
            (0, True, False),
            ("maybe", False, False),
            ("maybe", True, True),
            (None, False, False),
            (None, True, True),
        ],
    )
    def test_coerce_bool(self, value: object, default: bool, expected: bool) -> None:
        assert _coerce_bool(value, default) is expected


class TestViolatedCoercion:
    def test_violated_false_string_is_not_a_violation(self) -> None:
        # Judge returns the *string* "false"; bool("false") is True, so the
        # naive coercion would wrongly record a violation.
        client = make_client(
            json.dumps({"violated": "false", "reason": "no violation"}),
            batch_json((1, 1.0, True, "good")),
        )
        grader = SkillGrader(client)
        result = grader.grade(
            test_id="TP-COERCE-1",
            response="response",
            expected_behaviors=["b1"],
            must_not=["lectures the user"],
        )
        assert result.must_not_violations == []
        assert result.passed is True

    def test_violated_true_string_is_a_violation(self) -> None:
        client = make_client(
            json.dumps({"violated": "true", "reason": "lectured"}),
            batch_json((1, 1.0, True, "good")),
        )
        grader = SkillGrader(client)
        result = grader.grade(
            test_id="TP-COERCE-2",
            response="response",
            expected_behaviors=["b1"],
            must_not=["lectures the user"],
        )
        assert len(result.must_not_violations) == 1
        assert result.passed is False


class TestPassedCoercion:
    def test_passed_false_string_counts_as_failed(self) -> None:
        # A failed behavior reported as the string "false" must not inflate
        # the pass rate via truthy-string coercion.
        raw = json.dumps(
            {"results": [{"index": 1, "score": 0.9, "passed": "false", "reason": "no"}]}
        )
        grader = SkillGrader(make_client(raw))
        result = grader.grade(
            test_id="TP-COERCE-3",
            response="response",
            expected_behaviors=["b1"],
            must_not=[],
        )
        assert result.behavior_results[0].passed is False
        assert result.behavior_pass_rate == 0.0
        assert result.passed is False

    def test_passed_true_string_counts_as_passed(self) -> None:
        raw = json.dumps(
            {"results": [{"index": 1, "score": 0.9, "passed": "true", "reason": "ok"}]}
        )
        grader = SkillGrader(make_client(raw))
        result = grader.grade(
            test_id="TP-COERCE-4",
            response="response",
            expected_behaviors=["b1"],
            must_not=[],
        )
        assert result.behavior_results[0].passed is True
        assert result.behavior_pass_rate == 1.0

    def test_passed_missing_falls_back_to_score_threshold(self) -> None:
        # No "passed" key: default to score >= 0.7.
        raw = json.dumps(
            {
                "results": [
                    {"index": 1, "score": 0.8, "reason": "high"},
                    {"index": 2, "score": 0.5, "reason": "low"},
                ]
            }
        )
        grader = SkillGrader(make_client(raw))
        result = grader.grade(
            test_id="TP-COERCE-5",
            response="response",
            expected_behaviors=["b1", "b2"],
            must_not=[],
        )
        assert result.behavior_results[0].passed is True
        assert result.behavior_results[1].passed is False
