"""Tests for rfc.temporal_reasoning_keywords.TemporalReasoningKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.temporal_reasoning_keywords import (
    TemporalReasoningKeywords,
    _extract_integer,
    _extract_order_verdict,
    _extract_sequence,
)


# ---------------------------------------------------------------------------
# _extract_order_verdict
# ---------------------------------------------------------------------------


class TestExtractOrderVerdict:
    def test_before_on_first_line(self) -> None:
        assert _extract_order_verdict("BEFORE\nBecause X came first.") == "BEFORE"

    def test_after_on_first_line(self) -> None:
        assert _extract_order_verdict("AFTER\nBecause Y came later.") == "AFTER"

    def test_case_insensitive_before(self) -> None:
        assert _extract_order_verdict("before\nexplanation") == "BEFORE"

    def test_case_insensitive_after(self) -> None:
        assert _extract_order_verdict("after\nexplanation") == "AFTER"

    def test_optional_label_prefix(self) -> None:
        assert _extract_order_verdict("Verdict: BEFORE\nexplanation") == "BEFORE"

    def test_leading_whitespace_stripped(self) -> None:
        assert _extract_order_verdict("  BEFORE — Event A first.\nexplanation") == "BEFORE"

    def test_returns_none_when_no_verdict(self) -> None:
        assert _extract_order_verdict("I think event A was earlier.") is None

    def test_empty_string_returns_none(self) -> None:
        assert _extract_order_verdict("") is None

    def test_verdict_mid_sentence_returns_none(self) -> None:
        # "before" in the middle of a sentence on the first line should not match
        # because _ORDER_RE is anchored to the start of the line.
        assert _extract_order_verdict("This happened before that.") is None

    def test_leading_blank_lines_ignored(self) -> None:
        assert _extract_order_verdict("\n\nBEFORE — clearly first.") == "BEFORE"


# ---------------------------------------------------------------------------
# _extract_integer
# ---------------------------------------------------------------------------


class TestExtractInteger:
    def test_plain_integer(self) -> None:
        assert _extract_integer("29\nFebruary 2024 has 29 days.") == 29

    def test_integer_with_commas(self) -> None:
        assert _extract_integer("1,000\nOne thousand days.") == 1000

    def test_integer_inline(self) -> None:
        assert _extract_integer("The answer is 34 years.") == 34

    def test_first_integer_wins(self) -> None:
        assert _extract_integer("55 years passed between 1969 and 2024.") == 55

    def test_returns_none_when_no_integer(self) -> None:
        assert _extract_integer("There are no numbers here.") is None

    def test_empty_string_returns_none(self) -> None:
        assert _extract_integer("") is None

    def test_only_checks_first_line(self) -> None:
        # Second line has the number; first line does not.
        assert _extract_integer("The answer is:\n42") is None

    def test_large_number(self) -> None:
        assert _extract_integer("8,760\nHours in a year.") == 8760


# ---------------------------------------------------------------------------
# _extract_sequence
# ---------------------------------------------------------------------------


class TestExtractSequence:
    def test_comma_separated(self) -> None:
        assert _extract_sequence("A, B, C\nexplanation") == ["A", "B", "C"]

    def test_space_separated(self) -> None:
        assert _extract_sequence("A B C\nexplanation") == ["A", "B", "C"]

    def test_comma_no_space(self) -> None:
        assert _extract_sequence("A,B,C") == ["A", "B", "C"]

    def test_case_insensitive(self) -> None:
        assert _extract_sequence("a, b, c\nexplanation") == ["A", "B", "C"]

    def test_different_order(self) -> None:
        assert _extract_sequence("C, A, B\nexplanation") == ["C", "A", "B"]

    def test_returns_none_when_no_letters(self) -> None:
        assert _extract_sequence("The order is unclear.") is None

    def test_empty_string_returns_none(self) -> None:
        assert _extract_sequence("") is None

    def test_two_letter_sequence_returns_none(self) -> None:
        # We need at least 3 letters for a valid sequence
        assert _extract_sequence("A, B") is None

    def test_label_prefix_before_sequence(self) -> None:
        assert _extract_sequence("Order: A, B, C") == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# TemporalReasoningKeywords init
# ---------------------------------------------------------------------------


class TestTemporalReasoningKeywordsInit:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_default_init(self, mock_create: MagicMock) -> None:
        TemporalReasoningKeywords()
        mock_create.assert_called_once()

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_custom_timeout(self, mock_create: MagicMock) -> None:
        TemporalReasoningKeywords(timeout=60)
        _, kwargs = mock_create.call_args
        assert kwargs.get("timeout") == 60


# ---------------------------------------------------------------------------
# evaluate_temporal_order
# ---------------------------------------------------------------------------


class TestEvaluateTemporalOrder:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def _make_kw(self, mock_create: MagicMock) -> TemporalReasoningKeywords:
        kw = TemporalReasoningKeywords()
        kw.client = MagicMock()
        return kw

    def test_correct_before_verdict(self) -> None:
        kw = self._make_kw()
        kw.client.generate.return_value = "BEFORE\nWWI ended in 1918, before WWII."
        result = kw.evaluate_temporal_order("WWI ended", "WWII began", "BEFORE")
        assert result["verdict"] == "BEFORE"
        assert result["correct"] is True

    def test_correct_after_verdict(self) -> None:
        kw = self._make_kw()
        kw.client.generate.return_value = "AFTER\nEvent A came later."
        result = kw.evaluate_temporal_order("Later event", "Earlier event", "AFTER")
        assert result["verdict"] == "AFTER"
        assert result["correct"] is True

    def test_wrong_verdict(self) -> None:
        kw = self._make_kw()
        kw.client.generate.return_value = "AFTER\nIncorrect."
        result = kw.evaluate_temporal_order("Earlier event", "Later event", "BEFORE")
        assert result["correct"] is False

    def test_no_verdict_extracted(self) -> None:
        kw = self._make_kw()
        kw.client.generate.return_value = "I am not sure which came first."
        result = kw.evaluate_temporal_order("Event A", "Event B", "BEFORE")
        assert result["verdict"] is None
        assert result["correct"] is False

    def test_invalid_expected_verdict_raises(self) -> None:
        kw = self._make_kw()
        with pytest.raises(ValueError, match="BEFORE.*AFTER"):
            kw.evaluate_temporal_order("A", "B", "SIMULTANEOUS")

    def test_result_contains_response(self) -> None:
        kw = self._make_kw()
        kw.client.generate.return_value = "BEFORE\nExplanation here."
        result = kw.evaluate_temporal_order("A", "B", "BEFORE")
        assert "BEFORE" in result["response"]


# ---------------------------------------------------------------------------
# evaluate_date_calculation
# ---------------------------------------------------------------------------


class TestEvaluateDateCalculation:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def _make_kw(self, mock_create: MagicMock) -> TemporalReasoningKeywords:
        kw = TemporalReasoningKeywords()
        kw.client = MagicMock()
        return kw

    def test_correct_answer(self) -> None:
        kw = self._make_kw()
        kw.client.generate.return_value = "29\nFebruary 2024 is a leap year."
        result = kw.evaluate_date_calculation("How many days does February 2024 have?", 29)
        assert result["calculated"] == 29
        assert result["correct"] is True

    def test_wrong_answer(self) -> None:
        kw = self._make_kw()
        kw.client.generate.return_value = "28\nFebruary has 28 days."
        result = kw.evaluate_date_calculation("How many days does February 2024 have?", 29)
        assert result["calculated"] == 28
        assert result["correct"] is False

    def test_no_integer_extracted(self) -> None:
        kw = self._make_kw()
        kw.client.generate.return_value = "I cannot determine the exact number."
        result = kw.evaluate_date_calculation("Some question", 42)
        assert result["calculated"] is None
        assert result["correct"] is False

    def test_expected_answer_coerced_to_int(self) -> None:
        kw = self._make_kw()
        kw.client.generate.return_value = "55\nExplanation."
        result = kw.evaluate_date_calculation("Years between?", "55")  # type: ignore[arg-type]
        assert result["correct"] is True


# ---------------------------------------------------------------------------
# evaluate_event_sequence
# ---------------------------------------------------------------------------


class TestEvaluateEventSequence:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def _make_kw(self, mock_create: MagicMock) -> TemporalReasoningKeywords:
        kw = TemporalReasoningKeywords()
        kw.client = MagicMock()
        return kw

    def test_correct_sequence(self) -> None:
        kw = self._make_kw()
        kw.client.generate.return_value = "A, B, C\nA was first, then B, then C."
        result = kw.evaluate_event_sequence("Event A", "Event B", "Event C", "A, B, C")
        assert result["sequence"] == ["A", "B", "C"]
        assert result["correct"] is True

    def test_wrong_sequence(self) -> None:
        kw = self._make_kw()
        kw.client.generate.return_value = "B, A, C\nIncorrect."
        result = kw.evaluate_event_sequence("Event A", "Event B", "Event C", "A, B, C")
        assert result["correct"] is False

    def test_no_sequence_extracted(self) -> None:
        kw = self._make_kw()
        kw.client.generate.return_value = "The chronological order is ambiguous."
        result = kw.evaluate_event_sequence("A", "B", "C", "A, B, C")
        assert result["sequence"] is None
        assert result["correct"] is False

    def test_invalid_expected_sequence_raises(self) -> None:
        kw = self._make_kw()
        with pytest.raises(ValueError, match="exactly 3 letters"):
            kw.evaluate_event_sequence("A", "B", "C", "A, B")

    def test_different_expected_order(self) -> None:
        kw = self._make_kw()
        kw.client.generate.return_value = "C, A, B\nC came first."
        result = kw.evaluate_event_sequence("A", "B", "C", "C, A, B")
        assert result["correct"] is True
