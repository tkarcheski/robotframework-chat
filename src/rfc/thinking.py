"""Thinking token parser for LLM responses.

Extracts and separates ``<think>...</think>`` and ``<thinking>...</thinking>``
blocks from LLM output, commonly used by reasoning models (qwen3, deepseek).
"""

from __future__ import annotations

import re
from typing import Optional


_THINK_PATTERN = re.compile(
    r"<(?:think|thinking)>(.*?)</(?:think|thinking)>", re.DOTALL
)


def parse_thinking(text: str) -> tuple[str, Optional[str]]:
    """Separate thinking content from the answer.

    Args:
        text: Raw LLM response that may contain thinking tags.

    Returns:
        A tuple of ``(clean_answer, thinking_text)``.
        ``thinking_text`` is ``None`` when no non-empty thinking blocks are found.
    """
    blocks: list[str] = []
    for match in _THINK_PATTERN.finditer(text):
        content = match.group(1).strip()
        if content:
            blocks.append(content)

    clean = _THINK_PATTERN.sub("", text)

    thinking: Optional[str] = None
    if blocks:
        thinking = "\n\n".join(blocks)

    return clean, thinking


def extract_json(text: str) -> str:
    """Extract JSON from text that may contain markdown or thinking tags.

    Handles:
    - Markdown code blocks (``\\`\\`\\`json...\\`\\`\\```)
    - Thinking tags (``<think>`` / ``<thinking>``)
    - Text before/after JSON

    Returns the extracted JSON string, or the original text if no JSON is found.
    """
    text, _ = parse_thinking(text)

    # Try to find JSON in markdown code blocks
    json_block_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
    matches = re.findall(json_block_pattern, text, re.DOTALL)
    if matches:
        return matches[0]

    # Try to find bare JSON with score/reason fields
    json_pattern = r'(\{.*"score".*"reason".*?\})'
    matches = re.findall(json_pattern, text, re.DOTALL)
    if matches:
        return matches[0]

    # Last resort: any JSON object, pick the largest match
    json_pattern = r"(\{.*?\})"
    matches = re.findall(json_pattern, text, re.DOTALL)
    if matches:
        return max(matches, key=len)

    return text


def estimate_token_count(text: Optional[str]) -> int:
    """Estimate token count using whitespace splitting.

    This is a rough approximation. Ollama doesn't report thinking tokens
    separately, so we estimate from the extracted text.

    Args:
        text: Text to estimate tokens for.

    Returns:
        Estimated token count (0 for None or empty/whitespace-only strings).
    """
    if not text or not text.strip():
        return 0
    return len(text.split())
