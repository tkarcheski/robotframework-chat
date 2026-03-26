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

    def test_unclosed_think_tag_not_stripped_by_default(self) -> None:
        """parse_thinking only handles closed tags by default; unclosed pass through."""
        text = "<think>reasoning with no closing tag"
        clean, thinking = parse_thinking(text)
        assert clean == text  # unchanged — unclosed tag not touched
        assert thinking is None

    def test_unclosed_thinking_tag_not_stripped_by_default(self) -> None:
        text = "<thinking>reasoning with no closing tag"
        clean, thinking = parse_thinking(text)
        assert clean == text
        assert thinking is None

    def test_unclosed_think_tag_stripped_when_strip_unclosed(self) -> None:
        """strip_unclosed=True removes unclosed <think> at start of response."""
        text = "<think>reasoning with no closing tag"
        clean, thinking = parse_thinking(text, strip_unclosed=True)
        assert clean == ""
        assert thinking == "reasoning with no closing tag"

    def test_unclosed_thinking_tag_stripped_when_strip_unclosed(self) -> None:
        text = "<thinking>reasoning with no closing tag"
        clean, thinking = parse_thinking(text, strip_unclosed=True)
        assert clean == ""
        assert thinking == "reasoning with no closing tag"

    def test_unclosed_think_with_answer_after(self) -> None:
        """Unclosed <think> followed by actual answer content."""
        text = "<think>let me reason\nstep 1\nstep 2\n</think>The answer is 42."
        # This is actually a closed tag, should work with or without strip_unclosed
        clean, thinking = parse_thinking(text, strip_unclosed=True)
        assert clean.strip() == "The answer is 42."
        assert "step 1" in thinking

    def test_strip_unclosed_false_preserves_default_behavior(self) -> None:
        """Explicit strip_unclosed=False behaves like the default."""
        text = "<think>unclosed reasoning"
        clean, thinking = parse_thinking(text, strip_unclosed=False)
        assert clean == text
        assert thinking is None

    def test_think_literal_inside_json_not_stripped(self) -> None:
        """Literal <think> inside a JSON value must not be treated as a tag."""
        text = '{"score": 1, "reason": "Model used <think> tags"}'
        clean, thinking = parse_thinking(text)
        assert clean == text
        assert thinking is None


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

    def test_json_only_inside_think_block(self) -> None:
        text = '<think>{"score": 1.0, "reason": "correct"}</think>'
        result = extract_json(text)
        assert '"score"' in result
        assert '"reason"' in result

    def test_json_inside_think_with_reasoning(self) -> None:
        text = (
            "<think>Let me evaluate this response carefully. "
            '{"score": 0.5, "reason": "partially correct"} '
            "That seems right.</think>"
        )
        result = extract_json(text)
        assert '"score"' in result
        assert '"reason"' in result

    def test_unclosed_think_with_json_after_reasoning(self) -> None:
        """Last-resort: unclosed <think> prefix with JSON inside."""
        text = '<think>some reasoning {"score": 1, "reason": "ok"}'
        result = extract_json(text)
        assert '"score"' in result
        assert '"reason"' in result

    def test_unclosed_think_no_json(self) -> None:
        """Model answered in thinking block with no JSON at all (user's bug)."""
        text = (
            "<think> Okay, let's tackle this problem step by step. "
            "The absolute value remains 10349. </think>"
        )
        result = extract_json(text)
        # No JSON anywhere — should return cleaned text, not text with tags
        assert "<think>" not in result

    def test_unclosed_think_no_json_strips_tag(self) -> None:
        """Unclosed <think> with no JSON returns inner text, not raw tag."""
        text = "<think>just reasoning, no json here"
        result = extract_json(text)
        assert "<think>" not in result
        assert "just reasoning" in result

    def test_think_literal_inside_json_value(self) -> None:
        """Literal <think> in JSON must not break extraction (reviewer regression)."""
        text = '{"score": 1, "reason": "Model used <think> tags"}'
        result = extract_json(text)
        assert '"score"' in result
        assert "<think>" in result  # preserved inside the JSON string

    def test_line_leading_think_in_normal_text_preserved(self) -> None:
        """Literal <think> at line start inside normal content is not stripped."""
        text = "Here is how to use it:\n<think> is a special tag\nEnd."
        result = extract_json(text)
        # No JSON, no real thinking tag — original text returned unchanged
        assert "<think>" in result

    def test_clean_json_preferred_over_thinking_json(self) -> None:
        text = (
            '<think>{"score": 0, "reason": "wrong"}</think>'
            '{"score": 1, "reason": "right"}'
        )
        result = extract_json(text)
        assert '"right"' in result


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
