"""Tests for rfc.temporal_reasoning_keywords.TemporalReasoningKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.temporal_reasoning_keywords import (
    TemporalReasoningKeywords,
    _extract_integer,
    _extract_letter_sequence,
    _normalize_order,
)


# ---------------------------------------------------------------------------
# Private helper tests
# ---------------------------------------------------------------------------


class TestExtractInteger:
    def test_plain_integer_on_first_line(self) -> None:
        assert _extract_integer("67\nsome explanation") == 67

    def test_integer_with_units(self) -> None:
        assert _extract_integer("67 days\nexplanation") == 67

    def test_integer_with_label(self) -> None:
        assert _extract_integer("Answer: 365\n") == 365

    def test_integer_with_trailing_dot(self) -> None:
        assert _extract_integer("52.\nweeks") == 52

    def test_integer_in_sentence(self) -> None:
        assert _extract_integer("The answer is 92 days.") == 92

    def test_returns_none_when_empty(self) -> None:
        assert _extract_integer("") is None

    def test_returns_none_when_no_integer(self) -> None:
        assert _extract_integer("I am not sure about this.") is None

    def test_returns_none_when_only_text(self) -> None:
        assert _extract_integer("The answer would depend on context.") is None

    def test_extracts_first_small_integer_when_multiple_present(self) -> None:
        # First non-year (<1000) integer wins on lines with multiple candidates.
        assert _extract_integer("52 or 53 weeks") == 52

    def test_decimal_answer_parsed_as_int(self) -> None:
        # "365.25" must be parsed as one token (365), not two integers [365, 25].
        assert _extract_integer("365.25 days") == 365

    def test_supplementary_units_do_not_override_primary_answer(self) -> None:
        # First small value wins; "9" (months) must not shadow "40" (weeks).
        assert _extract_integer("40 weeks (9 months)") == 40

    def test_ignores_context_years_and_returns_answer(self) -> None:
        # Regression for P1: year-like numbers in prose must not shadow the
        # actual answer.  "From 1939 to 1945, it lasted 6 years" → 6.
        assert _extract_integer("From 1939 to 1945, it lasted 6 years") == 6

    def test_context_years_ignored_cold_war(self) -> None:
        # "The Cold War ran from 1947 to 1991, a span of 44 years." → 44.
        assert _extract_integer("From 1947 to 1991, a span of 44 years.") == 44

    def test_ignores_integers_on_subsequent_lines(self) -> None:
        # Only the first line is searched.
        assert _extract_integer("no number here\n67 is on line two") is None

    def test_leading_blank_lines_stripped(self) -> None:
        assert _extract_integer("\n\n59\nMore text") == 59

    def test_large_integer(self) -> None:
        assert _extract_integer("11122") == 11122

    def test_zero(self) -> None:
        assert _extract_integer("0") == 0


class TestExtractLetterSequence:
    def test_standard_format(self) -> None:
        assert _extract_letter_sequence("D, A, B, C") == ["D", "A", "B", "C"]

    def test_no_spaces(self) -> None:
        assert _extract_letter_sequence("D,A,B,C") == ["D", "A", "B", "C"]

    def test_lowercase_input(self) -> None:
        assert _extract_letter_sequence("d, a, b, c") == ["D", "A", "B", "C"]

    def test_mixed_case(self) -> None:
        assert _extract_letter_sequence("D, a, B, c") == ["D", "A", "B", "C"]

    def test_with_label_prefix(self) -> None:
        assert _extract_letter_sequence("Order: D, A, B, C") == ["D", "A", "B", "C"]

    def test_empty_response(self) -> None:
        assert _extract_letter_sequence("") == []

    def test_no_letters(self) -> None:
        assert _extract_letter_sequence("I cannot determine the order.") == []

    def test_only_first_line_used(self) -> None:
        # Letters on subsequent lines should be ignored.
        assert _extract_letter_sequence("D, A\nB, C") == ["D", "A"]

    def test_three_event_sequence(self) -> None:
        assert _extract_letter_sequence("A, C, B") == ["A", "C", "B"]

    def test_leading_blank_lines_stripped(self) -> None:
        assert _extract_letter_sequence("\n\nA, B, C, D") == ["A", "B", "C", "D"]


class TestNormalizeOrder:
    def test_standard_format(self) -> None:
        assert _normalize_order("D, A, B, C") == ["D", "A", "B", "C"]

    def test_no_spaces_format(self) -> None:
        assert _normalize_order("D,A,B,C") == ["D", "A", "B", "C"]

    def test_uppercase(self) -> None:
        assert _normalize_order("A B C D") == ["A", "B", "C", "D"]

    def test_empty_string(self) -> None:
        assert _normalize_order("") == []


# ---------------------------------------------------------------------------
# Keyword class tests — mock the LLM client
# ---------------------------------------------------------------------------


@pytest.fixture()
def keywords() -> TemporalReasoningKeywords:
    with patch("rfc.temporal_reasoning_keywords.create_provider") as mock_factory:
        mock_client = MagicMock()
        mock_factory.return_value = mock_client
        kw = TemporalReasoningKeywords(timeout=10)
        kw.client = mock_client
        return kw


class TestSolveDateArithmetic:
    def test_correct_answer_exact(self, keywords: TemporalReasoningKeywords) -> None:
        keywords.client.generate.return_value = "59\n"
        result = keywords.solve_date_arithmetic(
            "How many days are between Jan 1 and Mar 1 in a non-leap year?",
            expected=59,
        )
        assert result["correct"] is True
        assert result["answer"] == 59
        assert result["expected"] == 59

    def test_incorrect_answer(self, keywords: TemporalReasoningKeywords) -> None:
        keywords.client.generate.return_value = "60\n"
        result = keywords.solve_date_arithmetic(
            "How many days are between Jan 1 and Mar 1 in a non-leap year?",
            expected=59,
        )
        assert result["correct"] is False

    def test_tolerance_within_range(self, keywords: TemporalReasoningKeywords) -> None:
        keywords.client.generate.return_value = "53\n"
        result = keywords.solve_date_arithmetic(
            "How many complete weeks are in a year?",
            expected=52,
            tolerance=1,
        )
        assert result["correct"] is True

    def test_tolerance_outside_range(self, keywords: TemporalReasoningKeywords) -> None:
        keywords.client.generate.return_value = "50\n"
        result = keywords.solve_date_arithmetic(
            "How many complete weeks are in a year?",
            expected=52,
            tolerance=1,
        )
        assert result["correct"] is False

    def test_no_integer_in_response(self, keywords: TemporalReasoningKeywords) -> None:
        keywords.client.generate.return_value = "I cannot determine this."
        result = keywords.solve_date_arithmetic(
            "How many days in a year?",
            expected=365,
        )
        assert result["correct"] is False
        assert result["answer"] is None

    def test_answer_with_units_in_response(
        self, keywords: TemporalReasoningKeywords
    ) -> None:
        keywords.client.generate.return_value = "365 days"
        result = keywords.solve_date_arithmetic(
            "How many days in a non-leap year?",
            expected=365,
        )
        assert result["correct"] is True
        assert result["answer"] == 365

    def test_response_stored_in_result(
        self, keywords: TemporalReasoningKeywords
    ) -> None:
        keywords.client.generate.return_value = "92"
        result = keywords.solve_date_arithmetic(
            "Days between March 15 and June 15?",
            expected=92,
        )
        assert result["response"] == "92"


class TestCheckEventOrdering:
    def test_correct_order(self, keywords: TemporalReasoningKeywords) -> None:
        keywords.client.generate.return_value = "D, A, B, C\n"
        result = keywords.check_event_ordering(
            events=(
                "A) End of World War II\n"
                "B) First moon landing\n"
                "C) Fall of the Berlin Wall\n"
                "D) French Revolution begins"
            ),
            expected_order="D, A, B, C",
        )
        assert result["correct"] is True
        assert result["actual_order"] == ["D", "A", "B", "C"]
        assert result["expected_order"] == ["D", "A", "B", "C"]

    def test_incorrect_order(self, keywords: TemporalReasoningKeywords) -> None:
        keywords.client.generate.return_value = "A, B, C, D\n"
        result = keywords.check_event_ordering(
            events=(
                "A) End of World War II\n"
                "B) First moon landing\n"
                "C) Fall of the Berlin Wall\n"
                "D) French Revolution begins"
            ),
            expected_order="D, A, B, C",
        )
        assert result["correct"] is False

    def test_empty_response_is_incorrect(
        self, keywords: TemporalReasoningKeywords
    ) -> None:
        keywords.client.generate.return_value = "I cannot determine the order."
        result = keywords.check_event_ordering(
            events="A) X\nB) Y\nC) Z\nD) W",
            expected_order="A, B, C, D",
        )
        assert result["correct"] is False
        assert result["actual_order"] == []

    def test_lowercase_response_normalized(
        self, keywords: TemporalReasoningKeywords
    ) -> None:
        keywords.client.generate.return_value = "b, d, a, c"
        result = keywords.check_event_ordering(
            events="A) X\nB) Y\nC) Z\nD) W",
            expected_order="B, D, A, C",
        )
        assert result["correct"] is True


class TestEstimateDuration:
    def test_correct_duration(self, keywords: TemporalReasoningKeywords) -> None:
        keywords.client.generate.return_value = "6\n"
        result = keywords.estimate_duration(
            "How many years did World War II last?",
            expected=6,
            tolerance=1,
        )
        assert result["correct"] is True
        assert result["answer"] == 6

    def test_within_tolerance(self, keywords: TemporalReasoningKeywords) -> None:
        keywords.client.generate.return_value = "5\n"
        result = keywords.estimate_duration(
            "How many years did World War II last?",
            expected=6,
            tolerance=1,
        )
        assert result["correct"] is True

    def test_outside_tolerance(self, keywords: TemporalReasoningKeywords) -> None:
        keywords.client.generate.return_value = "4\n"
        result = keywords.estimate_duration(
            "How many years did World War II last?",
            expected=6,
            tolerance=1,
        )
        assert result["correct"] is False

    def test_no_integer_response(self, keywords: TemporalReasoningKeywords) -> None:
        keywords.client.generate.return_value = "Not enough information."
        result = keywords.estimate_duration(
            "How many months is a typical pregnancy?",
            expected=9,
        )
        assert result["correct"] is False
        assert result["answer"] is None

    def test_exact_match_no_tolerance(
        self, keywords: TemporalReasoningKeywords
    ) -> None:
        keywords.client.generate.return_value = "9"
        result = keywords.estimate_duration(
            "How many months is a typical human pregnancy?",
            expected=9,
            tolerance=0,
        )
        assert result["correct"] is True

    def test_off_by_one_with_zero_tolerance(
        self, keywords: TemporalReasoningKeywords
    ) -> None:
        keywords.client.generate.return_value = "10"
        result = keywords.estimate_duration(
            "How many months is a typical human pregnancy?",
            expected=9,
            tolerance=0,
        )
        assert result["correct"] is False
