"""Tests for rfc.temporal_reasoning_keywords.TemporalReasoningKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.temporal_reasoning_keywords import (
    TemporalReasoningKeywords,
    _contains_number,
    _contains_word,
    _position_of,
)


# ---------------------------------------------------------------------------
# Private helper tests
# ---------------------------------------------------------------------------


class TestContainsNumber:
    def test_exact_integer_match(self) -> None:
        assert _contains_number("The answer is 42 days.", 42) is True

    def test_number_at_start(self) -> None:
        assert _contains_number("31 days later.", 31) is True

    def test_number_embedded_in_word_no_match(self) -> None:
        # "142" should not match "42"
        assert _contains_number("There are 142 items.", 42) is False

    def test_number_with_punctuation(self) -> None:
        assert _contains_number("Answer: 7.", 7) is True

    def test_number_not_present(self) -> None:
        assert _contains_number("No numbers here.", 59) is False

    def test_zero(self) -> None:
        assert _contains_number("Zero: 0 days.", 0) is True


class TestContainsWord:
    def test_exact_match(self) -> None:
        assert _contains_word("The month is March.", "March") is True

    def test_case_insensitive(self) -> None:
        assert _contains_word("The month is march.", "March") is True

    def test_word_boundary(self) -> None:
        # "February" should not match inside "Februarys" (unlikely, but guard)
        assert _contains_word("It is February.", "February") is True

    def test_word_not_present(self) -> None:
        assert _contains_word("It is January.", "March") is False

    def test_empty_response(self) -> None:
        assert _contains_word("", "March") is False


class TestPositionOf:
    def test_word_found(self) -> None:
        assert _position_of("March comes before June.", "March") == 0

    def test_second_word_found(self) -> None:
        pos = _position_of("First January then July.", "July")
        assert pos > 0

    def test_word_not_found_returns_minus_one(self) -> None:
        assert _position_of("No match here.", "March") == -1

    def test_case_insensitive(self) -> None:
        assert _position_of("the month is march.", "March") >= 0


# ---------------------------------------------------------------------------
# TemporalReasoningKeywords — unit tests with mocked LLM
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock()
    client.generate.return_value = "mocked response"
    return client


@pytest.fixture
def keywords(mock_client: MagicMock) -> TemporalReasoningKeywords:
    kw = TemporalReasoningKeywords.__new__(TemporalReasoningKeywords)
    kw.client = mock_client
    return kw


class TestCheckCalendarAnswer:
    def test_correct_month_and_day_passes(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        mock_client.generate.return_value = "The date is March 31."
        result = keywords.check_calendar_answer(
            "What date is 30 days after March 1?", "March", "31"
        )
        assert result["correct"] is True
        assert result["expected_month"] == "March"
        assert result["expected_day"] == "31"

    def test_wrong_month_fails(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        mock_client.generate.return_value = "April 15."
        result = keywords.check_calendar_answer(
            "What date is 30 days after March 1?", "March", "31"
        )
        assert result["correct"] is False

    def test_wrong_day_fails(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        mock_client.generate.return_value = "March 30."
        result = keywords.check_calendar_answer(
            "What date is 30 days after March 1?", "March", "31"
        )
        assert result["correct"] is False

    def test_response_stored(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        mock_client.generate.return_value = "March 31."
        result = keywords.check_calendar_answer("Q?", "March", "31")
        assert result["response"] == "March 31."

    def test_case_insensitive_month(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        mock_client.generate.return_value = "march 31st"
        result = keywords.check_calendar_answer("Q?", "March", "31")
        assert result["correct"] is True


class TestCheckDurationAnswer:
    def test_correct_count_passes(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        mock_client.generate.return_value = "There are 59 days between them."
        result = keywords.check_duration_answer(
            "How many days from Jan 1 to Mar 1?", 59
        )
        assert result["correct"] is True
        assert result["expected_count"] == 59

    def test_wrong_count_fails(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        mock_client.generate.return_value = "It is 60 days."
        result = keywords.check_duration_answer("Q?", 59)
        assert result["correct"] is False

    def test_embedded_number_no_false_positive(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        # "159" should NOT match expected 59
        mock_client.generate.return_value = "There are 159 total items."
        result = keywords.check_duration_answer("Q?", 59)
        assert result["correct"] is False

    def test_response_stored(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        mock_client.generate.return_value = "7 days."
        result = keywords.check_duration_answer("Q?", 7)
        assert result["response"] == "7 days."


class TestCheckSequenceOrder:
    def test_correct_order_passes(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        mock_client.generate.return_value = (
            "Chronological order: February, April, July, November."
        )
        result = keywords.check_sequence_order(
            "Order these months chronologically.",
            anchor_first="February",
            anchor_last="November",
        )
        assert result["correct"] is True

    def test_reversed_order_fails(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        mock_client.generate.return_value = (
            "November comes before February in reverse order."
        )
        result = keywords.check_sequence_order(
            "Order these months chronologically.",
            anchor_first="February",
            anchor_last="November",
        )
        assert result["correct"] is False

    def test_anchor_first_missing_fails(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        mock_client.generate.return_value = "July, November."
        result = keywords.check_sequence_order(
            "Order months.", anchor_first="February", anchor_last="November"
        )
        assert result["correct"] is False

    def test_anchor_last_missing_fails(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        mock_client.generate.return_value = "February, July."
        result = keywords.check_sequence_order(
            "Order months.", anchor_first="February", anchor_last="November"
        )
        assert result["correct"] is False

    def test_case_insensitive_matching(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        mock_client.generate.return_value = "february ... november"
        result = keywords.check_sequence_order(
            "Order months.", anchor_first="February", anchor_last="November"
        )
        assert result["correct"] is True

    def test_response_stored(
        self, keywords: TemporalReasoningKeywords, mock_client: MagicMock
    ) -> None:
        mock_client.generate.return_value = "February, November."
        result = keywords.check_sequence_order("Q?", "February", "November")
        assert result["response"] == "February, November."


# ---------------------------------------------------------------------------
# Constructor: create_provider is called
# ---------------------------------------------------------------------------


def test_constructor_calls_create_provider() -> None:
    with patch("rfc.temporal_reasoning_keywords.create_provider") as mock_cp:
        mock_cp.return_value = MagicMock()
        kw = TemporalReasoningKeywords()
        mock_cp.assert_called_once()
        assert kw.client is mock_cp.return_value
