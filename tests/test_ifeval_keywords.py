"""Tests for rfc.ifeval_keywords.IFEvalKeywords."""

from unittest.mock import MagicMock, patch

import pytest

from rfc.ifeval_keywords import IFEvalKeywords


class TestIFEvalKeywordsInit:
    @patch("rfc.ifeval_keywords.create_provider")
    def test_default_init(self, mock_create: MagicMock) -> None:
        kw = IFEvalKeywords()
        mock_create.assert_called_once_with(timeout=5400, max_retries=2)
        assert kw.client is mock_create.return_value

    @patch("rfc.ifeval_keywords.create_provider")
    def test_custom_timeout(self, mock_create: MagicMock) -> None:
        IFEvalKeywords(timeout=60, max_retries=1)
        mock_create.assert_called_once_with(timeout=60, max_retries=1)


class TestCheckSentenceCount:
    def test_exact_match(self) -> None:
        passed, reason = IFEvalKeywords.check_sentence_count(
            "The sun rises. It sets. Night falls.", 3
        )
        assert passed is True

    def test_too_few(self) -> None:
        passed, reason = IFEvalKeywords.check_sentence_count("Hello.", 3)
        assert passed is False
        assert "1" in reason and "3" in reason

    def test_too_many(self) -> None:
        passed, reason = IFEvalKeywords.check_sentence_count(
            "One. Two. Three. Four.", 3
        )
        assert passed is False

    def test_exclamation_and_question(self) -> None:
        passed, _ = IFEvalKeywords.check_sentence_count("What? Yes! Done.", 3)
        assert passed is True

    def test_empty_response(self) -> None:
        passed, _ = IFEvalKeywords.check_sentence_count("", 3)
        assert passed is False


class TestCheckAllCaps:
    def test_all_caps_passes(self) -> None:
        passed, _ = IFEvalKeywords.check_all_caps("HELLO WORLD")
        assert passed is True

    def test_mixed_case_fails(self) -> None:
        passed, _ = IFEvalKeywords.check_all_caps("Hello WORLD")
        assert passed is False

    def test_with_numbers_and_punctuation(self) -> None:
        passed, _ = IFEvalKeywords.check_all_caps("ABC 123! DEF.")
        assert passed is True

    def test_no_alpha_passes(self) -> None:
        passed, _ = IFEvalKeywords.check_all_caps("123 456")
        assert passed is True


class TestCheckBulletPoints:
    def test_correct_count_dash(self) -> None:
        text = "- One\n- Two\n- Three\n- Four\n- Five"
        passed, _ = IFEvalKeywords.check_bullet_points(text, 5)
        assert passed is True

    def test_correct_count_asterisk(self) -> None:
        text = "* One\n* Two\n* Three"
        passed, _ = IFEvalKeywords.check_bullet_points(text, 3)
        assert passed is True

    def test_wrong_count(self) -> None:
        text = "- One\n- Two\n- Three"
        passed, reason = IFEvalKeywords.check_bullet_points(text, 5)
        assert passed is False
        assert "3" in reason and "5" in reason

    def test_non_bullet_line_fails(self) -> None:
        text = "- One\nTwo\n- Three"
        passed, _ = IFEvalKeywords.check_bullet_points(text, 3)
        assert passed is False

    def test_blank_lines_ignored(self) -> None:
        text = "- One\n\n- Two\n\n- Three"
        passed, _ = IFEvalKeywords.check_bullet_points(text, 3)
        assert passed is True

    def test_unicode_bullet(self) -> None:
        text = "• One\n• Two"
        passed, _ = IFEvalKeywords.check_bullet_points(text, 2)
        assert passed is True


class TestCheckWordCount:
    def test_single_word(self) -> None:
        passed, _ = IFEvalKeywords.check_word_count("Paris", 1)
        assert passed is True

    def test_too_many(self) -> None:
        passed, _ = IFEvalKeywords.check_word_count("Hello World", 1)
        assert passed is False

    def test_twenty_words(self) -> None:
        text = " ".join(["word"] * 20)
        passed, _ = IFEvalKeywords.check_word_count(text, 20)
        assert passed is True

    def test_empty(self) -> None:
        passed, _ = IFEvalKeywords.check_word_count("", 1)
        assert passed is False


