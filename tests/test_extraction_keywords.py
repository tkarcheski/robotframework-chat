"""Tests for rfc.extraction_keywords.ExtractionKeywords."""

from unittest.mock import MagicMock, patch

from rfc.extraction_keywords import (
    ExtractionKeywords,
    _contains_value,
    _entity_in_lines,
    _strip_label,
)


# ---------------------------------------------------------------------------
# Private helper tests
# ---------------------------------------------------------------------------


class TestStripLabel:
    def test_strips_answer_prefix(self) -> None:
        assert _strip_label("Answer: Paris") == "Paris"

    def test_strips_value_prefix(self) -> None:
        assert _strip_label("Value: 190°C") == "190°C"

    def test_strips_name_prefix(self) -> None:
        assert _strip_label("Name: Dr. Priya Nair") == "Dr. Priya Nair"

    def test_no_prefix_unchanged(self) -> None:
        assert _strip_label("Paris") == "Paris"

    def test_multiline_only_first_line(self) -> None:
        assert _strip_label("Answer: Lisbon\nThis city is in Portugal.") == "Lisbon"

    def test_empty_string(self) -> None:
        assert _strip_label("") == ""

    def test_only_whitespace(self) -> None:
        assert _strip_label("   ") == ""

    def test_time_value_not_stripped(self) -> None:
        # "2:30 PM" must not be mangled to "30 PM" by the label-strip regex.
        assert _strip_label("2:30 PM") == "2:30 PM"

    def test_url_not_stripped(self) -> None:
        # "https://example.com" must not be mangled to "//example.com".
        assert _strip_label("https://example.com") == "https://example.com"

    def test_ratio_not_stripped(self) -> None:
        assert _strip_label("3:1 ratio") == "3:1 ratio"

    def test_multiword_title_not_stripped(self) -> None:
        # "Star Wars: Episode IV" must not be mangled to "Episode IV".
        assert _strip_label("Star Wars: Episode IV") == "Star Wars: Episode IV"

    def test_chapter_title_not_stripped(self) -> None:
        assert _strip_label("Chapter One: Arrival") == "Chapter One: Arrival"


class TestContainsValue:
    def test_exact_match(self) -> None:
        assert _contains_value("Paris", "Paris") is True

    def test_case_insensitive(self) -> None:
        assert _contains_value("paris", "Paris") is True

    def test_substring_in_longer_response(self) -> None:
        assert _contains_value("The city is Paris, France.", "Paris") is True

    def test_numeric_match(self) -> None:
        assert _contains_value("The answer is 1950.", "1950") is True

    def test_numeric_with_commas_stripped(self) -> None:
        assert _contains_value("2,847", "2847") is True

    def test_numeric_stripped_vs_comma(self) -> None:
        assert _contains_value("2847", "2,847") is True

    def test_false_when_absent(self) -> None:
        assert _contains_value("Lyon is a city in France.", "Paris") is False

    def test_empty_response_returns_false(self) -> None:
        assert _contains_value("", "Paris") is False

    def test_empty_expected_returns_false(self) -> None:
        assert _contains_value("Paris", "") is False

    def test_partial_word_boundary_not_required(self) -> None:
        # "Go" should match when looking for "Go" in "Programming in Go."
        assert _contains_value("Programming in Go.", "Go") is True


# ---------------------------------------------------------------------------
# _entity_in_lines
# ---------------------------------------------------------------------------


class TestEntityInLines:
    def test_entity_on_plain_line(self) -> None:
        assert _entity_in_lines("Python\nGo\nRust", "Python") is True

    def test_entity_with_list_marker_hyphen(self) -> None:
        assert _entity_in_lines("- Python\n- Go\n- Rust", "Go") is True

    def test_entity_with_numbered_marker(self) -> None:
        assert _entity_in_lines("1. Python\n2. Go\n3. Rust", "Rust") is True

    def test_negated_line_excluded(self) -> None:
        # "Rust is not mentioned" must NOT count as a match for "Rust"
        assert _entity_in_lines("Python\nGo\nRust is not mentioned", "Rust") is False

    def test_negated_with_never(self) -> None:
        assert _entity_in_lines("Python\nnever uses Rust", "Rust") is False

    def test_absent_negation(self) -> None:
        assert _entity_in_lines("Python\nRust is absent", "Rust") is False

    def test_entity_not_in_response(self) -> None:
        assert _entity_in_lines("Python\nGo", "Rust") is False

    def test_empty_response_returns_false(self) -> None:
        assert _entity_in_lines("", "Python") is False

    def test_empty_entity_returns_false(self) -> None:
        assert _entity_in_lines("Python\nGo", "") is False

    def test_case_insensitive(self) -> None:
        assert _entity_in_lines("python\ngo", "Python") is True

    def test_blank_lines_skipped(self) -> None:
        assert _entity_in_lines("\n\nRust\n\n", "Rust") is True

    def test_entity_present_in_non_negated_line(self) -> None:
        # "Rust" appears on one clean line AND one negated line — should still pass
        assert _entity_in_lines("Rust\nRust is not popular here", "Rust") is True

    def test_no_negation_word_excluded(self) -> None:
        # "No Rust mentioned" must not count as a positive hit for "Rust".
        assert _entity_in_lines("Python\nGo\nNo Rust mentioned", "Rust") is False

    def test_no_at_line_start_excluded(self) -> None:
        assert _entity_in_lines("No JavaScript used here", "JavaScript") is False

    def test_no_word_boundary_does_not_affect_node(self) -> None:
        # "node" contains "no" but is not the word "no" — must not be excluded.
        assert _entity_in_lines("node.js", "node.js") is True


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestExtractionKeywordsInit:
    @patch("rfc.extraction_keywords.create_provider")
    def test_default_init(self, mock_create: MagicMock) -> None:
        ExtractionKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)

    @patch("rfc.extraction_keywords.create_provider")
    def test_custom_timeout(self, mock_create: MagicMock) -> None:
        ExtractionKeywords(timeout=60, max_retries=1)
        mock_create.assert_called_once_with(timeout=60, max_retries=1)


