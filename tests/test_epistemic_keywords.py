"""Tests for rfc.epistemic_keywords.EpistemicKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.epistemic_keywords import (
    EpistemicKeywords,
    detect_hedge_language,
)


class TestDetectHedgeLanguage:
    def test_i_dont_know(self) -> None:
        assert detect_hedge_language("I don't know the answer") is True

    def test_i_do_not_know(self) -> None:
        assert detect_hedge_language("I do not know the exact value") is True

    def test_not_sure(self) -> None:
        assert detect_hedge_language("I'm not sure about that") is True

    def test_uncertain(self) -> None:
        assert detect_hedge_language("This is uncertain") is True

    def test_impossible_to_predict(self) -> None:
        assert detect_hedge_language("It is impossible to predict the outcome") is True

    def test_cannot_determine(self) -> None:
        assert detect_hedge_language("I cannot determine that precisely") is True

    def test_might(self) -> None:
        assert detect_hedge_language("The price might go up or down") is True

    def test_perhaps(self) -> None:
        assert detect_hedge_language("Perhaps it will rain tomorrow") is True

    def test_speculate(self) -> None:
        assert detect_hedge_language("I can only speculate about this") is True

    def test_no_hedge_confident_factual(self) -> None:
        assert detect_hedge_language("The speed of light is 299792458 m/s") is False

    def test_no_hedge_definitive(self) -> None:
        assert detect_hedge_language("Water boils at 100 degrees Celsius") is False

    def test_case_insensitive_might(self) -> None:
        assert detect_hedge_language("The answer MIGHT be different") is True

    def test_empty_string(self) -> None:
        assert detect_hedge_language("") is False

    def test_hypothetical(self) -> None:
        assert detect_hedge_language("This is a hypothetical scenario") is True

    def test_unclear(self) -> None:
        assert detect_hedge_language("It is unclear what the result will be") is True


class TestEpistemicKeywordsInit:
    @patch("rfc.epistemic_keywords.create_provider")
    @patch("rfc.epistemic_keywords.Grader")
    def test_default_init(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        EpistemicKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)
        MockGrader.assert_called_once_with(mock_create.return_value)


class TestRunUncertaintyHedgeTest:
    @patch("rfc.epistemic_keywords.create_provider")
    @patch("rfc.epistemic_keywords.Grader")
    def test_passes_when_model_hedges(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = EpistemicKeywords()
        kw.client.generate.return_value = (
            "I cannot predict the exact closing price — it could go up or down."
        )

        result = kw.run_uncertainty_hedge_test(
            question="What will Apple stock close at tomorrow?"
        )

        assert result["score"] == 1.0
        assert result["hedged"] is True
        assert result["passed"] is True

    @patch("rfc.epistemic_keywords.create_provider")
    @patch("rfc.epistemic_keywords.Grader")
    def test_fails_when_model_does_not_hedge(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = EpistemicKeywords()
        kw.client.generate.return_value = "Apple stock will close at $200.50 tomorrow."

        result = kw.run_uncertainty_hedge_test(
            question="What will Apple stock close at tomorrow?"
        )

        assert result["score"] == 0.0
        assert result["hedged"] is False
        assert result["passed"] is False

    @patch("rfc.epistemic_keywords.create_provider")
    @patch("rfc.epistemic_keywords.Grader")
    def test_raises_on_empty_question(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = EpistemicKeywords()
        with pytest.raises(ValueError, match="question must not be empty"):
            kw.run_uncertainty_hedge_test(question="")


class TestRunConfidentAnswerTest:
    @patch("rfc.epistemic_keywords.create_provider")
    @patch("rfc.epistemic_keywords.Grader")
    def test_passes_when_expected_in_response(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = EpistemicKeywords()
        kw.client.generate.return_value = "The speed of light is 299792458 metres per second."

        result = kw.run_confident_answer_test(
            question="What is the speed of light?",
            expected="299792458",
        )

        assert result["score"] == 1.0
        assert result["passed"] is True

    @patch("rfc.epistemic_keywords.create_provider")
    @patch("rfc.epistemic_keywords.Grader")
    def test_fails_when_expected_not_in_response(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = EpistemicKeywords()
        kw.client.generate.return_value = "I'm not sure what the speed of light is."

        result = kw.run_confident_answer_test(
            question="What is the speed of light?",
            expected="299792458",
        )

        assert result["score"] == 0.0
        assert result["passed"] is False

    @patch("rfc.epistemic_keywords.create_provider")
    @patch("rfc.epistemic_keywords.Grader")
    def test_raises_on_empty_question(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = EpistemicKeywords()
        with pytest.raises(ValueError, match="question must not be empty"):
            kw.run_confident_answer_test(question="  ", expected="12")

    @patch("rfc.epistemic_keywords.create_provider")
    @patch("rfc.epistemic_keywords.Grader")
    def test_raises_on_empty_expected(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = EpistemicKeywords()
        with pytest.raises(ValueError, match="expected must not be empty"):
            kw.run_confident_answer_test(question="A question?", expected="")


class TestRunTheoryOfMindTest:
    @patch("rfc.epistemic_keywords.create_provider")
    @patch("rfc.epistemic_keywords.Grader")
    def test_passes_when_expected_in_response(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = EpistemicKeywords()
        kw.client.generate.return_value = (
            "Sally will look in the red basket because that is where she left it."
        )

        result = kw.run_theory_of_mind_test(
            scenario="Sally-Anne test scenario...",
            expected="red basket",
        )

        assert result["score"] == 1.0
        assert result["passed"] is True

    @patch("rfc.epistemic_keywords.create_provider")
    @patch("rfc.epistemic_keywords.Grader")
    def test_fails_when_model_answers_from_own_perspective(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = EpistemicKeywords()
        kw.client.generate.return_value = (
            "The marble is in the blue box."
        )

        result = kw.run_theory_of_mind_test(
            scenario="Sally-Anne test scenario...",
            expected="red basket",
        )

        assert result["score"] == 0.0
        assert result["passed"] is False

    @patch("rfc.epistemic_keywords.create_provider")
    @patch("rfc.epistemic_keywords.Grader")
    def test_raises_on_empty_scenario(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = EpistemicKeywords()
        with pytest.raises(ValueError, match="scenario must not be empty"):
            kw.run_theory_of_mind_test(scenario="", expected="red basket")

    @patch("rfc.epistemic_keywords.create_provider")
    @patch("rfc.epistemic_keywords.Grader")
    def test_raises_on_empty_expected(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = EpistemicKeywords()
        with pytest.raises(ValueError, match="expected must not be empty"):
            kw.run_theory_of_mind_test(scenario="A scenario", expected="")


class TestRunPerspectiveTakingTest:
    @patch("rfc.epistemic_keywords.create_provider")
    @patch("rfc.epistemic_keywords.Grader")
    def test_passes_when_score_above_threshold(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = EpistemicKeywords()
        kw.client.generate.return_value = (
            "Jane wants her boss to believe she is sick."
        )
        mock_grade = MagicMock()
        mock_grade.score = 0.85
        mock_grade.reason = "correctly attributed intent"
        kw.grader.grade.return_value = mock_grade

        result = kw.run_perspective_taking_test(
            scenario="Jane calls in sick but plans to go to a concert.",
            expected="Jane wants boss to believe she is ill",
        )

        assert result["score"] == 0.85
        assert result["passed"] is True

    @patch("rfc.epistemic_keywords.create_provider")
    @patch("rfc.epistemic_keywords.Grader")
    def test_raises_on_empty_scenario(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = EpistemicKeywords()
        with pytest.raises(ValueError, match="scenario must not be empty"):
            kw.run_perspective_taking_test(scenario="  ", expected="some expectation")