class TestCheckNumberedList:
    def test_correct_sequence(self) -> None:
        text = "1. Mon\n2. Tue\n3. Wed\n4. Thu\n5. Fri\n6. Sat\n7. Sun"
        passed, _ = IFEvalKeywords.check_numbered_list(text, 7)
        assert passed is True

    def test_parenthesis_format(self) -> None:
        text = "1) Mon\n2) Tue\n3) Wed"
        passed, _ = IFEvalKeywords.check_numbered_list(text, 3)
        assert passed is True

    def test_missing_number(self) -> None:
        text = "1. Mon\n2. Tue\n4. Thu"
        passed, reason = IFEvalKeywords.check_numbered_list(text, 3)
        assert passed is False

    def test_wrong_count(self) -> None:
        text = "1. Mon\n2. Tue"
        passed, _ = IFEvalKeywords.check_numbered_list(text, 7)
        assert passed is False

    def test_extra_prose_fails(self) -> None:
        text = (
            "Here are the days:\n1. Mon\n2. Tue\n3. Wed\n4. Thu\n5. Fri\n6. Sat\n7. Sun"
        )
        passed, reason = IFEvalKeywords.check_numbered_list(text, 7)
        assert passed is False
        assert "Non-numbered" in reason


class TestCheckParagraphCount:
    def test_two_paragraphs(self) -> None:
        text = "First paragraph here.\n\nSecond paragraph here."
        passed, _ = IFEvalKeywords.check_paragraph_count(text, 2)
        assert passed is True

    def test_one_paragraph_fails(self) -> None:
        text = "Just one paragraph."
        passed, _ = IFEvalKeywords.check_paragraph_count(text, 2)
        assert passed is False

    def test_three_paragraphs_fails(self) -> None:
        text = "One.\n\nTwo.\n\nThree."
        passed, _ = IFEvalKeywords.check_paragraph_count(text, 2)
        assert passed is False

    def test_multiple_blank_lines(self) -> None:
        text = "First.\n\n\n\nSecond."
        passed, _ = IFEvalKeywords.check_paragraph_count(text, 2)
        assert passed is True


class TestCheckForbiddenLetter:
    def test_no_e_passes(self) -> None:
        passed, _ = IFEvalKeywords.check_forbidden_letter(
            "Bright sun falls upon ground.", "e"
        )
        assert passed is True

    def test_has_e_fails(self) -> None:
        passed, _ = IFEvalKeywords.check_forbidden_letter(
            "The sunset is beautiful.", "e"
        )
        assert passed is False

    def test_case_insensitive(self) -> None:
        passed, _ = IFEvalKeywords.check_forbidden_letter("EVERY day is good.", "e")
        assert passed is False

    def test_empty_passes(self) -> None:
        passed, _ = IFEvalKeywords.check_forbidden_letter("", "e")
        assert passed is True


class TestCheckSentenceStart:
    def test_all_start_with_word(self) -> None:
        text = "Dogs are loyal. Dogs love people. Dogs are friendly."
        passed, _ = IFEvalKeywords.check_sentence_start(text, "Dogs")
        assert passed is True

    def test_one_missing(self) -> None:
        text = "Dogs are loyal. They love people. Dogs are friendly."
        passed, reason = IFEvalKeywords.check_sentence_start(text, "Dogs")
        assert passed is False
        assert "They" in reason or "2" in reason

    def test_case_sensitive(self) -> None:
        text = "dogs are loyal."
        passed, _ = IFEvalKeywords.check_sentence_start(text, "Dogs")
        assert passed is False


