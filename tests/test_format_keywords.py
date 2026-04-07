"""Tests for rfc.format_keywords.FormatKeywords."""

from unittest.mock import patch

from rfc.format_keywords import FormatKeywords


class TestValidateJsonResponse:
    def setup_method(self) -> None:
        self.fk = FormatKeywords()

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_valid_json_all_keys(self, mock_emit: patch) -> None:
        """Valid JSON with all expected keys scores 1.0."""
        response = '{"name": "Alice", "age": 30, "email": "alice@example.com"}'
        score = self.fk.validate_json_response(response, "name,age,email")
        assert score == 1.0
        mock_emit.assert_any_call("score", "1.0000")
        mock_emit.assert_any_call("parse_valid", "true")

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_invalid_json(self, mock_emit: patch) -> None:
        """Unparseable JSON scores 0.0."""
        response = "This is not JSON at all"
        score = self.fk.validate_json_response(response, "name,age")
        assert score == 0.0
        mock_emit.assert_any_call("score", "0.0000")
        mock_emit.assert_any_call("parse_valid", "false")

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_missing_keys_partial_credit(self, mock_emit: patch) -> None:
        """JSON with some missing keys gets partial credit."""
        response = '{"name": "Alice"}'
        score = self.fk.validate_json_response(response, "name,age,email")
        # 1 of 3 keys present: parse credit (0.5) + key fraction (0.5 * 1/3)
        assert 0.0 < score < 1.0
        mock_emit.assert_any_call("parse_valid", "true")

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_extra_keys_still_full_score(self, mock_emit: patch) -> None:
        """Extra keys beyond expected do not penalize."""
        response = '{"name": "Alice", "age": 30, "email": "a@b.c", "phone": "555"}'
        score = self.fk.validate_json_response(response, "name,age,email")
        assert score == 1.0

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_json_in_markdown_code_block(self, mock_emit: patch) -> None:
        """JSON wrapped in markdown code fences is extracted and parsed."""
        response = '```json\n{"name": "Alice", "age": 30}\n```'
        score = self.fk.validate_json_response(response, "name,age")
        assert score == 1.0

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_json_array_first_element(self, mock_emit: patch) -> None:
        """JSON array validates keys against the first element."""
        response = '[{"id": 1, "name": "Widget"}, {"id": 2, "name": "Gadget"}]'
        score = self.fk.validate_json_response(response, "id,name")
        assert score == 1.0

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_string_coercion_from_robot(self, mock_emit: patch) -> None:
        """Robot Framework passes strings — ensure expected_keys works."""
        response = '{"x": 1}'
        score = self.fk.validate_json_response(response, "x")
        assert score == 1.0


class TestValidateYamlResponse:
    def setup_method(self) -> None:
        self.fk = FormatKeywords()

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_valid_yaml_all_keys(self, mock_emit: patch) -> None:
        """Valid YAML with all expected keys scores 1.0."""
        response = "host: localhost\nport: 8080\ndebug: true"
        score = self.fk.validate_yaml_response(response, "host,port,debug")
        assert score == 1.0
        mock_emit.assert_any_call("parse_valid", "true")

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_invalid_yaml(self, mock_emit: patch) -> None:
        """Unparseable YAML (or non-dict result) scores 0.0."""
        response = ":\n  :\n    - ]["
        score = self.fk.validate_yaml_response(response, "host,port")
        assert score == 0.0

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_yaml_missing_keys(self, mock_emit: patch) -> None:
        """YAML with some missing keys gets partial credit."""
        response = "host: localhost"
        score = self.fk.validate_yaml_response(response, "host,port,debug")
        assert 0.0 < score < 1.0

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_yaml_plain_string_not_dict(self, mock_emit: patch) -> None:
        """YAML that parses to a plain string (not dict) scores 0.0."""
        response = "just a plain string"
        score = self.fk.validate_yaml_response(response, "host,port")
        assert score == 0.0
        mock_emit.assert_any_call("parse_valid", "false")

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_yaml_in_code_block(self, mock_emit: patch) -> None:
        """YAML wrapped in markdown code fences is extracted."""
        response = "```yaml\nhost: localhost\nport: 8080\n```"
        score = self.fk.validate_yaml_response(response, "host,port")
        assert score == 1.0


class TestValidateCsvResponse:
    def setup_method(self) -> None:
        self.fk = FormatKeywords()

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_valid_csv(self, mock_emit: patch) -> None:
        """CSV with correct columns and enough rows scores 1.0."""
        response = "name,department,salary\nAlice,Engineering,100000\nBob,Marketing,90000"
        score = self.fk.validate_csv_response(response, 3, 2)
        assert score == 1.0
        mock_emit.assert_any_call("parse_valid", "true")

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_csv_wrong_column_count(self, mock_emit: patch) -> None:
        """CSV with wrong number of columns gets partial credit."""
        response = "name,department\nAlice,Engineering\nBob,Marketing"
        score = self.fk.validate_csv_response(response, 3, 2)
        assert 0.0 < score < 1.0

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_csv_too_few_rows(self, mock_emit: patch) -> None:
        """CSV with too few data rows gets partial credit."""
        response = "name,dept,salary\nAlice,Eng,100000"
        score = self.fk.validate_csv_response(response, 3, 3)
        assert 0.0 < score < 1.0

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_csv_empty_response(self, mock_emit: patch) -> None:
        """Empty response scores 0.0."""
        score = self.fk.validate_csv_response("", 3, 2)
        assert score == 0.0

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_csv_string_coercion(self, mock_emit: patch) -> None:
        """Robot passes strings for int args — ensure coercion works."""
        response = "a,b,c\n1,2,3"
        score = self.fk.validate_csv_response(response, "3", "1")
        assert score == 1.0

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_csv_in_code_block(self, mock_emit: patch) -> None:
        """CSV wrapped in markdown code fences is extracted."""
        response = "```csv\nname,age\nAlice,30\nBob,25\n```"
        score = self.fk.validate_csv_response(response, 2, 2)
        assert score == 1.0

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_csv_ragged_data_row(self, mock_emit: patch) -> None:
        """CSV with header width matching but a data row with fewer columns
        must not score 1.0 — every data row must match the column count."""
        response = "name,department,salary\nAlice,Engineering,100000\nBob,Marketing"
        score = self.fk.validate_csv_response(response, 3, 2)
        assert score < 1.0


