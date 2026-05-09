"""Temporal reasoning evaluation keywords for Robot Framework.

Tests whether an LLM can correctly order historical events chronologically,
calculate elapsed time between events, and solve temporal word problems.

These capabilities underpin emerging LLM use-cases such as scheduling
assistants, deadline trackers, and historical-analysis tools.
"""

import re
from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .grader import Grader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SEQUENCE_PROMPT = """\
Order the following historical events from earliest to most recent.

Events:
{events}

Write the correct chronological order as a comma-separated list of letters \
on the first line only (for example: "B, A, D, C").

Order:"""

_DURATION_PROMPT = """\
{question}

Write only the number (as an integer) on the first line. No other text."""

_WORD_PROBLEM_PROMPT = """\
{question}

Write only the answer on the first line (the day of the week, time, or date). \
No other text."""

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

# Matches isolated single letters A-E (upper or lower); avoids matching
# letters embedded inside words such as "Answer" or "Before".
_LETTER_RE = re.compile(r"(?<![A-Za-z])([A-Ea-e])(?![A-Za-z])")

# Matches the first integer in a string (no leading sign required).
_INTEGER_RE = re.compile(r"\b(\d+)\b")


class TemporalReasoningKeywords:
    """Robot Framework keywords for temporal reasoning evaluation.

    Three grading strategies are provided:

    * **Sequence ordering** (Tier 1) — extract a letter sequence from the
      model's first response line and compare to ground truth.
    * **Duration calculation** (Tier 1) — extract the first integer from the
      model's response and compare to the expected year count.
    * **Temporal word problem** (Tier 1) — case-insensitive substring match
      of the expected answer against the model's first response line.
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = Grader(self.client)

    # ------------------------------------------------------------------
    # Tier 1: Sequence ordering
    # ------------------------------------------------------------------

    @keyword("Evaluate Sequence Order")
    def evaluate_sequence_order(
        self,
        events: List[str],
        expected_order: List[str],
    ) -> Dict[str, Any]:
        """Ask the LLM to order labelled events chronologically and verify.

        Events are presented as ``A) …``, ``B) …``, etc.  The model is
        asked to output a comma-separated sequence of letters on its first
        line (e.g., ``"B, A, D, C"``).

        Args:
            events: Event descriptions.  ``events[0]`` becomes label A,
                ``events[1]`` becomes label B, and so on (max 5 events).
            expected_order: Uppercase letters in the correct chronological
                order (e.g., ``["B", "A", "D", "C"]``).

        Returns:
            Dict with keys: ``extracted_order``, ``expected_order``,
            ``correct``, ``response``.
        """
        labels = "ABCDE"
        event_lines = "\n".join(
            f"{labels[i]}) {event}" for i, event in enumerate(events)
        )
        prompt = _SEQUENCE_PROMPT.format(events=event_lines)
        logger.info(f"Sequence ordering prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        extracted = _extract_letter_sequence(response, len(events))
        expected = [letter.upper() for letter in expected_order]
        correct = extracted == expected

        emit_rfc_data("expected_order", ", ".join(expected))
        emit_rfc_data(
            "extracted_order",
            ", ".join(extracted) if extracted is not None else "UNKNOWN",
        )
        emit_rfc_data("correct", str(correct))

        return {
            "extracted_order": extracted,
            "expected_order": expected,
            "correct": correct,
            "response": response,
        }

    # ------------------------------------------------------------------
    # Tier 1: Duration calculation
    # ------------------------------------------------------------------

    @keyword("Evaluate Duration")
    def evaluate_duration(
        self,
        question: str,
        expected_years: int,
    ) -> Dict[str, Any]:
        """Ask the LLM to calculate a time duration and verify the result.

        The model is asked to respond with a single integer on its first
        line.  The first integer found on that line is compared to
        ``expected_years``.

        Args:
            question: A question about years elapsed between two events.
            expected_years: The correct integer answer.

        Returns:
            Dict with keys: ``extracted_years``, ``expected_years``,
            ``correct``, ``response``.
        """
        prompt = _DURATION_PROMPT.format(question=question)
        logger.info(f"Duration prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        extracted = _extract_integer(response)
        expected = int(expected_years)
        correct = extracted == expected

        emit_rfc_data("question", question[:200])
        emit_rfc_data("expected_years", str(expected))
        emit_rfc_data(
            "extracted_years",
            str(extracted) if extracted is not None else "UNKNOWN",
        )
        emit_rfc_data("correct", str(correct))

        return {
            "extracted_years": extracted,
            "expected_years": expected,
            "correct": correct,
            "response": response,
        }

    # ------------------------------------------------------------------
    # Tier 1: Temporal word problem
    # ------------------------------------------------------------------

    @keyword("Evaluate Temporal Word Problem")
    def evaluate_temporal_word_problem(
        self,
        question: str,
        expected_answer: str,
    ) -> Dict[str, Any]:
        """Ask the LLM a temporal word problem and verify the first-line answer.

        The model is asked to write only the answer on its first line.
        Verification is a case-insensitive substring match of
        ``expected_answer`` against that first line.

        Args:
            question: A time-arithmetic word problem (day-of-week, time,
                or date calculation).
            expected_answer: The expected answer string (e.g., ``"Monday"``).

        Returns:
            Dict with keys: ``first_line``, ``expected_answer``,
            ``correct``, ``response``.
        """
        prompt = _WORD_PROBLEM_PROMPT.format(question=question)
        logger.info(f"Temporal word problem prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        first_line = (
            response.strip().splitlines()[0].strip() if response.strip() else ""
        )
        correct = expected_answer.lower() in first_line.lower()

        emit_rfc_data("question", question[:200])
        emit_rfc_data("expected_answer", expected_answer)
        emit_rfc_data("first_line_answer", first_line)
        emit_rfc_data("correct", str(correct))

        return {
            "first_line": first_line,
            "expected_answer": expected_answer,
            "correct": correct,
            "response": response,
        }


# ---------------------------------------------------------------------------
# Private extraction helpers (also exported for unit testing)
# ---------------------------------------------------------------------------


def _extract_letter_sequence(
    response: str, n: int
) -> Optional[List[str]]:
    """Extract a sequence of exactly *n* letters (A–E) from the first line.

    Returns a deduplicated list of uppercase letters in order of first
    appearance on the first response line.  Returns ``None`` if fewer
    than *n* distinct letters are found.
    """
    first_line = response.strip().splitlines()[0] if response.strip() else ""
    letters: List[str] = []
    seen: set = set()
    for m in _LETTER_RE.finditer(first_line):
        letter = m.group(1).upper()
        if letter not in seen:
            seen.add(letter)
            letters.append(letter)
    if len(letters) < n:
        return None
    return letters[:n]


def _extract_integer(response: str) -> Optional[int]:
    """Extract the first integer from the first non-empty line of a response."""
    first_line = response.strip().splitlines()[0] if response.strip() else ""
    m = _INTEGER_RE.search(first_line)
    if m:
        return int(m.group(1))
    return None