# ---------------------------------------------------------------------------
# Extract And Verify Entity
# ---------------------------------------------------------------------------


class TestExtractAndVerifyEntity:
    @patch("rfc.extraction_keywords.create_provider")
    def test_correct_entity_extracted(self, mock_create: MagicMock) -> None:
        kw = ExtractionKeywords()
        kw.client.generate.return_value = "Priya Nair"
        result = kw.extract_and_verify_entity(
            text="CEO Dr. Priya Nair announced the partnership.",
            question="What is the name of the CEO?",
            expected_value="Priya Nair",
        )
        assert result["correct"] is True
        assert result["expected"] == "Priya Nair"

    @patch("rfc.extraction_keywords.create_provider")
    def test_wrong_entity_marked_incorrect(self, mock_create: MagicMock) -> None:
        kw = ExtractionKeywords()
        kw.client.generate.return_value = "John Smith"
        result = kw.extract_and_verify_entity(
            text="CEO Dr. Priya Nair announced the partnership.",
            question="What is the name of the CEO?",
            expected_value="Priya Nair",
        )
        assert result["correct"] is False

    @patch("rfc.extraction_keywords.create_provider")
    def test_case_insensitive_match(self, mock_create: MagicMock) -> None:
        kw = ExtractionKeywords()
        kw.client.generate.return_value = "lisbon"
        result = kw.extract_and_verify_entity(
            text="My trip to Lisbon was unforgettable.",
            question="Which city is described?",
            expected_value="Lisbon",
        )
        assert result["correct"] is True

    @patch("rfc.extraction_keywords.create_provider")
    def test_response_with_label_prefix_stripped(self, mock_create: MagicMock) -> None:
        kw = ExtractionKeywords()
        kw.client.generate.return_value = "Answer: Paris"
        result = kw.extract_and_verify_entity(
            text="The capital of France is Paris.",
            question="What is the capital of France?",
            expected_value="Paris",
        )
        assert result["correct"] is True

    @patch("rfc.extraction_keywords.create_provider")
    def test_result_keys_present(self, mock_create: MagicMock) -> None:
        kw = ExtractionKeywords()
        kw.client.generate.return_value = "1950"
        result = kw.extract_and_verify_entity(
            text="Turing's paper was published in 1950.",
            question="What year was the paper published?",
            expected_value="1950",
        )
        assert "extracted" in result
        assert "correct" in result
        assert "response" in result
        assert "expected" in result

    @patch("rfc.extraction_keywords.create_provider")
    def test_regression_expected_in_prose_does_not_pass(
        self, mock_create: MagicMock
    ) -> None:
        # Regression: "Berlin\nNote that Paris is the capital of France." should
        # NOT be graded correct when the expected value is "Paris". The extracted
        # answer is "Berlin"; the mention of "Paris" in explanatory prose must
        # not inflate the pass rate.
        kw = ExtractionKeywords()
        kw.client.generate.return_value = (
            "Berlin\nNote that Paris is the capital of France, not Berlin."
        )
        result = kw.extract_and_verify_entity(
            text="What is the capital of Germany?",
            question="Which city is the capital?",
            expected_value="Paris",
        )
        assert result["extracted"] == "Berlin"
        assert result["correct"] is False


# ---------------------------------------------------------------------------
# Extract Key Value And Verify
# ---------------------------------------------------------------------------


