"""Tests for rfc.causal_reasoning_grader.CausalReasoningGrader."""

from unittest.mock import MagicMock

import pytest

from rfc.causal_reasoning_grader import CausalGradeResult, CausalReasoningGrader


class TestCausalGradeResult:
    def test_valid_result(self):
        r = CausalGradeResult(score=0.8, reason="correct", question_type="cause_id")
        assert r.score == 0.8
        assert r.passed is True

    def test_score_below_threshold_is_fail(self):
        r = CausalGradeResult(score=0.4, reason="wrong", question_type="cause_id")
        assert r.passed is False

    def test_score_boundary_pass(self):
        r = CausalGradeResult(score=0.5, reason="borderline", question_type="effect_pred")
        assert r.passed is True

    def test_score_must_be_float(self):
        with pytest.raises(TypeError, match="score must be a float"):
            CausalGradeResult(score="bad", reason="x", question_type="cause_id")  # type: ignore[arg-type]

    def test_score_out_of_range(self):
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            CausalGradeResult(score=1.5, reason="x", question_type="cause_id")

    def test_question_type_stored(self):
        r = CausalGradeResult(score=1.0, reason="ok", question_type="counterfactual")
        assert r.question_type == "counterfactual"


class TestCausalReasoningGraderInit:
    def test_none_client_rejected(self):
        with pytest.raises(TypeError, match="llm_client must not be None"):
            CausalReasoningGrader(None)

    def test_valid_client_stored(self):
        client = MagicMock()
        grader = CausalReasoningGrader(client)
        assert grader.llm is client


class TestCausalReasoningGraderGrade:
    def _make_grader(self, response: str) -> CausalReasoningGrader:
        client = MagicMock()
        client.generate.return_value = response
        return CausalReasoningGrader(client)

    def test_correct_cause_identification(self):
        grader = self._make_grader('{"score": 0.9, "reason": "correct cause named"}')
        result = grader.grade(
            scenario="Smoking causes lung cancer.",
            question="What is the primary cause of lung cancer in this scenario?",
            expected="smoking",
            actual="The primary cause is smoking.",
            question_type="cause_id",
        )
        assert isinstance(result, CausalGradeResult)
        assert result.score == pytest.approx(0.9)
        assert result.question_type == "cause_id"

    def test_wrong_cause_scored_zero(self):
        grader = self._make_grader('{"score": 0.0, "reason": "wrong cause named"}')
        result = grader.grade(
            scenario="Smoking causes lung cancer.",
            question="What causes lung cancer?",
            expected="smoking",
            actual="Genetics causes lung cancer.",
            question_type="cause_id",
        )
        assert result.score == pytest.approx(0.0)
        assert result.passed is False

    def test_counterfactual_correct(self):
        grader = self._make_grader('{"score": 1.0, "reason": "correct counterfactual"}')
        result = grader.grade(
            scenario="The match caused the fire.",
            question="If no match had been struck, would the fire have started?",
            expected="No, without the match there would be no fire.",
            actual="No, the fire would not have started without the match.",
            question_type="counterfactual",
        )
        assert result.score == pytest.approx(1.0)
        assert result.question_type == "counterfactual"

    def test_correlation_vs_causation(self):
        grader = self._make_grader('{"score": 0.85, "reason": "correctly identified spurious correlation"}')
        result = grader.grade(
            scenario="Ice cream sales and drowning rates both rise in summer.",
            question="Does ice cream consumption cause drowning?",
            expected="No. Both are caused by hot weather (confounding variable), not each other.",
            actual="No, ice cream does not cause drowning. Hot weather drives both.",
            question_type="correlation_vs_causation",
        )
        assert result.score == pytest.approx(0.85)

    def test_effect_prediction(self):
        grader = self._make_grader('{"score": 0.75, "reason": "partial credit — correct effect, missing magnitude"}')
        result = grader.grade(
            scenario="Increasing the price of a good reduces demand.",
            question="If the price doubles, what happens to quantity demanded?",
            expected="Quantity demanded decreases (demand falls).",
            actual="Quantity demanded will go down.",
            question_type="effect_pred",
        )
        assert result.score == pytest.approx(0.75)

    def test_causal_chain(self):
        grader = self._make_grader('{"score": 1.0, "reason": "full chain traced correctly"}')
        result = grader.grade(
            scenario="Deforestation leads to soil erosion, which leads to river silting, which leads to flooding.",
            question="What is the initiating cause of the flooding in this chain?",
            expected="deforestation",
            actual="The root cause is deforestation.",
            question_type="causal_chain",
        )
        assert result.score == pytest.approx(1.0)
        assert result.question_type == "causal_chain"

    def test_empty_actual_scores_zero(self):
        client = MagicMock()
        grader = CausalReasoningGrader(client)
        result = grader.grade(
            scenario="A causes B.",
            question="What causes B?",
            expected="A",
            actual="",
            question_type="cause_id",
        )
        assert result.score == 0.0
        assert result.passed is False
        client.generate.assert_not_called()

    def test_whitespace_actual_scores_zero(self):
        client = MagicMock()
        grader = CausalReasoningGrader(client)
        result = grader.grade(
            scenario="A causes B.",
            question="What causes B?",
            expected="A",
            actual="   \n\t  ",
            question_type="cause_id",
        )
        assert result.score == 0.0
        client.generate.assert_not_called()

    def test_invalid_json_from_grader_raises(self):
        grader = self._make_grader("not valid json at all")
        with pytest.raises(ValueError, match="invalid JSON"):
            grader.grade(
                scenario="S",
                question="Q",
                expected="E",
                actual="A",
                question_type="cause_id",
            )

    def test_missing_score_field_raises(self):
        grader = self._make_grader('{"reason": "missing score"}')
        with pytest.raises(ValueError, match="missing required fields"):
            grader.grade("S", "Q", "E", "A", "cause_id")

    def test_missing_reason_field_raises(self):
        grader = self._make_grader('{"score": 0.5}')
        with pytest.raises(ValueError, match="missing required fields"):
            grader.grade("S", "Q", "E", "A", "cause_id")

    def test_prompt_includes_question_type(self):
        client = MagicMock()
        client.generate.return_value = '{"score": 0.5, "reason": "ok"}'
        grader = CausalReasoningGrader(client)
        grader.grade("S", "Q", "E", "A", "counterfactual")
        prompt = client.generate.call_args[0][0]
        assert "counterfactual" in prompt.lower()

    def test_non_string_scenario_raises(self):
        client = MagicMock()
        grader = CausalReasoningGrader(client)
        with pytest.raises(TypeError, match="scenario must be a str"):
            grader.grade(123, "Q", "E", "A", "cause_id")  # type: ignore[arg-type]

    def test_non_string_actual_raises(self):
        client = MagicMock()
        grader = CausalReasoningGrader(client)
        with pytest.raises(TypeError, match="actual must be a str"):
            grader.grade("S", "Q", "E", 456, "cause_id")  # type: ignore[arg-type]

    def test_partial_credit_propagated(self):
        grader = self._make_grader('{"score": 0.5, "reason": "halfway there"}')
        result = grader.grade("S", "Q", "E", "A", "causal_chain")
        assert result.score == pytest.approx(0.5)
        assert result.passed is True


