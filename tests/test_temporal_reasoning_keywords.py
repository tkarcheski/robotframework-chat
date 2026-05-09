"""Tests for rfc.temporal_reasoning_keywords.TemporalReasoningKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.temporal_reasoning_keywords import (
    TemporalReasoningKeywords,
    _extract_choice_letter,
    _extract_first_integer,
)


# ---------------------------------------------------------------------------
# _extract_first_integer
# ---------------------------------------------------------------------------


class TestExtractFirstInteger:
    def test_plain_integer(self) -> None:
        assert _extract_first_integer("3600") == 3600

    def test_integer_with_trailing_text(self) -> None:
        assert _extract_first_integer("3600 seconds") == 3600

    def test_integer_embedded_in_sentence(self) -> None:
        assert _extract_first_integer("The answer is 168 hours.") == 168

    def test_first_integer_wins(self) -> None:
        assert _extract_first_integer("1440 minutes, not 24 hours") == 1440

    def test_none_on_empty(self) -> None:
        assert _extract_first_integer("") is None

    def test_none_when_no_digits(self) -> None:
        assert _extract_first_integer("no numbers here") is None

    def test_large_number(self) -> None:
        assert _extract_first_integer("86400") == 86400

    def test_number_in_prose(self) -> None:
        assert _extract_first_integer("There are 60 seconds in a minute.") == 60

    def test_comma_thousands_separator(self) -> None:
        assert _extract_first_integer("3,600 seconds") == 3600

    def test_comma_separator_large(self) -> None:
        assert _extract_first_integer("86,400 seconds in a day") == 86400

    def test_single_digit(self) -> None:
        assert _extract_first_integer("7") == 7

    def test_none_when_response_is_none_string(self) -> None:
        assert _extract_first_integer("") is None


# ---------------------------------------------------------------------------
# _extract_choice_letter
# ---------------------------------------------------------------------------


class TestExtractChoiceLetter:
    def test_letter_a_bare(self) -> None:
        assert _extract_choice_letter("A\nWWI came before WWII.") == "A"

    def test_letter_b_bare(self) -> None:
        assert _extract_choice_letter("B\nThe American Revolution was earlier.") == "B"

    def test_lowercase_a(self) -> None:
        assert _extract_choice_letter("a\nexplanation") == "A"

    def test_lowercase_b(self) -> None:
        assert _extract_choice_letter("b) It came first.") == "B"

    def test_returns_none_on_empty(self) -> None:
        assert _extract_choice_letter("") is None

    def test_returns_none_when_no_ab(self) -> None:
        assert _extract_choice_letter("The answer is somewhere here.") is None

    def test_only_first_line_checked(self) -> None:
        # A is on line 2; first line has no A or B choice letter
        result = _extract_choice_letter("The event was:\nA) WWI\nB) WWII")
        assert result is None

    def test_leading_spaces_a(self) -> None:
        assert _extract_choice_letter("  A  \nExplanation") == "A"

    def test_letter_a_with_paren(self) -> None:
        assert _extract_choice_letter("A) This event came first.") == "A"

    def test_letter_b_with_paren(self) -> None:
        assert _extract_choice_letter("B) This event was earlier.") == "B"

    def test_word_starting_with_a_does_not_match(self) -> None:
        # "About" starts with A but has no word boundary after the A before more chars
        assert _extract_choice_letter("About this question...") is None

    def test_word_starting_with_b_does_not_match(self) -> None:
        assert _extract_choice_letter("Because of the evidence...") is None

    def test_letter_a_with_period(self) -> None:
        assert _extract_choice_letter("A. The printing press came first.") == "A"


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestTemporalReasoningKeywordsInit:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_default_init(self, mock_create: MagicMock) -> None:
        TemporalReasoningKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_custom_timeout(self, mock_create: MagicMock) -> None:
        TemporalReasoningKeywords(timeout=60, max_retries=1)
        mock_create.assert_called_once_with(timeout=60, max_retries=1)

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_max_retries_coerced_to_int(self, mock_create: MagicMock) -> None:
        TemporalReasoningKeywords(max_retries="3")  # type: ignore[arg-type]
        mock_create.assert_called_once_with(timeout=5400, max_retries=3)


# ---------------------------------------------------------------------------
# Evaluate Temporal Arithmetic
# ---------------------------------------------------------------------------


class TestEvaluateTemporalArithmetic:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_correct_answer(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "3600"
        result = kw.evaluate_temporal_arithmetic(
            question="How many seconds are in one hour?",
            expected_value=3600,
        )
        assert result["extracted_value"] == 3600
        assert result["correct"] is True
        assert result["expected"] == 3600

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_wrong_answer(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "360"
        result = kw.evaluate_temporal_arithmetic(
            question="How many seconds are in one hour?",
            expected_value=3600,
        )
        assert result["extracted_value"] == 360
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_answer_embedded_in_prose(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "The answer is 1440 minutes."
        result = kw.evaluate_temporal_arithmetic(
            question="How many minutes in a day?",
            expected_value=1440,
        )
        assert result["extracted_value"] == 1440
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_comma_formatted_number(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "3,600"
        result = kw.evaluate_temporal_arithmetic(
            question="How many seconds are in one hour?",
            expected_value=3600,
        )
        assert result["extracted_value"] == 3600
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_no_number_in_response(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "I don't know the answer."
        result = kw.evaluate_temporal_arithmetic(
            question="How many seconds in an hour?",
            expected_value=3600,
        )
        assert result["extracted_value"] is None
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_string_expected_value_coerced(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "168"
        result = kw.evaluate_temporal_arithmetic(
            question="How many hours in a week?",
            expected_value="168",  # type: ignore[arg-type]
        )
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_result_dict_keys_present(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "168"
        result = kw.evaluate_temporal_arithmetic(
            question="Hours in a week?",
            expected_value=168,
        )
        assert set(result.keys()) == {
            "extracted_value",
            "correct",
            "response",
            "expected",
        }


# ---------------------------------------------------------------------------
# Evaluate Chronological Order
# ---------------------------------------------------------------------------


class TestEvaluateChronologicalOrder:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_correct_choice_a(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = (
            "A\nWWI began in 1914, before WWII started in 1939."
        )
        result = kw.evaluate_chronological_order(
            question="A) WWI (1914) B) WWII (1939). Which came first?",
            expected_letter="A",
        )
        assert result["chosen_letter"] == "A"
        assert result["correct"] is True
        assert result["expected"] == "A"

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_correct_choice_b(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = (
            "B\nThe American Revolution (1776) predates the French Revolution (1789)."
        )
        result = kw.evaluate_chronological_order(
            question="A) French Revolution (1789) B) American Revolution (1776). Which came first?",
            expected_letter="B",
        )
        assert result["chosen_letter"] == "B"
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_wrong_choice(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "B\nWrong answer."
        result = kw.evaluate_chronological_order(
            question="A) WWI (1914) B) WWII (1939). Which came first?",
            expected_letter="A",
        )
        assert result["chosen_letter"] == "B"
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_no_letter_in_response(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "It is difficult to say without more context."
        result = kw.evaluate_chronological_order(
            question="A) WWI (1914) B) WWII (1939). Which came first?",
            expected_letter="A",
        )
        assert result["chosen_letter"] is None
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_invalid_expected_letter_raises(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "C\nSomething."
        with pytest.raises(ValueError, match="expected_letter must be"):
            kw.evaluate_chronological_order(
                question="A) WWI B) WWII. Which came first?",
                expected_letter="C",
            )

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_lowercase_response(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "a\nWWI was earlier."
        result = kw.evaluate_chronological_order(
            question="A) WWI (1914) B) WWII (1939). Which came first?",
            expected_letter="A",
        )
        assert result["chosen_letter"] == "A"
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_lowercase_expected_letter_normalised(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "A\nWWI came first."
        result = kw.evaluate_chronological_order(
            question="A) WWI (1914) B) WWII (1939). Which came first?",
            expected_letter="a",
        )
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_result_dict_keys_present(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "A\nExplanation."
        result = kw.evaluate_chronological_order(
            question="A) WWI B) WWII. Which came first?",
            expected_letter="A",
        )
        assert set(result.keys()) == {
            "chosen_letter",
            "correct",
            "response",
            "expected",
        }

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_letter_with_period(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "A. The printing press (1440) came first."
        result = kw.evaluate_chronological_order(
            question="A) Printing press (1440) B) Columbus (1492). Which came first?",
            expected_letter="A",
        )
        assert result["chosen_letter"] == "A"
        assert result["correct"] is True
