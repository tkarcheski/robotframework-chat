"""Tests for rfc.temporal_reasoning_keywords.TemporalReasoningKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.temporal_reasoning_keywords import TemporalReasoningKeywords


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_kw(**kwargs) -> TemporalReasoningKeywords:
    """Build a TemporalReasoningKeywords with a mocked client."""
    with patch("rfc.temporal_reasoning_keywords.create_provider"):
        kw = TemporalReasoningKeywords(**kwargs)
    kw.client = MagicMock()
    return kw


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestInit:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_default_timeout(self, mock_cp: MagicMock) -> None:
        TemporalReasoningKeywords()
        mock_cp.assert_called_once_with(timeout=5400, max_retries=2)

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    def test_custom_timeout(self, mock_cp: MagicMock) -> None:
        TemporalReasoningKeywords(timeout=60, max_retries=1)
        mock_cp.assert_called_once_with(timeout=60, max_retries=1)


# ---------------------------------------------------------------------------
# _extract_number
# ---------------------------------------------------------------------------


class TestExtractNumber:
    def test_extracts_plain_integer(self) -> None:
        kw = _make_kw()
        assert kw._extract_number("The answer is 42.") == 42

    def test_extracts_first_number(self) -> None:
        kw = _make_kw()
        assert kw._extract_number("There are 31 days in January and 28 in February.") == 31

    def test_returns_none_for_no_number(self) -> None:
        kw = _make_kw()
        assert kw._extract_number("no digits here") is None


# ---------------------------------------------------------------------------
# _extract_date
# ---------------------------------------------------------------------------


class TestExtractDate:
    def test_iso_format(self) -> None:
        kw = _make_kw()
        assert kw._extract_date("The date is 2024-02-14.") == "2024-02-14"

    def test_written_month(self) -> None:
        kw = _make_kw()
        assert kw._extract_date("The answer is February 14, 2024.") == "2024-02-14"

    def test_mdy_format(self) -> None:
        kw = _make_kw()
        assert kw._extract_date("The answer is 2/14/2024.") == "2024-02-14"

    def test_returns_none_for_no_date(self) -> None:
        kw = _make_kw()
        assert kw._extract_date("no date here") is None

    def test_iso_takes_priority(self) -> None:
        kw = _make_kw()
        # Both forms present — ISO wins
        result = kw._extract_date("2024-02-14 or February 14, 2024")
        assert result == "2024-02-14"


# ---------------------------------------------------------------------------
# _extract_weekday
# ---------------------------------------------------------------------------


class TestExtractWeekday:
    def test_finds_weekday(self) -> None:
        kw = _make_kw()
        assert kw._extract_weekday("That day is a Wednesday.") == "Wednesday"

    def test_case_insensitive(self) -> None:
        kw = _make_kw()
        assert kw._extract_weekday("the answer is friday") == "Friday"

    def test_returns_none_for_no_weekday(self) -> None:
        kw = _make_kw()
        assert kw._extract_weekday("no day name here") is None


# ---------------------------------------------------------------------------
# ask_temporal_numeric_question
# ---------------------------------------------------------------------------


class TestAskTemporalNumericQuestion:
    def test_correct_answer_passes(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "There are 31 days in January."
        result = kw.ask_temporal_numeric_question(
            "How many days in January?", expected_number=31
        )
        assert result["passed"] is True
        assert result["actual_number"] == 31

    def test_wrong_answer_fails(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "I think it is 30 days."
        result = kw.ask_temporal_numeric_question(
            "How many days in January?", expected_number=31
        )
        assert result["passed"] is False
        assert result["actual_number"] == 30

    def test_no_number_in_response_fails(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "I'm not sure about that."
        result = kw.ask_temporal_numeric_question("How many days?", expected_number=31)
        assert result["passed"] is False
        assert result["actual_number"] is None

    def test_think_block_stripped(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "<think>reasoning</think>The answer is 72."
        result = kw.ask_temporal_numeric_question("Hours in 3 days?", expected_number=72)
        assert result["passed"] is True


# ---------------------------------------------------------------------------
# ask_temporal_date_question
# ---------------------------------------------------------------------------


class TestAskTemporalDateQuestion:
    def test_iso_response_passes(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "The date is 2024-02-14."
        result = kw.ask_temporal_date_question(
            "30 days after Jan 15, 2024?", expected_date="2024-02-14"
        )
        assert result["passed"] is True
        assert result["actual_date"] == "2024-02-14"

    def test_written_month_response_passes(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "The answer is February 14, 2024."
        result = kw.ask_temporal_date_question(
            "30 days after Jan 15, 2024?", expected_date="2024-02-14"
        )
        assert result["passed"] is True

    def test_wrong_date_fails(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "The date is 2024-02-15."
        result = kw.ask_temporal_date_question(
            "30 days after Jan 15, 2024?", expected_date="2024-02-14"
        )
        assert result["passed"] is False

    def test_no_date_fails(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "I cannot answer that."
        result = kw.ask_temporal_date_question("Some date?", expected_date="2024-02-14")
        assert result["passed"] is False
        assert result["actual_date"] is None


# ---------------------------------------------------------------------------
# ask_temporal_weekday_question
# ---------------------------------------------------------------------------


class TestAskTemporalWeekdayQuestion:
    def test_correct_weekday_passes(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "July 4, 2025 falls on a Friday."
        result = kw.ask_temporal_weekday_question(
            "What day of the week is July 4, 2025?", expected_weekday="Friday"
        )
        assert result["passed"] is True
        assert result["actual_weekday"] == "Friday"

    def test_wrong_weekday_fails(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "It is a Saturday."
        result = kw.ask_temporal_weekday_question(
            "What day is July 4, 2025?", expected_weekday="Friday"
        )
        assert result["passed"] is False

    def test_case_insensitive_match(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "the answer is friday"
        result = kw.ask_temporal_weekday_question(
            "What day?", expected_weekday="Friday"
        )
        assert result["passed"] is True


# ---------------------------------------------------------------------------
# assert_temporal_result_passed
# ---------------------------------------------------------------------------


class TestAssertTemporalResultPassed:
    def test_passes_when_passed_true(self) -> None:
        kw = _make_kw()
        kw.assert_temporal_result_passed({"passed": True, "reason": "ok"})

    def test_raises_when_passed_false(self) -> None:
        kw = _make_kw()
        with pytest.raises(AssertionError, match="Temporal reasoning check failed"):
            kw.assert_temporal_result_passed({"passed": False, "reason": "wrong"})


# ---------------------------------------------------------------------------
# get_temporal_results_summary
# ---------------------------------------------------------------------------


class TestGetTemporalResultsSummary:
    def test_all_passed(self) -> None:
        kw = _make_kw()
        results = [{"passed": True}, {"passed": True}, {"passed": True}]
        summary = kw.get_temporal_results_summary(results)
        assert summary["total"] == 3
        assert summary["passed"] == 3
        assert summary["failed"] == 0
        assert summary["pass_rate"] == pytest.approx(1.0)

    def test_partial_pass(self) -> None:
        kw = _make_kw()
        results = [{"passed": True}, {"passed": False}, {"passed": True}]
        summary = kw.get_temporal_results_summary(results)
        assert summary["passed"] == 2
        assert summary["failed"] == 1
        assert summary["pass_rate"] == pytest.approx(2 / 3)

    def test_empty_list(self) -> None:
        kw = _make_kw()
        summary = kw.get_temporal_results_summary([])
        assert summary["total"] == 0
        assert summary["pass_rate"] == pytest.approx(0.0)