class TestExtractKeyValueAndVerify:
    @patch("rfc.extraction_keywords.create_provider")
    def test_correct_key_value_extracted(self, mock_create: MagicMock) -> None:
        kw = ExtractionKeywords()
        kw.client.generate.return_value = "2.3.0"
        result = kw.extract_key_value_and_verify(
            text="PyTorch 2.3.0 was released this month.",
            attribute="software version number",
            expected_value="2.3.0",
        )
        assert result["correct"] is True

    @patch("rfc.extraction_keywords.create_provider")
    def test_wrong_value_marked_incorrect(self, mock_create: MagicMock) -> None:
        kw = ExtractionKeywords()
        kw.client.generate.return_value = "3.0.0"
        result = kw.extract_key_value_and_verify(
            text="PyTorch 2.3.0 was released this month.",
            attribute="software version number",
            expected_value="2.3.0",
        )
        assert result["correct"] is False

    @patch("rfc.extraction_keywords.create_provider")
    def test_numeric_with_comma_formatting(self, mock_create: MagicMock) -> None:
        kw = ExtractionKeywords()
        kw.client.generate.return_value = "2,847"
        result = kw.extract_key_value_and_verify(
            text="A trial enrolled 2,847 participants.",
            attribute="number of participants",
            expected_value="2847",
        )
        assert result["correct"] is True

    @patch("rfc.extraction_keywords.create_provider")
    def test_result_keys_present(self, mock_create: MagicMock) -> None:
        kw = ExtractionKeywords()
        kw.client.generate.return_value = "Apache"
        result = kw.extract_key_value_and_verify(
            text="This is distributed under the Apache License, Version 2.0.",
            attribute="license type",
            expected_value="Apache",
        )
        assert "extracted" in result
        assert "correct" in result
        assert "response" in result
        assert "expected" in result

    @patch("rfc.extraction_keywords.create_provider")
    def test_regression_value_in_prose_does_not_pass(
        self, mock_create: MagicMock
    ) -> None:
        # Regression: "3.0.0\nNote: 2.3.0 was the previous release." should NOT
        # pass when the expected value is "2.3.0". Only the extracted first line
        # (3.0.0) should be checked, not the full response.
        kw = ExtractionKeywords()
        kw.client.generate.return_value = "3.0.0\nNote: 2.3.0 was the previous release."
        result = kw.extract_key_value_and_verify(
            text="PyTorch 2.3.0 was released this month.",
            attribute="software version number",
            expected_value="2.3.0",
        )
        assert result["extracted"] == "3.0.0"
        assert result["correct"] is False


# ---------------------------------------------------------------------------
# Extract Multiple Entities And Verify
# ---------------------------------------------------------------------------


class TestExtractMultipleEntitiesAndVerify:
    @patch("rfc.extraction_keywords.create_provider")
    def test_all_found(self, mock_create: MagicMock) -> None:
        kw = ExtractionKeywords()
        kw.client.generate.return_value = "Python, Go, and Rust"
        result = kw.extract_multiple_entities_and_verify(
            text="The project uses Python, Go, and Rust.",
            question="What programming languages are mentioned?",
            expected_values=["Python", "Go", "Rust"],
        )
        assert result["correct"] is True
        assert result["missing"] == []

    @patch("rfc.extraction_keywords.create_provider")
    def test_partial_found_marks_incorrect(self, mock_create: MagicMock) -> None:
        kw = ExtractionKeywords()
        kw.client.generate.return_value = "Python and Go"
        result = kw.extract_multiple_entities_and_verify(
            text="The project uses Python, Go, and Rust.",
            question="What programming languages are mentioned?",
            expected_values=["Python", "Go", "Rust"],
        )
        assert result["correct"] is False
        assert "Rust" in result["missing"]

    @patch("rfc.extraction_keywords.create_provider")
    def test_result_keys_present(self, mock_create: MagicMock) -> None:
        kw = ExtractionKeywords()
        kw.client.generate.return_value = "Vienna"
        result = kw.extract_multiple_entities_and_verify(
            text="The conference is in Vienna.",
            question="Which city?",
            expected_values=["Vienna"],
        )
        assert "found" in result
        assert "missing" in result
        assert "correct" in result
        assert "response" in result
        assert "expected" in result

    @patch("rfc.extraction_keywords.create_provider")
    def test_regression_negated_mention_not_counted(
        self, mock_create: MagicMock
    ) -> None:
        # Regression: "Rust is not mentioned" must NOT be a positive hit for "Rust".
        # Full-text substring matching would incorrectly pass this; line-based
        # parsing with negation detection must exclude it.
        kw = ExtractionKeywords()
        kw.client.generate.return_value = "Python\nGo\nRust is not mentioned"
        result = kw.extract_multiple_entities_and_verify(
            text="The project uses Python, Go, and Rust.",
            question="What programming languages are mentioned?",
            expected_values=["Python", "Go", "Rust"],
        )
        assert result["correct"] is False
        assert "Rust" in result["missing"]
