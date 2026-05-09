"""Tests for rfc.temporal_reasoning_keywords.TemporalReasoningKeywords."""

from unittest.mock import MagicMock, patch

from rfc.temporal_reasoning_keywords import (
    TemporalReasoningKeywords,
    _extract_integer,
    _extract_letter_sequence,
    _word_match,
)


# ---------------------------------------------------------------------------
# _extract_letter_sequence
# ---------------------------------------------------------------------------


class TestExtractLetterSequence:
    def test_clean_comma_separated(self) -> None:
        assert _extract_letter_sequence("A, B, C, D", 4) == ["A", "B", "C", "D"]

    def test_lowercase_letters_normalised(self) -> None:
        assert _extract_letter_sequence("b, a, d, c", 4) == ["B", "A", "D", "C"]

    def test_mixed_case(self) -> None:
        assert _extract_letter_sequence("C, a, E, b, D", 5) == ["C", "A", "E", "B", "D"]

    def test_only_first_line_searched(self) -> None:
        # Second line has more letters — must not be used.
        result = _extract_letter_sequence("A, B\nC, D, E", 4)
        assert result is None  # only 2 on first line

    def test_scrambled_order_preserved(self) -> None:
        assert _extract_letter_sequence("D, B, A, C", 4) == ["D", "B", "A", "C"]

    def test_five_events(self) -> None:
        assert _extract_letter_sequence("B, D, A, C, E", 5) == ["B", "D", "A", "C", "E"]

    def test_returns_none_when_too_few_letters(self) -> None:
        assert _extract_letter_sequence("A, B", 4) is None

    def test_returns_none_on_empty_response(self) -> None:
        assert _extract_letter_sequence("", 4) is None

    def test_repeated_letter_same_total_rejected(self) -> None:
        # "B, A, D, C, C" has 5 raw tokens for n=4 — rejected.
        assert _extract_letter_sequence("B, A, D, C, C", 4) is None

    def test_repeated_letter_exact_count_rejected(self) -> None:
        # "B, A, B, C" has 4 raw tokens but only 3 unique — rejected.
        assert _extract_letter_sequence("B, A, B, C", 4) is None

    def test_ignores_letters_inside_words(self) -> None:
        # "Before" starts with B but that B is inside a word.
        result = _extract_letter_sequence("Before anything: A, C, D, B", 4)
        assert result == ["A", "C", "D", "B"]

    def test_letters_with_parens(self) -> None:
        # Model may use "A) B) C) D)" format on first line.
        assert _extract_letter_sequence("A) B) C) D)", 4) == ["A", "B", "C", "D"]

    def test_extra_preamble_text_ignored(self) -> None:
        # First line has prose before the sequence.
        result = _extract_letter_sequence("Order: C, A, D, B", 4)
        assert result == ["C", "A", "D", "B"]

    def test_returns_none_for_all_prose(self) -> None:
        result = _extract_letter_sequence("The events occurred in this sequence.", 4)
        assert result is None

    def test_letter_f_not_included(self) -> None:
        # F is outside A-E range and must not be returned.
        result = _extract_letter_sequence("A, B, C, D, F", 4)
        assert result == ["A", "B", "C", "D"]

    def test_too_many_letters_returns_none(self) -> None:
        # 4-event scenario but model gives 5 labels — must not truncate.
        assert _extract_letter_sequence("B, A, D, C, E", 4) is None

    def test_exact_five_letters_accepted(self) -> None:
        # 5-event scenario with exactly 5 labels — accepted.
        assert _extract_letter_sequence("B, D, A, C, E", 5) == ["B", "D", "A", "C", "E"]

    def test_extra_letters_not_masked_by_f_filter(self) -> None:
        # Even though F is filtered, 5 valid A-E labels for n=4 still rejects.
        assert _extract_letter_sequence("A, B, C, D, E", 4) is None


# ---------------------------------------------------------------------------
# _word_match
# ---------------------------------------------------------------------------


