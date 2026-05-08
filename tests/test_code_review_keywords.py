"""Tests for rfc.code_review_keywords.CodeReviewKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.code_review_keywords import (
    CodeReviewKeywords,
    _extract_letter,
)


# ---------------------------------------------------------------------------
# Private helper tests
# ---------------------------------------------------------------------------


class TestExtractLetter:
    def test_letter_a_with_paren(self) -> None:
        assert _extract_letter("A) Missing parentheses on the method call.") == "A"

    def test_letter_b(self) -> None:
        assert _extract_letter("B\nSQL injection via string concatenation.") == "B"

    def test_letter_c_with_paren(self) -> None:
        assert _extract_letter("C) Path traversal vulnerability.") == "C"

    def test_letter_d(self) -> None:
        assert _extract_letter("D) No vulnerability here.") == "D"

    def test_lowercase_converted(self) -> None:
        assert _extract_letter("b) mutable default argument") == "B"

    def test_returns_none_when_no_letter_on_first_line(self) -> None:
        assert _extract_letter("The bug is in line 3 of the snippet.") is None

    def test_letter_mid_sentence_ignored(self) -> None:
        result = _extract_letter("The answer is A) this one")
        assert result is None

    def test_only_first_line_searched(self) -> None:
        response = "Let me analyse the code.\nB) SQL injection"
        assert _extract_letter(response) is None

    def test_empty_response_returns_none(self) -> None:
        assert _extract_letter("") is None


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestCodeReviewKeywordsInit:
    @patch("rfc.code_review_keywords.create_provider")
    def test_default_init(self, mock_create: MagicMock) -> None:
        CodeReviewKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)

    @patch("rfc.code_review_keywords.create_provider")
    def test_custom_timeout(self, mock_create: MagicMock) -> None:
        CodeReviewKeywords(timeout=45, max_retries=1)
        mock_create.assert_called_once_with(timeout=45, max_retries=1)


# ---------------------------------------------------------------------------
# Identify Bug In Code
# ---------------------------------------------------------------------------


class TestIdentifyBugInCode:
    @patch("rfc.code_review_keywords.create_provider")
    def test_correct_letter_selected(self, mock_create: MagicMock) -> None:
        kw = CodeReviewKeywords()
        kw.client.generate.return_value = (
            "B) The mutable default argument `collection=[]` is shared across calls."
        )
        result = kw.identify_bug_in_code(
            code="def add_item(value, collection=[]):\n    collection.append(value)\n    return collection",
            question="Which option correctly identifies the bug?\nA) Use extend() instead\nB) Mutable default arg is shared\nC) Return a copy\nD) No bug",
            expected_letter="B",
        )
        assert result["chosen_letter"] == "B"
        assert result["correct"] is True
        assert result["expected"] == "B"

    @patch("rfc.code_review_keywords.create_provider")
    def test_wrong_letter_marked_incorrect(self, mock_create: MagicMock) -> None:
        kw = CodeReviewKeywords()
        kw.client.generate.return_value = "D) There is no bug."
        result = kw.identify_bug_in_code(
            code="def get_last(data):\n    return data[len(data)]",
            question="Which option identifies the bug?\nA) Wrong name\nB) Off-by-one\nC) Use loop\nD) No bug",
            expected_letter="B",
        )
        assert result["chosen_letter"] == "D"
        assert result["correct"] is False

    @patch("rfc.code_review_keywords.create_provider")
    def test_invalid_expected_letter_raises(self, mock_create: MagicMock) -> None:
        kw = CodeReviewKeywords()
        with pytest.raises(ValueError, match="expected_letter must be A"):
            kw.identify_bug_in_code(
                code="some code",
                question="some question",
                expected_letter="E",
            )

    @patch("rfc.code_review_keywords.create_provider")
    def test_unrecognised_response_letter_is_none(self, mock_create: MagicMock) -> None:
        kw = CodeReviewKeywords()
        kw.client.generate.return_value = "The bug is the missing parentheses."
        result = kw.identify_bug_in_code(
            code="def f(x):\n    return len(x.split)",
            question="Which option identifies the bug?\nA) Missing parens\nB) Use filter\nC) Use regex\nD) No bug",
            expected_letter="A",
        )
        assert result["chosen_letter"] is None
        assert result["correct"] is False

    @patch("rfc.code_review_keywords.create_provider")
    def test_result_keys_present(self, mock_create: MagicMock) -> None:
        kw = CodeReviewKeywords()
        kw.client.generate.return_value = "A) Missing parentheses."
        result = kw.identify_bug_in_code(
            code="def f(x):\n    return len(x.split)",
            question="Which option?\nA) Missing parens\nB) Other\nC) Other\nD) No bug",
            expected_letter="A",
        )
        assert "chosen_letter" in result
        assert "correct" in result
        assert "response" in result
        assert "expected" in result

    @patch("rfc.code_review_keywords.create_provider")
    def test_expected_letter_case_insensitive(self, mock_create: MagicMock) -> None:
        kw = CodeReviewKeywords()
        kw.client.generate.return_value = "C) Correct answer."
        result = kw.identify_bug_in_code(
            code="some code",
            question="question",
            expected_letter="c",
        )
        assert result["expected"] == "C"
        assert result["correct"] is True


# ---------------------------------------------------------------------------
# Identify Security Vulnerability
# ---------------------------------------------------------------------------


class TestIdentifySecurityVulnerability:
    @patch("rfc.code_review_keywords.create_provider")
    def test_correct_sql_injection(self, mock_create: MagicMock) -> None:
        kw = CodeReviewKeywords()
        kw.client.generate.return_value = (
            "B) String concatenation of user input into SQL enables injection."
        )
        result = kw.identify_security_vulnerability(
            code='query = "SELECT * FROM users WHERE name = \'" + username + "\'"',
            question="Which option describes the vulnerability?\nA) Use SELECT id\nB) SQL injection\nC) No close\nD) No vuln",
            expected_letter="B",
        )
        assert result["chosen_letter"] == "B"
        assert result["correct"] is True

    @patch("rfc.code_review_keywords.create_provider")
    def test_wrong_letter_marked_incorrect(self, mock_create: MagicMock) -> None:
        kw = CodeReviewKeywords()
        kw.client.generate.return_value = "A) Use SELECT id instead."
        result = kw.identify_security_vulnerability(
            code='query = "SELECT * FROM users WHERE name = \'" + username + "\'"',
            question="Which option?\nA) Use SELECT id\nB) SQL injection\nC) No close\nD) No vuln",
            expected_letter="B",
        )
        assert result["chosen_letter"] == "A"
        assert result["correct"] is False

    @patch("rfc.code_review_keywords.create_provider")
    def test_invalid_expected_letter_raises(self, mock_create: MagicMock) -> None:
        kw = CodeReviewKeywords()
        with pytest.raises(ValueError, match="expected_letter must be A"):
            kw.identify_security_vulnerability(
                code="some code",
                question="some question",
                expected_letter="X",
            )

    @patch("rfc.code_review_keywords.create_provider")
    def test_result_keys_present(self, mock_create: MagicMock) -> None:
        kw = CodeReviewKeywords()
        kw.client.generate.return_value = "C) Path traversal."
        result = kw.identify_security_vulnerability(
            code="path = os.path.join('/uploads/', filename)",
            question="Which option?\nA) Use pathlib\nB) Memory issue\nC) Path traversal\nD) No vuln",
            expected_letter="C",
        )
        assert "chosen_letter" in result
        assert "correct" in result
        assert "response" in result
        assert "expected" in result