class TestCheckEndsWithWord:
    def test_ends_correctly(self) -> None:
        passed, _ = IFEvalKeywords.check_ends_with_word("The ocean is vast. END", "END")
        assert passed is True

    def test_ends_wrong(self) -> None:
        passed, _ = IFEvalKeywords.check_ends_with_word("The ocean is vast.", "END")
        assert passed is False

    def test_trailing_whitespace(self) -> None:
        passed, _ = IFEvalKeywords.check_ends_with_word(
            "The ocean is vast. END  \n", "END"
        )
        assert passed is True

    def test_trailing_punctuation(self) -> None:
        passed, _ = IFEvalKeywords.check_ends_with_word(
            "The ocean is vast. END.", "END"
        )
        assert passed is True


class TestCheckAllLowercase:
    def test_all_lower_passes(self) -> None:
        passed, _ = IFEvalKeywords.check_all_lowercase("gravity pulls things down.")
        assert passed is True

    def test_has_uppercase_fails(self) -> None:
        passed, _ = IFEvalKeywords.check_all_lowercase("Gravity pulls things down.")
        assert passed is False

    def test_with_numbers_passes(self) -> None:
        passed, _ = IFEvalKeywords.check_all_lowercase("there are 9 planets.")
        assert passed is True


class TestCheckNoDigits:
    def test_no_digits_passes(self) -> None:
        passed, _ = IFEvalKeywords.check_no_digits("Spring, summer, fall, winter.")
        assert passed is True

    def test_has_digit_fails(self) -> None:
        passed, _ = IFEvalKeywords.check_no_digits("There are 4 seasons.")
        assert passed is False

    def test_empty_passes(self) -> None:
        passed, _ = IFEvalKeywords.check_no_digits("")
        assert passed is True


class TestCheckIFEvalConstraint:
    @patch("rfc.ifeval_keywords.create_provider")
    def test_dispatches_sentence_count(self, mock_create: MagicMock) -> None:
        kw = IFEvalKeywords()
        result = kw.check_ifeval_constraint("One. Two. Three.", "sentence_count", "3")
        assert result["passed"] is True
        assert result["constraint"] == "sentence_count"

    @patch("rfc.ifeval_keywords.create_provider")
    def test_dispatches_all_caps(self, mock_create: MagicMock) -> None:
        kw = IFEvalKeywords()
        result = kw.check_ifeval_constraint("HELLO WORLD", "all_caps")
        assert result["passed"] is True

    @patch("rfc.ifeval_keywords.create_provider")
    def test_unknown_constraint_raises(self, mock_create: MagicMock) -> None:
        kw = IFEvalKeywords()
        with pytest.raises(ValueError, match="Unknown constraint"):
            kw.check_ifeval_constraint("hello", "nonexistent")

    @patch("rfc.ifeval_keywords.create_provider")
    def test_missing_expected_value_raises(self, mock_create: MagicMock) -> None:
        kw = IFEvalKeywords()
        for constraint in (
            "sentence_count",
            "bullet_points",
            "word_count",
            "numbered_list",
            "paragraph_count",
            "forbidden_letter",
            "sentence_start",
            "ends_with_word",
        ):
            with pytest.raises(ValueError, match="requires a non-empty"):
                kw.check_ifeval_constraint("hello", constraint)


