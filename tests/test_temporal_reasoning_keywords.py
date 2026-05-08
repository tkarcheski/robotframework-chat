"""Tests for rfc.temporal_reasoning_keywords.TemporalReasoningKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.temporal_reasoning_keywords import (
    TemporalReasoningKeywords,
    _extract_first_integer,
    _extract_letter,
    _extract_order_letters,
)


# ---------------------------------------------------------------------------
# _extract_order_letters
# ---------------------------------------------------------------------------


class TestExtractOrderLetters:
    def test_comma_separated(self) -> None:
        assert _extract_order_letters("B, D, A, C", 4) == ["B", "D", "A", "C"]

    def test_space_separated(self) -> None:
        assert _extract_order_letters("A B C D", 4) == ["A", "B", "C", "D"]

    def test_arrow_separated(self) -> None:
        assert _extract_order_letters("C → A → D → B", 4) == ["C", "A", "D", "B"]

    def test_lowercase_converted(self) -> None:
        assert _extract_order_letters("b, a, d, c", 4) == ["B", "A", "D", "C"]

    def test_mixed_case(self) -> None:
        assert _extract_order_letters("B, a, D, c", 4) == ["B", "A", "D", "C"]

    def test_returns_none_on_too_few_letters(self) -> None:
        assert _extract_order_letters("A, B, C", 4) is None

    def test_returns_none_on_duplicate_letters(self) -> None:
        # Duplicate A means only 3 unique letters
        assert _extract_order_letters("A, A, B, C", 4) is None

    def test_returns_none_on_empty(self) -> None:
        assert _extract_order_letters("", 4) is None

    def test_ignores_subsequent_lines(self) -> None:
        response = "B, D, A, C\nThis is because Darwin came before Bell..."
        assert _extract_order_letters(response, 4) == ["B", "D", "A", "C"]

    def test_leading_label_stripped(self) -> None:
        # First line starts with "Order: B, D, A, C"
        assert _extract_order_letters("Order: B, D, A, C", 4) == ["B", "D", "A", "C"]

    def test_with_n_equals_3(self) -> None:
        assert _extract_order_letters("C, A, B", 3) == ["C", "A", "B"]

    def test_extra_letters_beyond_n_returns_none(self) -> None:
        # 5 unique letters when n=4 → None (too many)
        assert _extract_order_letters("A, B, C, D, E", 4) is None

    def test_duplicate_with_correct_unique_count_leading_returns_none(self) -> None:
        # Regression (Codex P2): "A, A, B, C, D" has 4 unique letters but 5 tokens.
        # Dedup alone would wrongly accept this as a valid 4-event order.
        assert _extract_order_letters("A, A, B, C, D", 4) is None

    def test_duplicate_with_correct_unique_count_trailing_returns_none(self) -> None:
        # Regression (Codex P2): trailing duplicate "A, B, C, D, A" must also be rejected.
        assert _extract_order_letters("A, B, C, D, A", 4) is None


# ---------------------------------------------------------------------------
# _extract_first_integer
# ---------------------------------------------------------------------------


class TestExtractFirstInteger:
    def test_bare_integer(self) -> None:
        assert _extract_first_integer("59") == 59

    def test_integer_with_units(self) -> None:
        assert _extract_first_integer("59 days") == 59

    def test_integer_with_label(self) -> None:
        assert _extract_first_integer("Answer: 78") == 78

    def test_leading_zero(self) -> None:
        assert _extract_first_integer("07") == 7

    def test_returns_none_on_empty(self) -> None:
        assert _extract_first_integer("") is None

    def test_returns_none_on_no_digits(self) -> None:
        assert _extract_first_integer("no numbers here") is None

    def test_ignores_subsequent_lines(self) -> None:
        response = "13\nBecause 91 divided by 7 equals 13 weeks."
        assert _extract_first_integer(response) == 13

    def test_first_integer_in_line(self) -> None:
        # "59 days" — picks up 59, not any later number
        assert _extract_first_integer("59 days, not 60") == 59

    def test_large_number(self) -> None:
        assert _extract_first_integer("1000 hours") == 1000


# ---------------------------------------------------------------------------
# _extract_letter
# ---------------------------------------------------------------------------


class TestExtractLetter:
    def test_letter_a(self) -> None:
        assert _extract_letter("A) A then B then C") == "A"

    def test_letter_b(self) -> None:
        assert _extract_letter("B) Project B is longer") == "B"

    def test_letter_c_with_paren(self) -> None:
        assert _extract_letter("C) They are on the same day") == "C"

    def test_letter_d(self) -> None:
        assert _extract_letter("D) December") == "D"

    def test_lowercase_converted(self) -> None:
        assert _extract_letter("b) Sarah's birthday") == "B"

    def test_bare_letter(self) -> None:
        assert _extract_letter("C\nThree weeks equals 21 days...") == "C"

    def test_returns_none_on_empty(self) -> None:
        assert _extract_letter("") is None

    def test_returns_none_when_no_letter_at_start(self) -> None:
        # Letter must be at start of first line
        assert _extract_letter("The answer is C) definitely") is None

    def test_ignores_subsequent_lines(self) -> None:
        response = "A\nBecause A comes before B and C in time."
        assert _extract_letter(response) == "A"


# ---------------------------------------------------------------------------
# TemporalReasoningKeywords — init
# ---------------------------------------------------------------------------


class TestTemporalReasoningKeywordsInit:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_default_init(self, MockGrader: MagicMock, mock_create: MagicMock) -> None:
        TemporalReasoningKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)
        MockGrader.assert_called_once_with(mock_create.return_value)

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_custom_timeout(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        TemporalReasoningKeywords(timeout=60, max_retries=1)
        mock_create.assert_called_once_with(timeout=60, max_retries=1)


# ---------------------------------------------------------------------------
# Check Event Order
# ---------------------------------------------------------------------------


class TestCheckEventOrder:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_correct_order(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = (
            "B, D, A, C\nDarwin (1859) came first, then Bell (1876), Einstein (1905), Turing (1936)."
        )
        events = {
            "A": "Albert Einstein publishes Special Relativity (1905)",
            "B": "Charles Darwin publishes On the Origin of Species (1859)",
            "C": "Alan Turing describes the Turing machine (1936)",
            "D": "Alexander Graham Bell invents the telephone (1876)",
        }
        result = kw.check_event_order(events, "B D A C")
        assert result["order"] == "B D A C"
        assert result["correct"] is True
        assert result["expected"] == "B D A C"

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_wrong_order_marks_incorrect(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "A, B, C, D\nIncorrect reasoning."
        events = {
            "A": "Albert Einstein publishes Special Relativity (1905)",
            "B": "Charles Darwin publishes On the Origin of Species (1859)",
            "C": "Alan Turing describes the Turing machine (1936)",
            "D": "Alexander Graham Bell invents the telephone (1876)",
        }
        result = kw.check_event_order(events, "B D A C")
        assert result["order"] == "A B C D"
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_unrecognised_response_order_is_none(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "The events occurred in various decades."
        events = {
            "A": "Event A (1900)",
            "B": "Event B (1850)",
            "C": "Event C (1920)",
            "D": "Event D (1880)",
        }
        result = kw.check_event_order(events, "B D A C")
        assert result["order"] is None
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_expected_order_normalised(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "B, D, A, C\nExplanation."
        events = {"A": "A (1905)", "B": "B (1859)", "C": "C (1936)", "D": "D (1876)"}
        # expected_order with commas should still match
        result = kw.check_event_order(events, "B, D, A, C")
        assert result["correct"] is True


# ---------------------------------------------------------------------------
# Check Duration Answer
# ---------------------------------------------------------------------------


class TestCheckDurationAnswer:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_correct_exact_answer(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "59\nJanuary has 31 days, February has 28 in a non-leap year."
        result = kw.check_duration_answer(
            "How many days between Jan 1 and Mar 1 in a non-leap year?", 59
        )
        assert result["answer"] == 59
        assert result["correct"] is True
        assert result["expected"] == 59

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_wrong_answer_marks_incorrect(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "60\nI thought February had 29 days."
        result = kw.check_duration_answer(
            "How many days between Jan 1 and Mar 1 in a non-leap year?", 59
        )
        assert result["answer"] == 60
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_tolerance_allows_off_by_one(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "60\nSlightly off."
        result = kw.check_duration_answer(
            "How many days between Jan 1 and Mar 1 in a non-leap year?",
            59,
            tolerance=1,
        )
        assert result["answer"] == 60
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_answer_with_units_extracted(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "78 hours\nThat's 3*24 + 6."
        result = kw.check_duration_answer(
            "How many hours are in 3 days and 6 hours?", 78
        )
        assert result["answer"] == 78
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_no_integer_in_response_returns_none(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "I cannot determine the exact number of days."
        result = kw.check_duration_answer("Some question?", 42)
        assert result["answer"] is None
        assert result["correct"] is False


# ---------------------------------------------------------------------------
# Check Relative Time
# ---------------------------------------------------------------------------


class TestCheckRelativeTime:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_correct_letter(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = (
            "C) They are on the same day\n3 weeks equals 21 days."
        )
        choices = [
            "A) Sarah's birthday comes first",
            "B) John's birthday comes first",
            "C) They are on the same day",
        ]
        result = kw.check_relative_time(
            "Sarah's birthday is in 3 weeks. John's is in 21 days. Whose is sooner?",
            choices,
            "C",
        )
        assert result["chosen_letter"] == "C"
        assert result["correct"] is True
        assert result["expected"] == "C"

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_wrong_letter_marks_incorrect(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "A) Sarah's birthday comes first\nIncorrect."
        choices = ["A) Sarah first", "B) John first", "C) Same day"]
        result = kw.check_relative_time("Question?", choices, "C")
        assert result["chosen_letter"] == "A"
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_invalid_expected_letter_raises(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        choices = ["A) option", "B) option"]
        with pytest.raises(ValueError, match="expected_letter"):
            kw.check_relative_time("Question?", choices, "E")

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_unrecognised_response_is_none(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "It depends on many factors."
        choices = ["A) option1", "B) option2", "C) option3"]
        result = kw.check_relative_time("Question?", choices, "B")
        assert result["chosen_letter"] is None
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_lowercase_expected_normalised(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "B\nProject B is longer."
        choices = ["A) Project A", "B) Project B", "C) Same length"]
        result = kw.check_relative_time("Which is longer?", choices, "b")
        assert result["chosen_letter"] == "B"
        assert result["correct"] is True


# ---------------------------------------------------------------------------
# Grade Timeline Reasoning
# ---------------------------------------------------------------------------


class TestGradeTimelineReasoning:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_passing_timeline(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = (
            "The startup was founded in January, launched in April, "
            "reached 100k users in August, and raised funding in November. "
            "This growth-first strategy shows rapid product-market fit."
        )
        mock_grade = MagicMock()
        mock_grade.score = 0.9
        mock_grade.reason = "Covers all key events and draws correct inference"
        kw.grader.grade.return_value = mock_grade

        result = kw.grade_timeline_reasoning(
            scenario="A startup: founded Jan, launched Apr, 100k users Aug, Series A Nov.",
            expected_elements="beta before funding, rapid user growth, growth-first approach",
            min_score=0.5,
        )
        assert result["score"] == 0.9
        assert result["passed"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_failing_timeline(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "The company did things."
        mock_grade = MagicMock()
        mock_grade.score = 0.1
        mock_grade.reason = "Vague answer lacking temporal analysis"
        kw.grader.grade.return_value = mock_grade

        result = kw.grade_timeline_reasoning(
            scenario="Startup timeline...",
            expected_elements="rapid growth, funding after product",
            min_score=0.5,
        )
        assert result["score"] == 0.1
        assert result["passed"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_grader_receives_scenario_and_elements(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "Some timeline analysis."
        mock_grade = MagicMock()
        mock_grade.score = 0.7
        mock_grade.reason = "ok"
        kw.grader.grade.return_value = mock_grade

        kw.grade_timeline_reasoning(
            scenario="A patient was diagnosed in Year 1 and recovered by Year 3.",
            expected_elements="two-year recovery, treatment timeline",
        )
        call_args = kw.grader.grade.call_args[0]
        assert "Year 1" in call_args[0]
        assert "two-year" in call_args[1]
        assert "Some timeline analysis." in call_args[2]
