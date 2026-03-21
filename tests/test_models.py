"""Tests for rfc.models dataclasses."""

import pytest
from rfc.models import GradeResult, SafetyResult


class TestGradeResult:
    def test_valid_pass(self):
        r = GradeResult(score=1.0, reason="correct")
        assert r.score == 1.0
        assert r.reason == "correct"

    def test_valid_fail(self):
        r = GradeResult(score=0.0, reason="wrong answer")
        assert r.score == 0.0
        assert r.reason == "wrong answer"

    def test_valid_partial_score(self):
        r = GradeResult(score=0.5, reason="partially correct")
        assert r.score == 0.5

    def test_valid_high_partial_score(self):
        r = GradeResult(score=0.75, reason="mostly correct")
        assert r.score == 0.75

    def test_int_score_coerced_to_float(self):
        r = GradeResult(score=1, reason="correct")
        assert isinstance(r.score, float)
        assert r.score == 1.0

    def test_invalid_score_above_range(self):
        with pytest.raises(ValueError, match="score must be between 0.0 and 1.0"):
            GradeResult(score=1.5, reason="bad")

    def test_invalid_score_negative(self):
        with pytest.raises(ValueError, match="score must be between 0.0 and 1.0"):
            GradeResult(score=-0.1, reason="bad")

    def test_invalid_score_type(self):
        with pytest.raises(TypeError, match="score must be a float"):
            GradeResult(score="1", reason="bad")

    def test_invalid_reason_type(self):
        with pytest.raises(TypeError, match="reason must be a str"):
            GradeResult(score=1.0, reason=123)

    def test_score_at_boundaries(self):
        r0 = GradeResult(score=0.0, reason="zero")
        assert r0.score == 0.0
        r1 = GradeResult(score=1.0, reason="one")
        assert r1.score == 1.0


class TestSafetyResult:
    def test_valid_safe(self):
        r = SafetyResult(
            is_safe=True,
            confidence=0.8,
            violation_type=None,
            indicators=[],
            details={},
        )
        assert r.is_safe is True
        assert r.confidence == 0.8

    def test_valid_unsafe(self):
        r = SafetyResult(
            is_safe=False,
            confidence=0.9,
            violation_type="injection",
            indicators=["compliance"],
            details={"risk": "high"},
        )
        assert r.is_safe is False
        assert r.violation_type == "injection"

    def test_invalid_confidence_too_high(self):
        with pytest.raises(ValueError, match="confidence must be between"):
            SafetyResult(
                is_safe=True,
                confidence=1.5,
                violation_type=None,
                indicators=[],
                details={},
            )

    def test_invalid_confidence_negative(self):
        with pytest.raises(ValueError, match="confidence must be between"):
            SafetyResult(
                is_safe=True,
                confidence=-0.1,
                violation_type=None,
                indicators=[],
                details={},
            )

    def test_invalid_is_safe_type(self):
        with pytest.raises(TypeError, match="is_safe must be a bool"):
            SafetyResult(
                is_safe="yes",
                confidence=0.5,
                violation_type=None,
                indicators=[],
                details={},
            )

    def test_invalid_indicators_type(self):
        with pytest.raises(TypeError, match="indicators must be a list"):
            SafetyResult(
                is_safe=True,
                confidence=0.5,
                violation_type=None,
                indicators="not_a_list",
                details={},
            )

    def test_confidence_at_boundaries(self):
        r0 = SafetyResult(
            is_safe=True,
            confidence=0.0,
            violation_type=None,
            indicators=[],
            details={},
        )
        assert r0.confidence == 0.0

        r1 = SafetyResult(
            is_safe=True,
            confidence=1.0,
            violation_type=None,
            indicators=[],
            details={},
        )
        assert r1.confidence == 1.0

    def test_confidence_accepts_int(self):
        r = SafetyResult(
            is_safe=True,
            confidence=1,
            violation_type=None,
            indicators=[],
            details={},
        )
        assert r.confidence == 1

    def test_non_numeric_confidence_raises(self):
        with pytest.raises(TypeError, match="confidence must be a float"):
            SafetyResult(
                is_safe=True,
                confidence="high",
                violation_type=None,
                indicators=[],
                details={},
            )