class TestWordMatch:
    def test_exact_match(self) -> None:
        assert _word_match("Monday", "Monday") is True

    def test_case_insensitive(self) -> None:
        assert _word_match("monday", "Monday") is True

    def test_embedded_in_sentence(self) -> None:
        assert _word_match("The answer is Monday.", "Monday") is True

    def test_not_before_answer_fails(self) -> None:
        assert _word_match("Not Monday", "Monday") is False

    def test_no_before_answer_fails(self) -> None:
        # "No Tuesday" (no punctuation separator) is a clear negation.
        assert _word_match("No Tuesday", "Tuesday") is False

    def test_never_before_answer_fails(self) -> None:
        assert _word_match("never Wednesday", "Wednesday") is False

    def test_isnt_before_answer_fails(self) -> None:
        assert _word_match("isn't Thursday", "Thursday") is False

    def test_wasnt_before_answer_fails(self) -> None:
        assert _word_match("wasn't Friday", "Friday") is False

    def test_answer_absent_returns_false(self) -> None:
        assert _word_match("The package arrives on Sunday.", "Monday") is False

    def test_empty_text_returns_false(self) -> None:
        assert _word_match("", "Monday") is False

    def test_answer_as_part_of_word_rejected(self) -> None:
        # "Mondays" should not match "Monday" as a whole word
        assert _word_match("Mondays are busy.", "Monday") is False

    def test_negation_in_different_clause_still_passes(self) -> None:
        # "Not sure but Monday" — negation does not immediately precede the answer
        assert _word_match("Not sure but Monday", "Monday") is True

    def test_smart_quote_isnt_fails(self) -> None:
        # U+2019 RIGHT SINGLE QUOTATION MARK — common LLM output
        assert _word_match("isn’t Monday", "Monday") is False

    def test_smart_quote_wasnt_fails(self) -> None:
        # U+2018 LEFT SINGLE QUOTATION MARK variant
        assert _word_match("wasn‘t Tuesday", "Tuesday") is False


# ---------------------------------------------------------------------------
# _extract_integer
# ---------------------------------------------------------------------------


class TestExtractInteger:
    def test_plain_integer_on_first_line(self) -> None:
        assert _extract_integer("66") == 66

    def test_integer_with_trailing_prose(self) -> None:
        assert _extract_integer("66 years elapsed between the events.") == 66

    def test_integer_buried_in_sentence(self) -> None:
        assert _extract_integer("The answer is 561 years.") == 561

    def test_only_first_line_searched(self) -> None:
        assert _extract_integer("44\n1945 to 1989") == 44

    def test_returns_none_on_empty_response(self) -> None:
        assert _extract_integer("") is None

    def test_returns_none_when_no_integer(self) -> None:
        assert _extract_integer("I cannot answer this question.") is None

    def test_first_integer_wins(self) -> None:
        # Response starts with the answer; ignore larger number later.
        assert _extract_integer("94 (from 1859 to 1953)") == 94

    def test_large_integer(self) -> None:
        assert _extract_integer("360") == 360

    def test_integer_after_label(self) -> None:
        assert _extract_integer("Answer: 131") == 131


# ---------------------------------------------------------------------------
# Initialisation
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
# Evaluate Sequence Order
# ---------------------------------------------------------------------------


