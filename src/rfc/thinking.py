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

# Matches an unclosed <think>/<thinking> tag that was never closed.
# Only used as a last-resort fallback inside extract_json(), never in
# parse_thinking(), to avoid silently truncating normal model output
# that happens to contain a literal "<think>" token.
_UNCLOSED_THINK_PATTERN = re.compile(r"^\s*<(?:think|thinking)>([\s\S]*)$")


def parse_thinking(text: str) -> tuple[str, Optional[str]]:
    """Separate thinking content from the answer.

    Only handles properly closed ``<think>...</think>`` and
    ``<thinking>...</thinking>`` tags.  Unclosed tags are **not** stripped
    here to avoid false positives when content merely mentions these tokens.

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
    - Properly closed thinking tags (``<think>...</think>``)
    - JSON trapped inside thinking blocks (searched as fallback)
    - Unclosed ``<think>`` as a last resort (only when all else fails)
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

    # Last resort: handle unclosed <think> tags.  Only attempted here (not in
    # parse_thinking) to avoid truncating normal content that mentions <think>.
    unclosed = _UNCLOSED_THINK_PATTERN.match(clean)
    if unclosed:
        inner = unclosed.group(1)
        result = _find_json_in_text(inner)
        if result is not None:
            return result
        # No JSON inside the unclosed block either — return empty clean text
        # so callers never see raw <think> tags in error messages.
        return inner.strip()

    # No JSON found anywhere — return cleaned text (closed tags stripped)
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
