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
