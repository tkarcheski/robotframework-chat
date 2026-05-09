"""Temporal reasoning evaluation keywords for Robot Framework.

Tests whether an LLM can perform calendar arithmetic, calculate durations
between dates, and order events chronologically. All three keyword types
use deterministic extraction (Tier 1 / verify:python) — no LLM judge.
"""

import re
from typing import Any, Dict, Optional

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data


# ---------------------------------------------------------------------------
# Private helpers (exported for unit tests)
# ---------------------------------------------------------------------------


def _contains_number(response: str, number: int) -> bool:
    """Return True if *response* contains *number* as a standalone integer.

    Uses word-boundary matching so "142" does not satisfy a search for "42".
    """
    pattern = r"(?<!\d)" + re.escape(str(number)) + r"(?!\d)"
    return bool(re.search(pattern, response))


def _contains_word(response: str, word: str) -> bool:
    """Case-insensitive word-boundary search for *word* in *response*."""
    if not response:
        return False
    pattern = r"\b" + re.escape(word) + r"\b"
    return bool(re.search(pattern, response, re.IGNORECASE))


def _position_of(response: str, word: str) -> int:
    """Return the character position of the first case-insensitive occurrence
    of *word* in *response*, or -1 if not found."""
    m = re.search(re.escape(word), response, re.IGNORECASE)
    return m.start() if m else -1


# ---------------------------------------------------------------------------
# Keyword library
# ---------------------------------------------------------------------------


_CALENDAR_PROMPT = """\
{question}

Respond with the month name and day number only. Do not include the year.
Example format: "March 31" or "April 14"."""

_DURATION_PROMPT = """\
{question}

Respond with a single integer. Do not include units or explanation."""

_SEQUENCE_PROMPT = """\
{question}

List the items in strict chronological order, one per line or separated by
commas. Include all items exactly as given."""


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
    # Tier 1: calendar arithmetic
    # ------------------------------------------------------------------

    @keyword("Check Calendar Answer")
    def check_calendar_answer(
        self,
        question: str,
        expected_month: str,
        expected_day: str,
    ) -> Dict[str, Any]:
        """Ask a date-offset question and verify the month and day in the reply.

        The LLM is instructed to reply with just the month and day.  The
        answer is considered correct when *both* the expected month name
        (case-insensitive, word-boundary match) and the expected day number
        (digit-boundary match) appear in the response.

        Args:
            question: The calendar arithmetic question.
            expected_month: Expected month name (e.g. ``"March"``).
            expected_day: Expected day number as a string (e.g. ``"31"``).

        Returns:
            Dict with keys: correct, expected_month, expected_day, response.
        """
        prompt = _CALENDAR_PROMPT.format(question=question)
        logger.info(f"Calendar arithmetic prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        month_ok = _contains_word(response, expected_month)
        day_ok = _contains_number(response, int(expected_day))
        correct = month_ok and day_ok

        emit_rfc_data("question", question[:200])
        emit_rfc_data("expected_month", expected_month)
        emit_rfc_data("expected_day", expected_day)
        emit_rfc_data("month_found", str(month_ok))
        emit_rfc_data("day_found", str(day_ok))
        emit_rfc_data("correct", str(correct))

        return {
            "correct": correct,
            "expected_month": expected_month,
            "expected_day": expected_day,
            "response": response,
        }

    # ------------------------------------------------------------------
    # Tier 1: duration calculation
    # ------------------------------------------------------------------

    @keyword("Check Duration Answer")
    def check_duration_answer(
        self,
        question: str,
        expected_count: int,
    ) -> Dict[str, Any]:
        """Ask a duration question and verify the integer appears in the reply.

        The LLM is instructed to reply with a single integer.  The answer is
        correct when *expected_count* appears as a standalone digit sequence
        in the response (digit-boundary match to prevent "159" matching "59").

        Args:
            question: The duration question (days, weeks, months).
            expected_count: Expected integer value.

        Returns:
            Dict with keys: correct, expected_count, response.
        """
        prompt = _DURATION_PROMPT.format(question=question)
        logger.info(f"Duration prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        correct = _contains_number(response, int(expected_count))

        emit_rfc_data("question", question[:200])
        emit_rfc_data("expected_count", str(expected_count))
        emit_rfc_data("correct", str(correct))

        return {
            "correct": correct,
            "expected_count": int(expected_count),
            "response": response,
        }

    # ------------------------------------------------------------------
    # Tier 1: sequence / chronological ordering
    # ------------------------------------------------------------------

    @keyword("Check Sequence Order")
    def check_sequence_order(
        self,
        question: str,
        anchor_first: str,
        anchor_last: str,
    ) -> Dict[str, Any]:
        """Ask the LLM to order items and verify that anchor_first precedes
        anchor_last in the output.

        The answer is correct when *anchor_first* appears at a lower character
        position than *anchor_last* in the response (case-insensitive), and
        both anchors are present.

        Args:
            question: The ordering question listing the items.
            anchor_first: Item that must appear earliest in the ordered output.
            anchor_last: Item that must appear latest in the ordered output.

        Returns:
            Dict with keys: correct, anchor_first, anchor_last, response.
        """
        prompt = _SEQUENCE_PROMPT.format(question=question)
        logger.info(f"Sequence ordering prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        pos_first = _position_of(response, anchor_first)
        pos_last = _position_of(response, anchor_last)

        correct = pos_first != -1 and pos_last != -1 and pos_first < pos_last

        emit_rfc_data("question", question[:200])
        emit_rfc_data("anchor_first", anchor_first)
        emit_rfc_data("anchor_last", anchor_last)
        emit_rfc_data("pos_first", str(pos_first))
        emit_rfc_data("pos_last", str(pos_last))
        emit_rfc_data("correct", str(correct))

        return {
            "correct": correct,
            "anchor_first": anchor_first,
            "anchor_last": anchor_last,
            "response": response,
        }