class TestEvaluateSequenceOrder:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_correct_order_passes(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "A, B, C, D, E\nHere is my reasoning."
        result = kw.evaluate_sequence_order(
            events=[
                "Sputnik 1 launches (1957)",
                "Gagarin first human in space (1961)",
                "Apollo 11 Moon landing (1969)",
                "Voyager 1 launched (1977)",
                "Hubble Space Telescope launched (1990)",
            ],
            expected_order=["A", "B", "C", "D", "E"],
        )
        assert result["correct"] is True
        assert result["extracted_order"] == ["A", "B", "C", "D", "E"]
        assert result["expected_order"] == ["A", "B", "C", "D", "E"]

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_wrong_order_fails(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "A, B, C, D\nExplanation here."
        result = kw.evaluate_sequence_order(
            events=[
                "Watson-Crick DNA helix (1953)",
                "Fleming discovers penicillin (1928)",
                "CRISPR developed (2012)",
                "PCR invented (1983)",
            ],
            expected_order=["B", "A", "D", "C"],
        )
        assert result["correct"] is False
        assert result["extracted_order"] == ["A", "B", "C", "D"]
        assert result["expected_order"] == ["B", "A", "D", "C"]

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_scrambled_order_correct(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "B, A, D, C"
        result = kw.evaluate_sequence_order(
            events=[
                "Watson-Crick DNA helix (1953)",
                "Fleming discovers penicillin (1928)",
                "CRISPR developed (2012)",
                "PCR invented (1983)",
            ],
            expected_order=["B", "A", "D", "C"],
        )
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_unextractable_response_is_incorrect(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = (
            "I cannot determine the order without more information."
        )
        result = kw.evaluate_sequence_order(
            events=["Event one", "Event two", "Event three", "Event four"],
            expected_order=["A", "B", "C", "D"],
        )
        assert result["correct"] is False
        assert result["extracted_order"] is None

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_lowercase_expected_order_normalised(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "B, A, D, C"
        result = kw.evaluate_sequence_order(
            events=["E1", "E2", "E3", "E4"],
            expected_order=["b", "a", "d", "c"],
        )
        assert result["correct"] is True
        assert result["expected_order"] == ["B", "A", "D", "C"]

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_extra_label_in_response_rejected(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        # 4-event scenario but model outputs 5 labels — must not truncate to 4.
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "B, A, D, C, E"
        result = kw.evaluate_sequence_order(
            events=[
                "Watson-Crick DNA helix (1953)",
                "Fleming discovers penicillin (1928)",
                "CRISPR developed (2012)",
                "PCR invented (1983)",
            ],
            expected_order=["B", "A", "D", "C"],
        )
        assert result["correct"] is False
        assert result["extracted_order"] is None


# ---------------------------------------------------------------------------
# Evaluate Duration
# ---------------------------------------------------------------------------


class TestEvaluateDuration:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_correct_duration(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "66"
        result = kw.evaluate_duration(
            question=(
                "How many complete years elapsed between the Wright Brothers' "
                "first flight in 1903 and the Apollo 11 Moon landing in 1969?"
            ),
            expected_years=66,
        )
        assert result["correct"] is True
        assert result["extracted_years"] == 66
        assert result["expected_years"] == 66

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_wrong_duration_fails(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "65"
        result = kw.evaluate_duration(
            question="How many complete years from 1903 to 1969?",
            expected_years=66,
        )
        assert result["correct"] is False
        assert result["extracted_years"] == 65

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_answer_with_prose_extracted(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "561 years elapsed between those events."
        result = kw.evaluate_duration(
            question="Years from Magna Carta (1215) to Independence (1776)?",
            expected_years=561,
        )
        assert result["correct"] is True
        assert result["extracted_years"] == 561

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_no_integer_in_response_fails(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "I don't know the exact number."
        result = kw.evaluate_duration(
            question="How many years between X and Y?",
            expected_years=44,
        )
        assert result["correct"] is False
        assert result["extracted_years"] is None

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_expected_years_coerced_to_int(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "94"
        result = kw.evaluate_duration(
            question="Years from Darwin (1859) to DNA (1953)?",
            expected_years=94,  # type: ignore[arg-type]
        )
        assert result["expected_years"] == 94
        assert result["correct"] is True


# ---------------------------------------------------------------------------
# Evaluate Temporal Word Problem
# ---------------------------------------------------------------------------


class TestEvaluateTemporalWordProblem:
    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_correct_day_answer(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "Monday\nBecause Friday + 3 = Monday."
        result = kw.evaluate_temporal_word_problem(
            question=(
                "A package is shipped on Friday. "
                "It arrives exactly 3 days later. "
                "What day of the week does it arrive?"
            ),
            expected_answer="Monday",
        )
        assert result["correct"] is True
        assert result["first_line"] == "Monday"

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_wrong_day_fails(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "Sunday"
        result = kw.evaluate_temporal_word_problem(
            question="Package ships Friday, arrives 3 days later?",
            expected_answer="Monday",
        )
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_case_insensitive_match(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "monday"
        result = kw.evaluate_temporal_word_problem(
            question="Ship on Friday, arrives 3 days later?",
            expected_answer="Monday",
        )
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_answer_embedded_in_first_line(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "The deadline is Wednesday."
        result = kw.evaluate_temporal_word_problem(
            question="Thursday + 90 days?",
            expected_answer="Wednesday",
        )
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_empty_response_fails(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = ""
        result = kw.evaluate_temporal_word_problem(
            question="Anything?",
            expected_answer="Monday",
        )
        assert result["correct"] is False
        assert result["first_line"] == ""

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_tuesday_same_day_after_14_days(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "Tuesday"
        result = kw.evaluate_temporal_word_problem(
            question=(
                "If today is Tuesday and the deadline is exactly 14 days "
                "from today, what day of the week is the deadline?"
            ),
            expected_answer="Tuesday",
        )
        assert result["correct"] is True

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_only_first_line_checked(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        kw = TemporalReasoningKeywords()
        # Correct answer only on second line — should fail.
        kw.client.generate.return_value = "I need to calculate this.\nMonday"
        result = kw.evaluate_temporal_word_problem(
            question="Ship Friday, arrives 3 days later?",
            expected_answer="Monday",
        )
        assert result["correct"] is False
        assert result["first_line"] == "I need to calculate this."

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_negated_answer_fails(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        # "Not Monday" must not pass when "Monday" is expected.
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "Not Monday"
        result = kw.evaluate_temporal_word_problem(
            question="Ship Friday, arrives 3 days later?",
            expected_answer="Monday",
        )
        assert result["correct"] is False

    @patch("rfc.temporal_reasoning_keywords.create_provider")
    @patch("rfc.temporal_reasoning_keywords.Grader")
    def test_no_before_answer_fails(
        self, MockGrader: MagicMock, mock_create: MagicMock
    ) -> None:
        # "No Monday" (space only, no punctuation) is a clear negation.
        kw = TemporalReasoningKeywords()
        kw.client.generate.return_value = "No Monday"
        result = kw.evaluate_temporal_word_problem(
            question="Package arrives Tuesday?",
            expected_answer="Monday",
        )
        assert result["correct"] is False