class TestCountSentences:
    def setup_method(self) -> None:
        self.fk = FormatKeywords()

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_three_sentences(self, mock_emit: patch) -> None:
        text = "First sentence. Second sentence. Third sentence."
        count = self.fk.count_sentences(text)
        assert count == 3
        mock_emit.assert_any_call("sentence_count", "3")

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_single_sentence(self, mock_emit: patch) -> None:
        count = self.fk.count_sentences("Just one sentence.")
        assert count == 1

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_empty_string(self, mock_emit: patch) -> None:
        count = self.fk.count_sentences("")
        assert count == 0

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_question_and_exclamation(self, mock_emit: patch) -> None:
        text = "Is this a question? Yes it is! And a statement."
        count = self.fk.count_sentences(text)
        assert count == 3

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_no_trailing_punctuation(self, mock_emit: patch) -> None:
        """Text without trailing punctuation still counts as a sentence."""
        text = "This has no period"
        count = self.fk.count_sentences(text)
        assert count == 1

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_abbreviations_not_split(self, mock_emit: patch) -> None:
        """Common abbreviations like Mr. Dr. etc. should not split sentences."""
        text = "Dr. Smith went to Washington. He had a meeting."
        count = self.fk.count_sentences(text)
        assert count == 2

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_abbreviation_at_sentence_end(self, mock_emit: patch) -> None:
        """An abbreviation that genuinely ends a sentence must still count.
        'Acme Inc. It ships globally.' has 2 sentences."""
        text = "Acme Inc. It ships globally."
        count = self.fk.count_sentences(text)
        assert count == 2

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_abbreviation_mid_and_end(self, mock_emit: patch) -> None:
        """Abbreviation mid-sentence not split, but if next word is capitalized
        and starts a new sentence, split. 'I work at Foo Inc. Bar Corp. is next.'"""
        text = "I work at Foo Inc. Bar Corp. is next."
        count = self.fk.count_sentences(text)
        assert count == 2


class TestCountWords:
    def setup_method(self) -> None:
        self.fk = FormatKeywords()

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_normal_text(self, mock_emit: patch) -> None:
        count = self.fk.count_words("The quick brown fox")
        assert count == 4
        mock_emit.assert_any_call("word_count", "4")

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_empty_string(self, mock_emit: patch) -> None:
        count = self.fk.count_words("")
        assert count == 0

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_whitespace_only(self, mock_emit: patch) -> None:
        count = self.fk.count_words("   \n\t  ")
        assert count == 0

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_multi_space(self, mock_emit: patch) -> None:
        """Multiple spaces between words should not inflate count."""
        count = self.fk.count_words("hello    world")
        assert count == 2


class TestCheckForbiddenWords:
    def setup_method(self) -> None:
        self.fk = FormatKeywords()

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_no_violations(self, mock_emit: patch) -> None:
        """Response without forbidden words returns empty list."""
        violations = self.fk.check_forbidden_words(
            "Python is great for scripting.", "however,therefore"
        )
        assert violations == []
        mock_emit.assert_any_call("violation_count", "0")

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_single_violation(self, mock_emit: patch) -> None:
        violations = self.fk.check_forbidden_words(
            "Python is great. However, Java is faster.", "however"
        )
        assert violations == ["however"]

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_case_insensitive(self, mock_emit: patch) -> None:
        """Detection is case-insensitive."""
        violations = self.fk.check_forbidden_words(
            "HOWEVER, this works.", "however"
        )
        assert violations == ["however"]

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_multiple_violations(self, mock_emit: patch) -> None:
        violations = self.fk.check_forbidden_words(
            "However, therefore we proceed.", "however,therefore"
        )
        assert sorted(violations) == ["however", "therefore"]

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_word_boundary_no_false_positive(self, mock_emit: patch) -> None:
        """Should not match substrings: 'show' should not trigger 'how'."""
        violations = self.fk.check_forbidden_words(
            "Let me show you the way.", "how"
        )
        assert violations == []

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_empty_response(self, mock_emit: patch) -> None:
        violations = self.fk.check_forbidden_words("", "however")
        assert violations == []

    @patch("rfc.format_keywords.emit_rfc_data")
    def test_empty_forbidden_list(self, mock_emit: patch) -> None:
        """Empty forbidden words string returns no violations."""
        violations = self.fk.check_forbidden_words("Some text here.", "")
        assert violations == []
