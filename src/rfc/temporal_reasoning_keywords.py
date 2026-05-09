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

# Matches a negation word immediately before the cursor position.
# Input is normalised before matching (typographic apostrophes → ASCII),
# so only ASCII apostrophes are needed here.
_NEGATION_BEFORE_RE = re.compile(
    r"\b(?:not|no|never|isn't|wasn't|don't|doesn't)\s*$",
    re.IGNORECASE,
)

# Maps typographic apostrophe variants to the ASCII apostrophe so that
# _NEGATION_BEFORE_RE can use a single simple pattern.
_SMART_APOSTROPHES = str.maketrans(
    {
        0x2018: 0x0027,  # LEFT single quotation mark  ‘
        0x2019: 0x0027,  # RIGHT single quotation mark ‘
        0x02BC: 0x0027,  # modifier letter apostrophe  ʼ
        0x0060: 0x0027,  # grave accent                `
        0x00B4: 0x0027,  # acute accent                ´
    }
)


class TemporalReasoningKeywords:
    """Robot Framework keywords for temporal reasoning evaluation.

    Three grading strategies are provided:

    * **Sequence ordering** (Tier 1) — extract a letter sequence from the
      model's first response line and compare to ground truth.  Requires
      exactly ``n`` distinct letters; extra labels are rejected.
    * **Duration calculation** (Tier 1) — extract the first integer from the
      model's response and compare to the expected year count.
    * **Temporal word problem** (Tier 1) — whole-word match of the expected
      answer against the model's first response line, with negation detection
      (``"Not Monday"`` does not pass when ``"Monday"`` is expected).
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
        Verification uses whole-word matching with negation detection:
        ``"Not Monday"`` does **not** pass when the expected answer is
        ``"Monday"``.

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
        correct = _word_match(first_line, expected_answer)

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


def _extract_letter_sequence(response: str, n: int) -> Optional[List[str]]:
    """Extract a sequence of exactly *n* distinct letters (A–E) from the first line.

    Requires **exactly** *n* label tokens with no duplicates.  Returns ``None``
    when the raw token count differs from *n* (too few, too many, or a repeated
    label that deduplication would otherwise mask — e.g. ``"B, A, D, C, C"``
    is rejected for a 4-event case even though it deduplicates to 4 items).
    """
    first_line = response.strip().splitlines()[0] if response.strip() else ""
    all_tokens = [m.group(1).upper() for m in _LETTER_RE.finditer(first_line)]
    if len(all_tokens) != n or len(set(all_tokens)) != n:
        return None
    return all_tokens


def _extract_integer(response: str) -> Optional[int]:
    """Extract the first integer from the first non-empty line of a response."""
    first_line = response.strip().splitlines()[0] if response.strip() else ""
    m = _INTEGER_RE.search(first_line)
    if m:
        return int(m.group(1))
    return None


def _word_match(text: str, target: str) -> bool:
    """Return True iff *target* appears as a whole word in *text* and is not
    immediately preceded by a negation word (not/no/never/isn't/wasn't/…).

    Typographic apostrophes (U+2019 etc.) are normalised to ASCII ``'`` before
    matching so that LLM contractions like ``isn't`` are detected reliably.
    This prevents answers like ``"Not Monday"`` or ``"isn't Monday"`` from
    matching when the expected answer is ``"Monday"``.
    """
    normalised = text.translate(_SMART_APOSTROPHES)
    m = re.search(r"\b" + re.escape(target) + r"\b", normalised, re.IGNORECASE)
    if not m:
        return False
    before = normalised[: m.start()].rstrip()
    return not bool(_NEGATION_BEFORE_RE.search(before))
