"""Tests for rfc.causal_reasoning_keywords.CausalReasoningKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.causal_reasoning_keywords import (
    CausalReasoningKeywords,
    _extract_letter,
    _extract_verdict,
)


# ---------------------------------------------------------------------------
# Private helper tests
# ---------------------------------------------------------------------------


class TestExtractVerdict:
    def test_causal_on_first_line(self) -> None:
        assert _extract_verdict("CAUSAL\nBecause X directly causes Y.") == "CAUSAL"

    def test_not_causal_on_first_line(self) -> None:
        assert (
            _extract_verdict("NOT_CAUSAL\nThis is a spurious correlation.")
            == "NOT_CAUSAL"
        )

    def test_case_insensitive_causal(self) -> None:
        assert _extract_verdict("causal\nexplanation") == "CAUSAL"

    def test_case_insensitive_not_causal(self) -> None:
        assert _extract_verdict("not_causal\nexplanation") == "NOT_CAUSAL"

    def test_not_causal_space_variant(self) -> None:
        assert _extract_verdict("not causal\nexplanation") == "NOT_CAUSAL"

    def test_not_causal_hyphen_variant(self) -> None:
        # Regression: NOT-CAUSAL (hyphen) must not match bare CAUSAL
        assert (
            _extract_verdict("NOT-CAUSAL\nThis is a spurious correlation.")
            == "NOT_CAUSAL"
        )

    def test_not_causal_hyphen_lowercase(self) -> None:
        assert _extract_verdict("not-causal\nexplanation") == "NOT_CAUSAL"

    def test_leading_blank_lines_stripped_before_first_line_search(self) -> None:
        # strip() removes leading newlines, so the verdict on the first real line is found
        assert _extract_verdict("\n\nNOT_CAUSAL — spurious.") == "NOT_CAUSAL"

    def test_returns_none_when_no_verdict(self) -> None:
        assert _extract_verdict("I am not sure about this.") is None

    def test_empty_response_returns_none(self) -> None:
        assert _extract_verdict("") is None

    def test_body_only_verdict_returns_none(self) -> None:
        # Regression: explanatory prose like "there is no causal link" in the body
        # must NOT be treated as a structured verdict — first line has no verdict token.
        assert (
            _extract_verdict("Let me explain my reasoning.\nThere is no causal link.")
            is None
        )

    def test_causal_adjective_in_first_line_prose_returns_none(self) -> None:
        # "causal" used as an adjective mid-sentence should not produce a CAUSAL verdict
        assert (
            _extract_verdict("There is no causal relationship between these variables.")
            is None
        )


class TestExtractLetter:
    def test_letter_a(self) -> None:
        assert _extract_letter("A) Post hoc fallacy") == "A"

    def test_letter_b(self) -> None:
        assert _extract_letter("B\nBecause there is a confounding variable.") == "B"

    def test_letter_c_with_paren(self) -> None:
        assert _extract_letter("C) Reverse causation applies here.") == "C"

    def test_letter_d(self) -> None:
        assert _extract_letter("D) No fallacy.") == "D"

    def test_lowercase_converted(self) -> None:
        assert _extract_letter("b) confounding variable") == "B"

    def test_returns_none_when_no_letter(self) -> None:
        assert _extract_letter("The answer is somewhere in here.") is None

    def test_ignores_letter_mid_line(self) -> None:
        # Letter must be at start of a line
        result = _extract_letter("The answer is A) definitely this one")
        assert result is None

    def test_free_text_first_line_does_not_pick_up_restated_option(self) -> None:
        # Regression: first line "I choose B" should not be beaten by "A)" on line 2
        response = "I choose B\nA) Post hoc ergo propter hoc\nB) Confounding variable"
        assert _extract_letter(response) is None

    def test_only_first_line_is_searched(self) -> None:
        # Letter D appears only on line 2 — should not be returned
        response = "My answer is based on context.\nD) No fallacy here."
        assert _extract_letter(response) is None


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestCausalReasoningKeywordsInit:
    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_default_init(self, MockGrader: MagicMock, mock_create: MagicMock) -> None:
        CausalReasoningKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)
        MockGrader.assert_called_once_with(mock_create.return_value)

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_custom_timeout(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        CausalReasoningKeywords(timeout=30, max_retries=1)
        mock_create.assert_called_once_with(timeout=30, max_retries=1)


# ---------------------------------------------------------------------------
# Evaluate Causal Claim
# ---------------------------------------------------------------------------


class TestEvaluateCausalClaim:
    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_correct_not_causal_verdict(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = (
            "NOT_CAUSAL\nBoth ice cream sales and drowning are driven by hot weather."
        )
        result = kw.evaluate_causal_claim(
            scenario="Ice cream sales and drowning rates both rise in summer.",
            claim="Eating ice cream causes drowning.",
            expected_verdict="NOT_CAUSAL",
        )
        assert result["verdict"] == "NOT_CAUSAL"
        assert result["correct"] is True
        assert result["expected"] == "NOT_CAUSAL"

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_correct_causal_verdict(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = (
            "CAUSAL\nLong-term smoking causes lung cancer via carcinogen exposure."
        )
        result = kw.evaluate_causal_claim(
            scenario="Heavy smokers have much higher rates of lung cancer.",
            claim="Smoking causes lung cancer.",
            expected_verdict="CAUSAL",
        )
        assert result["verdict"] == "CAUSAL"
        assert result["correct"] is True

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_wrong_verdict_marks_incorrect(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = (
            "CAUSAL\nIce cream definitely causes drowning."
        )
        result = kw.evaluate_causal_claim(
            scenario="Ice cream sales and drowning rates both rise in summer.",
            claim="Eating ice cream causes drowning.",
            expected_verdict="NOT_CAUSAL",
        )
        assert result["verdict"] == "CAUSAL"
        assert result["correct"] is False

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_invalid_expected_verdict_raises(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        with pytest.raises(ValueError, match="expected_verdict must be one of"):
            kw.evaluate_causal_claim(
                scenario="Some scenario.",
                claim="Some claim.",
                expected_verdict="MAYBE",
            )

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_unrecognised_llm_response_verdict_is_none(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = "I cannot determine the answer."
        result = kw.evaluate_causal_claim(
            scenario="Some scenario.",
            claim="Some claim.",
            expected_verdict="CAUSAL",
        )
        assert result["verdict"] is None
        assert result["correct"] is False


# ---------------------------------------------------------------------------
# Check Fallacy Detection
# ---------------------------------------------------------------------------


class TestCheckFallacyDetection:
    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_correct_post_hoc_detection(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = (
            "A) This is post hoc ergo propter hoc — rain doesn't care about car washes."
        )
        result = kw.check_fallacy_detection(
            argument="Every time I wash my car it rains, so washing my car causes rain.",
            expected_letter="A",
        )
        assert result["chosen_letter"] == "A"
        assert result["correct"] is True

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_wrong_letter_marks_incorrect(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = "C) Reverse causation."
        result = kw.check_fallacy_detection(
            argument="Cities with more police have more crime, so police cause crime.",
            expected_letter="B",
        )
        assert result["chosen_letter"] == "C"
        assert result["correct"] is False

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_invalid_expected_letter_raises(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        with pytest.raises(ValueError, match="expected_letter must be A"):
            kw.check_fallacy_detection(
                argument="Some argument.",
                expected_letter="E",
            )

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_unrecognised_response_letter_is_none(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = "The fallacy here is post hoc reasoning."
        result = kw.check_fallacy_detection(
            argument="Some argument.",
            expected_letter="A",
        )
        assert result["chosen_letter"] is None
        assert result["correct"] is False


# ---------------------------------------------------------------------------
# Grade Counterfactual
# ---------------------------------------------------------------------------


class TestGradeCounterfactual:
    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_passing_counterfactual(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = (
            "Without the Internet, information would spread via print, radio, and TV. "
            "Global communication would be far slower, academic research would rely on "
            "physical libraries, and commerce would be largely local."
        )
        mock_grade = MagicMock()
        mock_grade.score = 0.85
        mock_grade.reason = "Covers slower communication and research impact"
        kw.grader.grade.return_value = mock_grade

        result = kw.grade_counterfactual(
            question="If the Internet had never been invented, how would information spread today?",
            expected_elements="slower communication, physical media, limited global reach",
            min_score=0.5,
        )
        assert result["score"] == 0.85
        assert result["passed"] is True

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_failing_counterfactual(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = "Things would be the same."
        mock_grade = MagicMock()
        mock_grade.score = 0.1
        mock_grade.reason = "Answer lacks any reasoning about alternate world"
        kw.grader.grade.return_value = mock_grade

        result = kw.grade_counterfactual(
            question="If the Internet had never been invented, how would information spread today?",
            expected_elements="slower communication, physical media, limited global reach",
            min_score=0.5,
        )
        assert result["score"] == 0.1
        assert result["passed"] is False

    @patch("rfc.causal_reasoning_keywords.create_provider")
    @patch("rfc.causal_reasoning_keywords.Grader")
    def test_grader_receives_question_and_elements(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = CausalReasoningKeywords()
        kw.client.generate.return_value = "Some counterfactual response."
        mock_grade = MagicMock()
        mock_grade.score = 0.7
        mock_grade.reason = "ok"
        kw.grader.grade.return_value = mock_grade

        kw.grade_counterfactual(
            question="If Newton had not published Principia, would calculus exist?",
            expected_elements="Leibniz developed calculus independently",
        )
        call_args = kw.grader.grade.call_args[0]
        assert "Newton" in call_args[0]
        assert "Leibniz" in call_args[1]
        assert "Some counterfactual response." in call_args[2]
