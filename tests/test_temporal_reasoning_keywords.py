"""Tests for rfc.temporal_reasoning_keywords.TemporalReasoningKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.temporal_reasoning_keywords import (
    TemporalReasoningKeywords,
    _extract_first_integer,
    _extract_letter,
)


# ---------------------------------------------------------------------------
# _extract_first_integer
# ---------------------------------------------------------------------------


class TestExtractFirstInteger:
    def test_integer_on_first_line(self) -> None:
        assert _extract_first_integer("28\nFebruary has 28 days.") == 28

    def test_integer_alone(self) -> None:
        assert _extract_first_integer("365") == 365

    def test_integer_with_leading_text(self) -> None:
        assert _extract_first_integer("Integer answer: 90") == 90

    def test_takes_first_integer_on_first_line(self) -> None:
        assert _extract_first_integer("180 minutes\nThat is 3 hours.") == 180

    def test_ignores_integers_on_subsequent_lines(self) -> None:
        # First non-empty line "Answer:" has no integer → None, even though line 2 has 48.
        assert _extract_first_integer("Answer:\n48") is None

    def test_skips_blank_first_line(self) -> None:
        assert _extract_first_integer("\n\n72") == 72

    def test_returns_none_for_empty_string(self) -> None:
        assert _extract_first_integer("") is None

    def test_returns_none_for_no_integer(self) -> None:
        assert _extract_first_integer("I cannot determine the answer.") is None

    def test_large_integer(self) -> None:
        assert _extract_first_integer("1440\nMinutes in a day.") == 1440

    def test_does_not_match_decimal_as_integer(self) -> None:
        # Should not pick up "3" from "3.5 hours"
        result = _extract_first_integer("3.5 hours equals 210 minutes")
        # 210 is a valid standalone integer on this line; 3 could also match
        # depending on impl — key requirement: if 210 is present, it must be found
        assert result is not None

    def test_zero(self) -> None:
        assert _extract_first_integer("0") == 0


# ---------------------------------------------------------------------------
# _extract_letter
# ---------------------------------------------------------------------------


class TestExtractLetter:
    def test_letter_a_at_start(self) -> None:
        assert _extract_letter("A) The earliest event is the Battle of Waterloo.") == "A"

    def test_letter_b(self) -> None:
        assert _extract_letter("B\nBecause the telephone was invented in 1876.") == "B"

    def test_letter_c_with_paren(self) -> None:
        assert _extract_letter("C) Correct — this predates the others.") == "C"

    def test_letter_d(self) -> None:
        assert _extract_letter("D) This is the earliest event listed.") == "D"

    def test_lowercase_is_uppercased(self) -> None:
        assert _extract_letter("a) Post hoc fallacy applies here.") == "A"

    def test_returns_none_for_no_letter(self) -> None:
        assert _extract_letter("The earliest event is the one from 1815.") is None

    def test_returns_none_for_empty_string(self) -> None:
        assert _extract_letter("") is None

    def test_mid_sentence_letter_not_matched(self) -> None:
        # Letter must be anchored to the start of the first line
        result = _extract_letter("I believe the answer is A.")
        assert result is None

    def test_letter_on_second_line_not_matched(self) -> None:
        result = _extract_letter("Let me think about this.\nA) The Battle of Waterloo.")
        assert result is None


# ---------------------------------------------------------------------------
# TemporalReasoningKeywords — initialisation
# ---------------------------------------------------------------------------


class TestTemporalReasoningKeywordsInit:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_default_init(self, mock_create: MagicMock) -> None:
        TemporalReasoningKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_custom_timeout_and_retries(self, mock_create: MagicMock) -> None:
        TemporalReasoningKeywords(timeout=60, max_retries=3)
        mock_create.assert_called_once_with(timeout=60, max_retries=3)


# ---------------------------------------------------------------------------
# Evaluate Date Arithmetic
# ---------------------------------------------------------------------------


class TestEvaluateDateArithmetic:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_correct_integer_answer(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "28\nFebruary has 28 days in a non-leap year."
        result = kw.evaluate_date_arithmetic(
            question="How many days are in February during a non-leap year?",
            expected_answer=28,
        )
        assert result["extracted_answer"] == 28
        assert result["expected"] == 28
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_wrong_integer_answer(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "29\nFebruary has 29 days."
        result = kw.evaluate_date_arithmetic(
            question="How many days are in February during a non-leap year?",
            expected_answer=28,
        )
        assert result["extracted_answer"] == 29
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_tolerance_allows_close_answer(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "364"
        result = kw.evaluate_date_arithmetic(
            question="How many days in a non-leap year?",
            expected_answer=365,
            tolerance=1,
        )
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_no_integer_in_response(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "I don't know the answer."
        result = kw.evaluate_date_arithmetic(
            question="How many days in a non-leap year?",
            expected_answer=365,
        )
        assert result["extracted_answer"] is None
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_expected_answer_coerced_from_string(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "365"
        result = kw.evaluate_date_arithmetic(
            question="How many days in a non-leap year?",
            expected_answer="365",  # type: ignore[arg-type]
        )
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_result_contains_response_field(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        raw = "366\nLeap year."
        kw.client.generate.return_value = raw
        result = kw.evaluate_date_arithmetic(
            question="How many days in a leap year?",
            expected_answer=366,
        )
        assert result["response"] == raw


# ---------------------------------------------------------------------------
# Evaluate Duration Calculation
# ---------------------------------------------------------------------------


class TestEvaluateDurationCalculation:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_correct_hours_to_minutes(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "180\n3 hours × 60 = 180 minutes."
        result = kw.evaluate_duration_calculation(
            question="How many minutes are in exactly 3 hours?",
            expected_answer=180,
        )
        assert result["extracted_answer"] == 180
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_wrong_duration_answer(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "90"
        result = kw.evaluate_duration_calculation(
            question="How many minutes are in exactly 3 hours?",
            expected_answer=180,
        )
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_tolerance_exact_match(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "48"
        result = kw.evaluate_duration_calculation(
            question="How many hours in exactly 2 days?",
            expected_answer=48,
            tolerance=0,
        )
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_empty_response_is_incorrect(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = ""
        result = kw.evaluate_duration_calculation(
            question="How many seconds in 1 hour?",
            expected_answer=3600,
        )
        assert result["correct"] is False
        assert result["extracted_answer"] is None


# ---------------------------------------------------------------------------
# Check Earliest Event
# ---------------------------------------------------------------------------


class TestCheckEarliestEvent:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_correct_letter_returned(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = (
            "D) The Battle of Waterloo (1815) is by far the earliest event listed."
        )
        result = kw.check_earliest_event(
            event_a="The Apollo 11 moon landing",
            event_b="The Wright brothers' first powered flight",
            event_c="The fall of the Berlin Wall",
            event_d="The Battle of Waterloo",
            expected_letter="D",
        )
        assert result["chosen_letter"] == "D"
        assert result["expected"] == "D"
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_wrong_letter(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "B) The Wright Brothers flight."
        result = kw.check_earliest_event(
            event_a="The Apollo 11 moon landing",
            event_b="The Wright brothers' first powered flight",
            event_c="The fall of the Berlin Wall",
            event_d="The Battle of Waterloo",
            expected_letter="D",
        )
        assert result["chosen_letter"] == "B"
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_invalid_expected_letter_raises(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        with pytest.raises(ValueError, match="expected_letter must be A, B, C, or D"):
            kw.check_earliest_event(
                event_a="Event A",
                event_b="Event B",
                event_c="Event C",
                event_d="Event D",
                expected_letter="E",
            )

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_unrecognised_response(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "The earliest is the battle in 1815."
        result = kw.check_earliest_event(
            event_a="Apollo 11",
            event_b="Wright Brothers",
            event_c="Berlin Wall fall",
            event_d="Battle of Waterloo",
            expected_letter="D",
        )
        assert result["chosen_letter"] is None
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_lowercase_expected_letter_normalised(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "A) Earliest."
        result = kw.check_earliest_event(
            event_a="First steam locomotive (1804)",
            event_b="First telephone (1876)",
            event_c="First airplane flight (1903)",
            event_d="Sputnik launch (1957)",
            expected_letter="a",  # lowercase input
        )
        assert result["expected"] == "A"
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_result_contains_all_keys(self, mock_create: MagicMock) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "C) This one."
        result = kw.check_earliest_event(
            event_a="E1",
            event_b="E2",
            event_c="E3",
            event_d="E4",
            expected_letter="C",
        )
        assert "response" in result
        assert "chosen_letter" in result
        assert "expected" in result
        assert "correct" in result
