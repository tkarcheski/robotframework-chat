"""Temporal reasoning evaluation keywords for Robot Framework.

Tests whether an LLM can solve time/date arithmetic problems and correctly
order historical events chronologically. Both keyword types use deterministic
Python-backed grading (Tier 1 / verify:python).
"""

import re
from typing import Any, Dict, Optional

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data

# Matches the first standalone integer, tolerating comma thousands-separators
# (e.g. "3,600" is treated as 3600, not 3).
_INTEGER_RE = re.compile(r"\b(\d[\d,]*\d|\d)\b")

# Matches "A" or "B" anchored to the start of the first non-empty line.
# Word boundary prevents matching "Be careful" or "About" as a choice letter.
_AB_CHOICE_RE = re.compile(r"^\s*([ABab])\b")

_ARITHMETIC_PROMPT = """\
{question}

Respond with a single integer and nothing else. Do not include units, \
explanations, or punctuation."""

_CHRONOLOGY_PROMPT = """\
{question}

Respond with only the letter A or B on the first line, then give a brief \
one-sentence explanation.

Answer:"""


class TemporalReasoningKeywords:
    """Robot Framework keywords for temporal reasoning evaluation."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))

    @keyword("Evaluate Temporal Arithmetic")
    def evaluate_temporal_arithmetic(
        self,
        question: str,
        expected_value: int,
    ) -> Dict[str, Any]:
        """Ask the LLM a time/date arithmetic question and verify the integer answer.

        The prompt explicitly requests a single integer. The first integer found
        in the response (after removing comma thousands-separators) is compared
        to *expected_value*.

        Args:
            question: A time/date arithmetic question with a known integer answer.
            expected_value: The correct integer answer.

        Returns:
            Dict with keys: extracted_value, correct, response, expected.
        """
        expected_value = int(expected_value)

        prompt = _ARITHMETIC_PROMPT.format(question=question)
        logger.info(f"Temporal arithmetic prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        extracted = _extract_first_integer(response)
        correct = extracted == expected_value

        emit_rfc_data("question", question[:200])
        emit_rfc_data("expected_value", str(expected_value))
        emit_rfc_data(
            "extracted_value", str(extracted) if extracted is not None else "NONE"
        )
        emit_rfc_data("correct", str(correct))

        return {
            "extracted_value": extracted,
            "correct": correct,
            "response": response,
            "expected": expected_value,
        }

    @keyword("Evaluate Chronological Order")
    def evaluate_chronological_order(
        self,
        question: str,
        expected_letter: str,
    ) -> Dict[str, Any]:
        """Ask the LLM which of two events (A or B) occurred first and verify.

        Args:
            question: A question presenting two dated events, asking which came
                first. Should instruct the model to answer with just A or B.
            expected_letter: ``"A"`` or ``"B"``.

        Returns:
            Dict with keys: chosen_letter, correct, response, expected.

        Raises:
            ValueError: If expected_letter is not ``"A"`` or ``"B"``.
        """
        expected_letter = expected_letter.strip().upper()
        if expected_letter not in {"A", "B"}:
            raise ValueError(
                f"expected_letter must be 'A' or 'B', got {expected_letter!r}"
            )

        prompt = _CHRONOLOGY_PROMPT.format(question=question)
        logger.info(f"Chronological order prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        chosen = _extract_choice_letter(response)
        correct = chosen == expected_letter

        emit_rfc_data("question", question[:200])
        emit_rfc_data("expected_letter", expected_letter)
        emit_rfc_data("chosen_letter", chosen or "UNKNOWN")
        emit_rfc_data("correct", str(correct))

        return {
            "chosen_letter": chosen,
            "correct": correct,
            "response": response,
            "expected": expected_letter,
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _extract_first_integer(response: str) -> Optional[int]:
    """Return the integer value of the first digit sequence in *response*.

    Comma thousands-separators are stripped before conversion so that
    "3,600 seconds" yields 3600, not 3.  Returns ``None`` when no digit
    sequence is found.
    """
    if not response:
        return None
    m = _INTEGER_RE.search(response)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _extract_choice_letter(response: str) -> Optional[str]:
    """Return ``'A'`` or ``'B'`` extracted from the first non-empty line.

    The prompt instructs the model to place the letter first. Returning
    ``None`` signals a non-compliant response; callers treat that as failure.
    """
    if not response:
        return None
    stripped = response.strip()
    if not stripped:
        return None
    first_line = stripped.splitlines()[0]
    m = _AB_CHOICE_RE.search(first_line)
    return m.group(1).upper() if m else None