class TestCausalReasoningGraderCheckStructure:
    """Tests for the Tier 1 deterministic structure checker."""

    def test_valid_json_structure_passes(self):
        client = MagicMock()
        grader = CausalReasoningGrader(client)
        result = grader.check_causal_json_structure(
            '{"cause": "smoking", "effect": "lung cancer"}'
        )
        assert result["has_cause"] is True
        assert result["has_effect"] is True
        assert result["is_valid"] is True

    def test_missing_cause_field_fails(self):
        client = MagicMock()
        grader = CausalReasoningGrader(client)
        result = grader.check_causal_json_structure('{"effect": "cancer"}')
        assert result["has_cause"] is False
        assert result["is_valid"] is False

    def test_missing_effect_field_fails(self):
        client = MagicMock()
        grader = CausalReasoningGrader(client)
        result = grader.check_causal_json_structure('{"cause": "smoking"}')
        assert result["has_effect"] is False
        assert result["is_valid"] is False

    def test_empty_cause_value_fails(self):
        client = MagicMock()
        grader = CausalReasoningGrader(client)
        result = grader.check_causal_json_structure('{"cause": "", "effect": "cancer"}')
        assert result["is_valid"] is False

    def test_invalid_json_is_not_valid(self):
        client = MagicMock()
        grader = CausalReasoningGrader(client)
        result = grader.check_causal_json_structure("not json")
        assert result["is_valid"] is False
        assert result["has_cause"] is False
        assert result["has_effect"] is False

    def test_extra_fields_are_allowed(self):
        client = MagicMock()
        grader = CausalReasoningGrader(client)
        result = grader.check_causal_json_structure(
            '{"cause": "fire", "effect": "smoke", "confidence": "high"}'
        )
        assert result["is_valid"] is True

    def test_empty_array_json_is_not_valid(self):
        # P2 fix: valid JSON that is not an object must not raise AttributeError.
        # extract_json returns "[]" as-is; json.loads gives a list, not a dict.
        client = MagicMock()
        grader = CausalReasoningGrader(client)
        result = grader.check_causal_json_structure("[]")
        assert result["is_valid"] is False
        assert result["has_cause"] is False

    def test_json_number_is_not_valid(self):
        # P2 fix: a bare JSON number is valid JSON but not a dict.
        client = MagicMock()
        grader = CausalReasoningGrader(client)
        result = grader.check_causal_json_structure("42")
        assert result["is_valid"] is False

    def test_unclosed_think_tag_with_json_is_valid(self):
        # P1 fix: extract_json strips thinking tags internally, so raw_response
        # containing an unclosed <think> block followed by JSON is still valid.
        client = MagicMock()
        grader = CausalReasoningGrader(client)
        raw = '<think>reasoning here...\n{"cause": "smoking", "effect": "cancer"}'
        result = grader.check_causal_json_structure(raw)
        assert result["is_valid"] is True
        assert result["cause"] == "smoking"
        assert result["effect"] == "cancer"
