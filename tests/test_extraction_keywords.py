"""Tests for rfc.extraction_keywords.ExtractionKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.extraction_keywords import ExtractionKeywords


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_kw(**kwargs) -> ExtractionKeywords:
    with patch("rfc.extraction_keywords.create_provider"):
        kw = ExtractionKeywords(**kwargs)
    kw.client = MagicMock()
    return kw


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestInit:
    @patch("rfc.extraction_keywords.create_provider")
    def test_default_timeout(self, mock_cp: MagicMock) -> None:
        ExtractionKeywords()
        mock_cp.assert_called_once_with(timeout=5400, max_retries=2)

    @patch("rfc.extraction_keywords.create_provider")
    def test_custom_timeout(self, mock_cp: MagicMock) -> None:
        ExtractionKeywords(timeout=30, max_retries=1)
        mock_cp.assert_called_once_with(timeout=30, max_retries=1)


# ---------------------------------------------------------------------------
# _recall
# ---------------------------------------------------------------------------


class TestRecall:
    def test_all_found(self) -> None:
        kw = _make_kw()
        score, found, missing = kw._recall("Alice and Bob attended.", ["Alice", "Bob"])
        assert score == pytest.approx(1.0)
        assert found == ["Alice", "Bob"]
        assert missing == []

    def test_partial_found(self) -> None:
        kw = _make_kw()
        score, found, missing = kw._recall("Alice attended.", ["Alice", "Bob"])
        assert score == pytest.approx(0.5)
        assert found == ["Alice"]
        assert missing == ["Bob"]

    def test_none_found(self) -> None:
        kw = _make_kw()
        score, found, missing = kw._recall("No names here.", ["Alice", "Bob"])
        assert score == pytest.approx(0.0)
        assert missing == ["Alice", "Bob"]

    def test_case_insensitive(self) -> None:
        kw = _make_kw()
        score, found, _ = kw._recall("alice and BOB attended.", ["Alice", "Bob"])
        assert score == pytest.approx(1.0)

    def test_empty_expected(self) -> None:
        kw = _make_kw()
        score, _, _ = kw._recall("some text", [])
        assert score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _strip_commas
# ---------------------------------------------------------------------------


class TestStripCommas:
    def test_removes_comma_separators(self) -> None:
        assert ExtractionKeywords._strip_commas("1,234") == "1234"
        assert ExtractionKeywords._strip_commas("1,234,567") == "1234567"

    def test_plain_number_unchanged(self) -> None:
        assert ExtractionKeywords._strip_commas("42") == "42"

    def test_decimal_unchanged(self) -> None:
        assert ExtractionKeywords._strip_commas("3.14") == "3.14"


# ---------------------------------------------------------------------------
# ask_and_extract_named_entities
# ---------------------------------------------------------------------------


class TestAskAndExtractNamedEntities:
    def test_all_entities_found_passes(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "Alice\nBob\nCarol"
        result = kw.ask_and_extract_named_entities(
            context="Alice, Bob, and Carol met yesterday.",
            expected_entities=["Alice", "Bob", "Carol"],
        )
        assert result["passed"] is True
        assert result["score"] == pytest.approx(1.0)
        assert result["missing"] == []

    def test_partial_recall_with_min_score_passes(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "Alice\nBob"
        result = kw.ask_and_extract_named_entities(
            context="Alice, Bob, and Carol met.",
            expected_entities=["Alice", "Bob", "Carol"],
            min_score=0.6,
        )
        assert result["passed"] is True
        assert result["missing"] == ["Carol"]

    def test_partial_recall_below_threshold_fails(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "Alice"
        result = kw.ask_and_extract_named_entities(
            context="Alice, Bob, Carol.",
            expected_entities=["Alice", "Bob", "Carol"],
            min_score=1.0,
        )
        assert result["passed"] is False

    def test_entity_type_in_prompt(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "Acme Corp"
        kw.ask_and_extract_named_entities(
            context="Acme Corp hired Alice.",
            expected_entities=["Acme Corp"],
            entity_type="organization",
        )
        call_args = kw.client.generate.call_args[0][0]
        assert "organization" in call_args

    def test_think_block_stripped(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "<think>reasoning</think>Alice\nBob"
        result = kw.ask_and_extract_named_entities(
            context="Alice and Bob.",
            expected_entities=["Alice", "Bob"],
        )
        assert result["passed"] is True


# ---------------------------------------------------------------------------
# ask_and_extract_numeric_fact
# ---------------------------------------------------------------------------


class TestAskAndExtractNumericFact:
    def test_exact_match_passes(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "42"
        result = kw.ask_and_extract_numeric_fact(
            context="The company has 42 employees.",
            question="How many employees does the company have?",
            expected_value="42",
        )
        assert result["passed"] is True

    def test_comma_formatted_matches_plain(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "1,234"
        result = kw.ask_and_extract_numeric_fact(
            context="Revenue was 1234.",
            question="What was the revenue?",
            expected_value="1234",
        )
        assert result["passed"] is True

    def test_wrong_number_fails(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "99"
        result = kw.ask_and_extract_numeric_fact(
            context="The company has 42 employees.",
            question="How many employees?",
            expected_value="42",
        )
        assert result["passed"] is False

    def test_strips_non_numeric_chars(self) -> None:
        kw = _make_kw()
        # Response has trailing punctuation
        kw.client.generate.return_value = "42."
        result = kw.ask_and_extract_numeric_fact(
            context="42 units.",
            question="How many units?",
            expected_value="42",
        )
        assert result["passed"] is True


# ---------------------------------------------------------------------------
# ask_and_extract_key_value_pairs
# ---------------------------------------------------------------------------


class TestAskAndExtractKeyValuePairs:
    def test_all_pairs_found_passes(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "CEO: Alice\nFounded: 1994\nHQ: Seattle"
        result = kw.ask_and_extract_key_value_pairs(
            context="Alice is CEO. Company founded 1994. HQ in Seattle.",
            expected_pairs=["CEO: Alice", "Founded: 1994"],
        )
        assert result["passed"] is True
        assert result["score"] == pytest.approx(1.0)

    def test_missing_pair_fails_with_full_threshold(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "CEO: Alice"
        result = kw.ask_and_extract_key_value_pairs(
            context="Alice is CEO. Founded 1994.",
            expected_pairs=["CEO: Alice", "Founded: 1994"],
            min_score=1.0,
        )
        assert result["passed"] is False
        assert "Founded: 1994" in result["missing"]

    def test_partial_passes_with_low_threshold(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "CEO: Alice"
        result = kw.ask_and_extract_key_value_pairs(
            context="Alice is CEO. Founded 1994.",
            expected_pairs=["CEO: Alice", "Founded: 1994"],
            min_score=0.5,
        )
        assert result["passed"] is True


# ---------------------------------------------------------------------------
# assert_extraction_passed
# ---------------------------------------------------------------------------


class TestAssertExtractionPassed:
    def test_passes_when_passed_true(self) -> None:
        kw = _make_kw()
        kw.assert_extraction_passed({"passed": True})

    def test_raises_when_passed_false(self) -> None:
        kw = _make_kw()
        with pytest.raises(AssertionError, match="entity extraction failed"):
            kw.assert_extraction_passed(
                {"passed": False, "reason": "recall=0.5"}, label="entity extraction"
            )
