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
_UNCLOSED_THINK_PATTERN = re.compile(
    r"(?:^|\n)\s*<(?:think|thinking)>([\s\S]*)$"
)


def parse_thinking(text: str) -> tuple[str, Optional[str]]:
    """Separate thinking content from the answer.

    Handles both properly closed (``<think>...</think>``) and unclosed
    (``<think>...``) thinking tags.

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

    # Handle unclosed thinking tags (model started <think> but never closed it)
    unclosed = _UNCLOSED_THINK_PATTERN.search(clean)
    if unclosed:
        content = unclosed.group(1).strip()
        if content:
            blocks.append(content)
        clean = clean[: unclosed.start()]

    thinking: Optional[str] = None
    if blocks:
        thinking = "\n\n".join(blocks)

    return clean, thinking


def _find_json_in_text(text: str) -> str | None:
    """Try to find a JSON object in *text*.

    Returns the extracted JSON string, or ``None`` if no JSON is found.
    """
    # Markdown code blocks
    json_block_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
    matches = re.findall(json_block_pattern, text, re.DOTALL)
    if matches:
        return matches[0]

    # Bare JSON with score/reason fields
    json_pattern = r'(\{.*"score".*"reason".*?\})'
    matches = re.findall(json_pattern, text, re.DOTALL)
    if matches:
        return matches[0]

    # Any JSON object, pick the largest match
    json_pattern = r"(\{.*?\})"
    matches = re.findall(json_pattern, text, re.DOTALL)
    if matches:
        return max(matches, key=len)

    return None


def extract_json(text: str) -> str:
    """Extract JSON from text that may contain markdown or thinking tags.

    Handles:
    - Markdown code blocks (``\\`\\`\\`json...\\`\\`\\```)
    - Thinking tags (``<think>`` / ``<thinking>``) — closed or unclosed
    - JSON trapped inside thinking blocks (searched as fallback)
    - Text before/after JSON

    Returns the extracted JSON string, or the cleaned text if no JSON is found.
    """
    clean, thinking = parse_thinking(text)

    # First: look for JSON in the clean (non-thinking) text
    result = _find_json_in_text(clean)
    if result is not None:
        return result

    # Fallback: look for JSON inside the thinking content
    if thinking is not None:
        result = _find_json_in_text(thinking)
        if result is not None:
            return result

    # No JSON found anywhere — return cleaned text (thinking tags stripped)
    return clean


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
