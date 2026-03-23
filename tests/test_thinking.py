"""Tests for rfc.thinking — thinking token parser."""

from rfc.thinking import estimate_token_count, extract_json, parse_thinking


class TestParseThinking:
    def test_no_thinking_tags(self) -> None:
        text = "The answer is 42."
        clean, thinking = parse_thinking(text)
        assert clean == "The answer is 42."
        assert thinking is None

    def test_think_tags(self) -> None:
        text = "<think>Let me reason about this.</think>The answer is 42."
        clean, thinking = parse_thinking(text)
        assert clean == "The answer is 42."
        assert thinking == "Let me reason about this."

    def test_thinking_tags(self) -> None:
        text = "<thinking>Step 1: consider...</thinking>The answer is 42."
        clean, thinking = parse_thinking(text)
        assert clean == "The answer is 42."
        assert thinking == "Step 1: consider..."

    def test_multiline_thinking(self) -> None:
        text = "<think>\nLine 1\nLine 2\n</think>\nThe answer is 42."
        clean, thinking = parse_thinking(text)
        assert clean.strip() == "The answer is 42."
        assert "Line 1" in thinking
        assert "Line 2" in thinking

    def test_multiple_think_blocks(self) -> None:
        text = (
            "<think>First thought.</think>Part 1. <think>Second thought.</think>Part 2."
        )
        clean, thinking = parse_thinking(text)
        assert "Part 1." in clean
        assert "Part 2." in clean
        assert "First thought." in thinking
        assert "Second thought." in thinking

    def test_empty_think_tags(self) -> None:
        text = "<think></think>The answer is 42."
        clean, thinking = parse_thinking(text)
        assert clean == "The answer is 42."
        assert thinking is None  # Empty thinking is treated as None

    def test_mixed_tag_types(self) -> None:
        text = "<think>A</think>Mid<thinking>B</thinking>End"
        clean, thinking = parse_thinking(text)
        assert "Mid" in clean
        assert "End" in clean
        assert "A" in thinking
        assert "B" in thinking

    def test_whitespace_only_thinking(self) -> None:
        text = "<think>   \n  </think>The answer."
        clean, thinking = parse_thinking(text)
        assert clean.strip() == "The answer."
        assert thinking is None  # Whitespace-only treated as None

    def test_empty_string(self) -> None:
        clean, thinking = parse_thinking("")
        assert clean == ""
        assert thinking is None

    def test_thinking_with_special_chars(self) -> None:
        text = "<think>What about {json} and [arrays]?</think>Result."
        clean, thinking = parse_thinking(text)
        assert clean == "Result."
        assert thinking == "What about {json} and [arrays]?"


class TestExtractJson:
    def test_plain_json(self) -> None:
        text = '{"score": 1, "reason": "correct"}'
        assert extract_json(text) == text

    def test_json_in_markdown_block(self) -> None:
        text = '```json\n{"score": 1, "reason": "ok"}\n```'
        assert extract_json(text) == '{"score": 1, "reason": "ok"}'

    def test_json_in_markdown_block_no_lang(self) -> None:
        text = '```\n{"score": 0.5, "reason": "partial"}\n```'
        assert extract_json(text) == '{"score": 0.5, "reason": "partial"}'

    def test_thinking_tags_stripped(self) -> None:
        text = '<think>hmm let me think</think>\n{"score": 1, "reason": "ok"}'
        result = extract_json(text)
        assert '"score"' in result
        assert "<think>" not in result

    def test_text_before_json(self) -> None:
        text = 'I think the answer is {"score": 0.8, "reason": "mostly right"}'
        result = extract_json(text)
        assert '"score"' in result
        assert '"reason"' in result

    def test_bare_json_fallback_picks_largest(self) -> None:
        text = 'prefix {"a": 1} and {"reason": "good", "score": 1, "extra": true} end'
        result = extract_json(text)
        assert '"reason"' in result
        assert '"score"' in result

    def test_no_json_returns_text(self) -> None:
        text = "no json here at all"
        assert extract_json(text) == text


class TestEstimateTokenCount:
    def test_empty_string(self) -> None:
        assert estimate_token_count("") == 0

    def test_single_word(self) -> None:
        assert estimate_token_count("hello") == 1

    def test_sentence(self) -> None:
        count = estimate_token_count("The quick brown fox jumps over the lazy dog")
        assert count == 9

    def test_none_returns_zero(self) -> None:
        assert estimate_token_count(None) == 0  # type: ignore[arg-type]

    def test_whitespace_only(self) -> None:
        assert estimate_token_count("   \n\t  ") == 0