class TestAskAndCheckConstraint:
    @patch("rfc.ifeval_keywords.emit_rfc_data")
    @patch("rfc.ifeval_keywords.create_provider")
    def test_passing_constraint(
        self, mock_create: MagicMock, mock_emit: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client.generate.return_value = "HELLO WORLD"
        mock_create.return_value = mock_client
        kw = IFEvalKeywords()
        result = kw.ask_and_check_constraint("Say hello in caps", "all_caps")
        assert result["passed"] is True
        mock_emit.assert_any_call("actual_answer", "HELLO WORLD")
        mock_emit.assert_any_call("score", "1")

    @patch("rfc.ifeval_keywords.emit_rfc_data")
    @patch("rfc.ifeval_keywords.create_provider")
    def test_failing_constraint(
        self, mock_create: MagicMock, mock_emit: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client.generate.return_value = "Hello World"
        mock_create.return_value = mock_client
        kw = IFEvalKeywords()
        result = kw.ask_and_check_constraint("Say hello in caps", "all_caps")
        assert result["passed"] is False
        mock_emit.assert_any_call("score", "0")

    @patch("rfc.ifeval_keywords.emit_rfc_data")
    @patch("rfc.ifeval_keywords.create_provider")
    def test_strips_thinking_tags(
        self, mock_create: MagicMock, mock_emit: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client.generate.return_value = "<think>hmm</think>HELLO WORLD"
        mock_create.return_value = mock_client
        kw = IFEvalKeywords()
        result = kw.ask_and_check_constraint("Say hello in caps", "all_caps")
        assert result["passed"] is True


class TestAssertIFEvalPassed:
    @patch("rfc.ifeval_keywords.create_provider")
    def test_passed_true_no_raise(self, mock_create: MagicMock) -> None:
        kw = IFEvalKeywords()
        kw.assert_ifeval_passed({"passed": True, "reason": "ok", "constraint": "x"})

    @patch("rfc.ifeval_keywords.create_provider")
    def test_passed_false_raises(self, mock_create: MagicMock) -> None:
        kw = IFEvalKeywords()
        with pytest.raises(AssertionError, match="failed"):
            kw.assert_ifeval_passed(
                {"passed": False, "reason": "bad", "constraint": "x"}
            )


class TestMultilingualConstraints:
    """Verify constraint checkers work across languages (Spanish, German, Japanese)."""

    def test_spanish_word_count(self) -> None:
        spanish_text = "El gato y el perro juegan juntos"  # 7 words
        passed, _ = IFEvalKeywords.check_word_count(spanish_text, 7)
        assert passed is True

    def test_spanish_bullet_points(self) -> None:
        spanish_bullets = "- Manzana\n- Plátano\n- Naranja"
        passed, _ = IFEvalKeywords.check_bullet_points(spanish_bullets, 3)
        assert passed is True

    def test_spanish_paragraph_count(self) -> None:
        spanish_para = "Primera sección del texto.\n\nSegunda sección del texto."
        passed, _ = IFEvalKeywords.check_paragraph_count(spanish_para, 2)
        assert passed is True

    def test_german_word_count(self) -> None:
        german_text = "Der Hund und die Katze spielen zusammen"  # 7 words
        passed, _ = IFEvalKeywords.check_word_count(german_text, 7)
        assert passed is True

    def test_german_numbered_list(self) -> None:
        german_list = "1. Apfel\n2. Banane\n3. Kirsche"
        passed, _ = IFEvalKeywords.check_numbered_list(german_list, 3)
        assert passed is True

    def test_german_ends_with_word(self) -> None:
        german_text = "Dies ist eine Aussage ENDE"
        passed, _ = IFEvalKeywords.check_ends_with_word(german_text, "ENDE")
        assert passed is True

    def test_japanese_word_count_no_spaces(self) -> None:
        japanese_text = "私は毎日学校に行きます"  # No spaces; split() returns 1 element
        passed, count_result = IFEvalKeywords.check_word_count(japanese_text, 1)
        assert passed is True  # Single token when split by whitespace

    def test_japanese_bullet_points_with_latin_numerals(self) -> None:
        japanese_bullets = "- りんご\n- バナナ\n- オレンジ"
        passed, _ = IFEvalKeywords.check_bullet_points(japanese_bullets, 3)
        assert passed is True

    def test_japanese_paragraph_count(self) -> None:
        japanese_para = "最初の段落です。\n\n2番目の段落です。"
        passed, _ = IFEvalKeywords.check_paragraph_count(japanese_para, 2)
        assert passed is True

    def test_cross_language_bullet_points_english(self) -> None:
        """Verify format constraint works regardless of language."""
        english_bullets = "- Apple\n- Banana\n- Cherry\n- Date"
        passed, _ = IFEvalKeywords.check_bullet_points(english_bullets, 4)
        assert passed is True
