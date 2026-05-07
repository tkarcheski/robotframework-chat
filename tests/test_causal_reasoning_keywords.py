"""Tests for rfc.causal_reasoning_keywords.CausalReasoningKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.causal_reasoning_keywords import CausalReasoningKeywords


class TestCausalReasoningKeywordsInit:
    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_default_init(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        CausalReasoningKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)
        MockGrader.assert_called_once_with(mock_create.return_value)

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_custom_timeout_and_retries(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        CausalReasoningKeywords(timeout=60, max_retries=3)
        mock_create.assert_called_once_with(timeout=60, max_retries=3)


class TestRunCausalDiscriminationTest:
    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_passes_when_score_above_threshold(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = "This is a correlation, not causation."
        mock_grade = MagicMock()
        mock_grade.score = 0.9
        mock_grade.reason = "correctly identified correlation + confound"
        kw.grader.grade.return_value = mock_grade

        result = kw.run_causal_discrimination_test(
            scenario="Ice cream sales and drowning rates are correlated.",
            expected="correlation, not causation; summer heat is the confound",
        )

        assert result["score"] == 0.9
        assert result["passed"] is True

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_fails_when_score_below_threshold(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = "Yes, eating ice cream causes drowning."
        mock_grade = MagicMock()
        mock_grade.score = 0.0
        mock_grade.reason = "incorrect — stated causal relationship"
        kw.grader.grade.return_value = mock_grade

        result = kw.run_causal_discrimination_test(
            scenario="Ice cream sales and drowning rates are correlated.",
            expected="correlation, not causation",
            min_score=0.5,
        )

        assert result["passed"] is False

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_raises_on_empty_scenario(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        with pytest.raises(ValueError, match="scenario must not be empty"):
            kw.run_causal_discrimination_test(scenario="  ", expected="correlation")

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_prompt_includes_scenario_and_question(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = "Correlation"
        mock_grade = MagicMock()
        mock_grade.score = 1.0
        mock_grade.reason = "ok"
        kw.grader.grade.return_value = mock_grade

        kw.run_causal_discrimination_test(
            scenario="Ice cream and drowning are correlated.",
            expected="correlation",
        )

        prompt_used = kw.client.generate.call_args[0][0]
        assert "Ice cream and drowning" in prompt_used
        assert "causal relationship" in prompt_used


class TestRunCounterfactualTest:
    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_passes_when_score_above_threshold(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = "Life expectancy would be significantly lower."
        mock_grade = MagicMock()
        mock_grade.score = 0.8
        mock_grade.reason = "addressed key impacts"
        kw.grader.grade.return_value = mock_grade

        result = kw.run_counterfactual_test(
            scenario="If antibiotics had never been discovered...",
            expected="significantly lower life expectancy",
        )

        assert result["score"] == 0.8
        assert result["passed"] is True

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_raises_on_empty_scenario(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        with pytest.raises(ValueError, match="scenario must not be empty"):
            kw.run_counterfactual_test(scenario="", expected="some outcome")


class TestRunInterventionTest:
    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_passes_when_score_above_threshold(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = (
            "Yes, providing breakfast is a reasonable intervention "
            "with good mechanistic evidence."
        )
        mock_grade = MagicMock()
        mock_grade.score = 0.9
        mock_grade.reason = "valid intervention reasoning"
        kw.grader.grade.return_value = mock_grade

        result = kw.run_intervention_test(
            scenario="Students who eat breakfast perform better academically.",
            expected="reasonable intervention with mechanistic support",
        )

        assert result["passed"] is True

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_raises_on_empty_scenario(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        with pytest.raises(ValueError, match="scenario must not be empty"):
            kw.run_intervention_test(scenario="   ", expected="some expectation")
