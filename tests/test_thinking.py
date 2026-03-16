"""Tests for rfc.thinking — thinking token parser."""

import pytest

from rfc.thinking import estimate_token_count, parse_thinking


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
        text = "<think>First thought.</think>Part 1. <think>Second thought.</think>Part 2."
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
