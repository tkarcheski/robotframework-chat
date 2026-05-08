"""Temporal reasoning evaluation keywords for Robot Framework.

Tests whether an LLM can correctly solve date arithmetic, order historical
events chronologically, and estimate durations of well-known time periods.

All grading is deterministic (Tier 1 / verify:python): answers are extracted
from the first line of the response via regex and compared to precomputed
correct values.
"""

import re
from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data

# Extract the first non-negative integer from a line of text.
# Handles:  "67", "67 days", "Answer: 67", "67.", "The answer is 67".
_INTEGER_RE = re.compile(r"\b(\d+)\b")

# Extract individual letters A–D from a line (used for event ordering).
_LETTER_SEQ_RE = re.compile(r"\b([A-Da-d])\b")

_DATE_ARITHMETIC_PROMPT = """\
Solve the following date arithmetic problem.

{question}

Respond with ONLY the numeric answer as a single integer on the very first \
line — no units, no explanation, no punctuation.

For example, if the answer is 67, write:
67

Answer:"""

_SEQUENCE_ORDER_PROMPT = """\
You are given four historical events labelled A, B, C, and D.
Place them in chronological order from earliest (oldest) to latest (most recent).

{events}

Respond with ONLY the four letters in chronological order, separated by \
commas, on the very first line.

Example format: D, A, B, C

Order:"""

_DURATION_PROMPT = """\
Answer the following question about a well-known time duration.

{question}

Respond with ONLY the numeric answer as a single integer on the very first \
line — no units, no explanation, no punctuation.

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

    # ------------------------------------------------------------------
    # Tier 1: deterministic answer extraction
    # ------------------------------------------------------------------

    @keyword("Solve Date Arithmetic")
    def solve_date_arithmetic(
        self,
        question: str,
        expected: int,
        tolerance: int = 0,
    ) -> Dict[str, Any]:
        """Ask the LLM a date arithmetic question and verify the numeric answer.

        The LLM is instructed to respond with a single integer on the first
        line. The integer is extracted deterministically and compared to the
        expected value within the given tolerance.

        Args:
            question: A date arithmetic question with a unique integer answer.
            expected: The correct integer answer.
            tolerance: Acceptable deviation from the expected answer (default 0).

        Returns:
            Dict with keys: answer, correct, response, expected.
        """
        prompt = _DATE_ARITHMETIC_PROMPT.format(question=question)
        logger.info(f"Date arithmetic prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        answer = _extract_integer(response)
        correct = answer is not None and abs(answer - int(expected)) <= int(tolerance)

        emit_rfc_data("question", question[:200])
        emit_rfc_data("expected", str(expected))
        emit_rfc_data("actual_answer", str(answer) if answer is not None else "NONE")
        emit_rfc_data("tolerance", str(tolerance))
        emit_rfc_data("correct", str(correct))

        return {
            "answer": answer,
            "correct": correct,
            "response": response,
            "expected": int(expected),
        }

    @keyword("Check Event Ordering")
    def check_event_ordering(
        self,
        events: str,
        expected_order: str,
    ) -> Dict[str, Any]:
        """Ask the LLM to order historical events chronologically and verify.

        Events are labelled A–D and the LLM must output them as a
        comma-separated sequence on the first line (e.g. ``"D, A, B, C"``).
        The sequence is extracted and compared to the expected ordering.

        Args:
            events: Multi-line string of events labelled A, B, C, D with
                their descriptions (years should NOT be included — the LLM
                must recall the dates from training knowledge).
            expected_order: Expected chronological sequence as a
                comma-separated string, e.g. ``"D, A, B, C"``.

        Returns:
            Dict with keys: actual_order, correct, response, expected_order.
        """
        prompt = _SEQUENCE_ORDER_PROMPT.format(events=events)
        logger.info(f"Event ordering prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        actual = _extract_letter_sequence(response)
        expected = _normalize_order(expected_order)
        correct = actual == expected

        emit_rfc_data("events", events[:400])
        emit_rfc_data("expected_order", ", ".join(expected))
        emit_rfc_data("actual_order", ", ".join(actual) if actual else "UNKNOWN")
        emit_rfc_data("correct", str(correct))

        return {
            "actual_order": actual,
            "correct": correct,
            "response": response,
            "expected_order": expected,
        }

    @keyword("Estimate Duration")
    def estimate_duration(
        self,
        question: str,
        expected: int,
        tolerance: int = 1,
    ) -> Dict[str, Any]:
        """Ask the LLM to state a well-known duration and verify within tolerance.

        Useful for quantities like "how many years did WWII last?" where the
        correct answer is well-established but reasonable rounding differs
        by at most a small margin.

        Args:
            question: A question about a well-known time duration.
            expected: The correct integer answer.
            tolerance: Acceptable deviation (default 1 to allow rounding).

        Returns:
            Dict with keys: answer, correct, response, expected.
        """
        prompt = _DURATION_PROMPT.format(question=question)
        logger.info(f"Duration estimation prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        answer = _extract_integer(response)
        correct = answer is not None and abs(answer - int(expected)) <= int(tolerance)

        emit_rfc_data("question", question[:200])
        emit_rfc_data("expected", str(expected))
        emit_rfc_data("actual_answer", str(answer) if answer is not None else "NONE")
        emit_rfc_data("tolerance", str(tolerance))
        emit_rfc_data("correct", str(correct))

        return {
            "answer": answer,
            "correct": correct,
            "response": response,
            "expected": int(expected),
        }


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------


def _extract_integer(response: str) -> Optional[int]:
    """Extract the first integer from the first non-empty line of a response.

    Returns ``None`` if no integer is found, which callers treat as a
    grading failure.
    """
    first_line = response.strip().splitlines()[0] if response.strip() else ""
    m = _INTEGER_RE.search(first_line)
    if m:
        return int(m.group(1))
    return None


def _extract_letter_sequence(response: str) -> List[str]:
    """Extract an ordered sequence of letters A–D from the first line."""
    first_line = response.strip().splitlines()[0] if response.strip() else ""
    letters = _LETTER_SEQ_RE.findall(first_line)
    return [letter.upper() for letter in letters]


def _normalize_order(order_str: str) -> List[str]:
    """Parse a comma-separated letter-order string into uppercase letter list."""
    letters = _LETTER_SEQ_RE.findall(order_str)
    return [letter.upper() for letter in letters]
