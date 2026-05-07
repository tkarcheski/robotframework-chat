"""Tests for rfc.code_review_keywords.CodeReviewKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.code_review_keywords import CodeReviewKeywords, _KNOWN_BUG_TYPES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_kw(**kwargs) -> CodeReviewKeywords:
    with patch("rfc.code_review_keywords.create_provider"):
        kw = CodeReviewKeywords(**kwargs)
    kw.client = MagicMock()
    return kw


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestInit:
    @patch("rfc.code_review_keywords.create_provider")
    def test_default_timeout(self, mock_cp: MagicMock) -> None:
        CodeReviewKeywords()
        mock_cp.assert_called_once_with(timeout=5400, max_retries=2)

    @patch("rfc.code_review_keywords.create_provider")
    def test_custom_timeout(self, mock_cp: MagicMock) -> None:
        CodeReviewKeywords(timeout=45, max_retries=3)
        mock_cp.assert_called_once_with(timeout=45, max_retries=3)


# ---------------------------------------------------------------------------
# _KNOWN_BUG_TYPES constant
# ---------------------------------------------------------------------------


class TestKnownBugTypes:
    def test_contains_expected_categories(self) -> None:
        for bt in [
            "off-by-one",
            "null-pointer",
            "resource-leak",
            "infinite-loop",
            "logic-error",
        ]:
            assert bt in _KNOWN_BUG_TYPES

    def test_is_frozen(self) -> None:
        assert isinstance(_KNOWN_BUG_TYPES, frozenset)


# ---------------------------------------------------------------------------
# _keyword_recall
# ---------------------------------------------------------------------------


class TestKeywordRecall:
    def test_all_found(self) -> None:
        kw = _make_kw()
        score, found, missing = kw._keyword_recall(
            "off-by-one error in range call", ["off-by-one", "range"]
        )
        assert score == pytest.approx(1.0)
        assert missing == []

    def test_partial(self) -> None:
        kw = _make_kw()
        score, found, missing = kw._keyword_recall(
            "off-by-one error", ["off-by-one", "range"]
        )
        assert score == pytest.approx(0.5)
        assert "range" in missing

    def test_none_found(self) -> None:
        kw = _make_kw()
        score, found, _ = kw._keyword_recall("unrelated text", ["off-by-one", "range"])
        assert score == pytest.approx(0.0)

    def test_case_insensitive(self) -> None:
        kw = _make_kw()
        score, found, _ = kw._keyword_recall("OFF-BY-ONE ERROR", ["off-by-one"])
        assert score == pytest.approx(1.0)

    def test_empty_required(self) -> None:
        kw = _make_kw()
        score, _, _ = kw._keyword_recall("some text", [])
        assert score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _detect_bug_type
# ---------------------------------------------------------------------------


class TestDetectBugType:
    def test_detects_off_by_one(self) -> None:
        kw = _make_kw()
        assert kw._detect_bug_type("This is an off-by-one error.") == "off-by-one"

    def test_detects_with_space_variant(self) -> None:
        kw = _make_kw()
        assert kw._detect_bug_type("This is an off by one error.") == "off-by-one"

    def test_detects_resource_leak(self) -> None:
        kw = _make_kw()
        assert kw._detect_bug_type("resource-leak detected.") == "resource-leak"

    def test_detects_infinite_loop(self) -> None:
        kw = _make_kw()
        assert kw._detect_bug_type("This causes an infinite-loop.") == "infinite-loop"

    def test_returns_none_for_unknown(self) -> None:
        kw = _make_kw()
        assert kw._detect_bug_type("The code looks fine.") is None


# ---------------------------------------------------------------------------
# ask_llm_to_find_bug
# ---------------------------------------------------------------------------


class TestAskLlmToFindBug:
    _CODE = "for i in range(1, len(arr) + 1):\n    print(arr[i])"

    def test_all_keywords_found_passes(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = (
            "The bug is an off-by-one error: range should stop at len(arr), "
            "not len(arr)+1. This causes an IndexError."
        )
        result = kw.ask_llm_to_find_bug(
            code=self._CODE,
            bug_description="off-by-one in range upper bound",
            required_keywords=["off-by-one", "IndexError"],
        )
        assert result["passed"] is True
        assert result["score"] == pytest.approx(1.0)
        assert result["missing_keywords"] == []

    def test_partial_recall_above_threshold_passes(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "There is an off-by-one error."
        result = kw.ask_llm_to_find_bug(
            code=self._CODE,
            bug_description="off-by-one",
            required_keywords=["off-by-one", "IndexError"],
            min_score=0.5,
        )
        assert result["passed"] is True

    def test_partial_recall_below_threshold_fails(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "Looks fine to me."
        result = kw.ask_llm_to_find_bug(
            code=self._CODE,
            bug_description="off-by-one",
            required_keywords=["off-by-one", "IndexError"],
            min_score=0.5,
        )
        assert result["passed"] is False

    def test_language_in_prompt(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "off-by-one"
        kw.ask_llm_to_find_bug(
            code=self._CODE,
            bug_description="off-by-one",
            required_keywords=["off-by-one"],
            language="Python",
        )
        call_args = kw.client.generate.call_args[0][0]
        assert "Python" in call_args

    def test_think_block_stripped(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = (
            "<think>some reasoning</think>off-by-one error with IndexError"
        )
        result = kw.ask_llm_to_find_bug(
            code=self._CODE,
            bug_description="off-by-one",
            required_keywords=["off-by-one", "IndexError"],
        )
        assert result["passed"] is True


# ---------------------------------------------------------------------------
# ask_llm_to_classify_bug
# ---------------------------------------------------------------------------


class TestAskLlmToClassifyBug:
    _CODE = "while True:\n    print('hello')"

    def test_correct_classification_passes(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "infinite-loop"
        result = kw.ask_llm_to_classify_bug(
            code=self._CODE,
            expected_bug_type="infinite-loop",
        )
        assert result["passed"] is True
        assert result["actual_bug_type"] == "infinite-loop"

    def test_wrong_classification_fails(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "logic-error"
        result = kw.ask_llm_to_classify_bug(
            code=self._CODE,
            expected_bug_type="infinite-loop",
        )
        assert result["passed"] is False

    def test_unknown_classification_fails(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "The code looks fine."
        result = kw.ask_llm_to_classify_bug(
            code=self._CODE,
            expected_bug_type="infinite-loop",
        )
        assert result["passed"] is False
        assert result["actual_bug_type"] is None

    def test_categories_in_prompt(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "infinite-loop"
        kw.ask_llm_to_classify_bug(code=self._CODE, expected_bug_type="infinite-loop")
        prompt = kw.client.generate.call_args[0][0]
        assert "off-by-one" in prompt
        assert "resource-leak" in prompt


# ---------------------------------------------------------------------------
# ask_llm_to_suggest_fix
# ---------------------------------------------------------------------------


class TestAskLlmToSuggestFix:
    _CODE = "f = open('data.txt', 'r')\ncontent = f.read()\nreturn content"

    def test_fix_keywords_found_passes(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = (
            "Use a 'with' statement so the file is automatically closed:\n"
            "with open('data.txt', 'r') as f:\n    content = f.read()"
        )
        result = kw.ask_llm_to_suggest_fix(
            code=self._CODE,
            expected_fix_keywords=["with", "close"],
        )
        assert result["passed"] is True

    def test_below_threshold_fails(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "Just call close() at the end."
        result = kw.ask_llm_to_suggest_fix(
            code=self._CODE,
            expected_fix_keywords=["with", "close"],
            min_score=1.0,
        )
        assert result["passed"] is False

    def test_language_in_prompt(self) -> None:
        kw = _make_kw()
        kw.client.generate.return_value = "with"
        kw.ask_llm_to_suggest_fix(
            code=self._CODE,
            expected_fix_keywords=["with"],
            language="Python",
        )
        prompt = kw.client.generate.call_args[0][0]
        assert "Python" in prompt


# ---------------------------------------------------------------------------
# assert_code_review_passed
# ---------------------------------------------------------------------------


class TestAssertCodeReviewPassed:
    def test_passes_when_passed_true(self) -> None:
        kw = _make_kw()
        kw.assert_code_review_passed({"passed": True})

    def test_raises_when_passed_false(self) -> None:
        kw = _make_kw()
        with pytest.raises(AssertionError, match="bug detection failed"):
            kw.assert_code_review_passed(
                {"passed": False, "reason": "recall=0.0"}, label="bug detection"
            )
