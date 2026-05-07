"""Robot Framework keywords for LLM temporal reasoning tests."""

import re
from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import parse_thinking

_MONTHS: Dict[str, str] = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
}


class TemporalReasoningKeywords:
    """Keywords for testing LLM temporal reasoning accuracy.

    Grades by extracting the answer from the LLM response with regex and
    comparing against the known-correct value — no secondary LLM grader
    required (Tier 1).
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    _NUMBER_PATTERN = re.compile(r"\b(\d+)\b")
    _DATE_ISO_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
    _DATE_MDY_PATTERN = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
    _DATE_TEXT_PATTERN = re.compile(
        r"\b(January|February|March|April|May|June|July|August"
        r"|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b",
        re.IGNORECASE,
    )
    _WEEKDAY_PATTERN = re.compile(
        r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
        re.IGNORECASE,
    )

    def __init__(self, timeout: Optional[int] = None, max_retries: int = 2) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_number(self, text: str) -> Optional[int]:
        """Return the first integer found in *text*, or None."""
        m = self._NUMBER_PATTERN.search(text)
        return int(m.group(1)) if m else None

    def _extract_date(self, text: str) -> Optional[str]:
        """Extract a date from *text* and return it as YYYY-MM-DD, or None."""
        # Priority 1: ISO format already
        m = self._DATE_ISO_PATTERN.search(text)
        if m:
            return m.group(1)

        # Priority 2: written-out month (e.g. "February 14, 2024")
        m2 = self._DATE_TEXT_PATTERN.search(text)
        if m2:
            month = _MONTHS.get(m2.group(1).lower(), "00")
            day = m2.group(2).zfill(2)
            year = m2.group(3)
            return f"{year}-{month}-{day}"

        # Priority 3: MM/DD/YYYY
        m3 = self._DATE_MDY_PATTERN.search(text)
        if m3:
            month, day, year = m3.group(1), m3.group(2), m3.group(3)
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

        return None

    def _extract_weekday(self, text: str) -> Optional[str]:
        """Return the first weekday name found in *text*, title-cased, or None."""
        m = self._WEEKDAY_PATTERN.search(text)
        return m.group(1).title() if m else None

    def _emit_and_return(
        self,
        passed: bool,
        expected: str,
        reason: str,
        extra: Dict[str, Any],
    ) -> Dict[str, Any]:
        emit_rfc_data("score", str(1 if passed else 0))
        emit_rfc_data("expected_answer", expected)
        emit_rfc_data("grading_reason", reason)
        logger.info(f"Temporal grading: {reason}, passed={passed}")
        return {"passed": passed, "reason": reason, **extra}

    # ------------------------------------------------------------------
    # Public keywords
    # ------------------------------------------------------------------

    @keyword("Ask Temporal Numeric Question")
    def ask_temporal_numeric_question(
        self, question: str, expected_number: int
    ) -> Dict[str, Any]:
        """Ask a question whose answer is a single integer.

        Suitable for: day counts, age calculations, hour totals, leap-year
        day counts, etc.

        Args:
            question: Temporal question with a numeric answer.
            expected_number: Correct integer answer.

        Returns:
            Dict with ``passed``, ``actual_number``, ``reason``.
        """
        logger.info(f"Temporal numeric question: {question[:120]}")
        raw = self.client.generate(question)
        clean, _ = parse_thinking(raw, strip_unclosed=True)
        emit_rfc_data("actual_answer", clean[:500])

        actual = self._extract_number(clean)
        passed = actual == int(expected_number)
        reason = f"extracted={actual}, expected={expected_number}"
        return self._emit_and_return(
            passed, str(expected_number), reason, {"actual_number": actual}
        )

    @keyword("Ask Temporal Date Question")
    def ask_temporal_date_question(
        self, question: str, expected_date: str
    ) -> Dict[str, Any]:
        """Ask a date-arithmetic question and check the result.

        The question should hint at the expected format so the LLM returns
        something parseable (ISO or written-out month are both accepted).

        Args:
            question: Temporal question whose answer is a calendar date.
            expected_date: Correct date in YYYY-MM-DD format.

        Returns:
            Dict with ``passed``, ``actual_date``, ``reason``.
        """
        logger.info(f"Temporal date question: {question[:120]}")
        raw = self.client.generate(question)
        clean, _ = parse_thinking(raw, strip_unclosed=True)
        emit_rfc_data("actual_answer", clean[:500])

        actual = self._extract_date(clean)
        passed = actual == expected_date
        reason = f"extracted={actual!r}, expected={expected_date!r}"
        return self._emit_and_return(
            passed, expected_date, reason, {"actual_date": actual}
        )

    @keyword("Ask Temporal Weekday Question")
    def ask_temporal_weekday_question(
        self, question: str, expected_weekday: str
    ) -> Dict[str, Any]:
        """Ask a day-of-week question and verify the answer.

        Args:
            question: Question whose answer is a weekday name.
            expected_weekday: Correct day name (e.g. ``Wednesday``).

        Returns:
            Dict with ``passed``, ``actual_weekday``, ``reason``.
        """
        logger.info(f"Temporal weekday question: {question[:120]}")
        raw = self.client.generate(question)
        clean, _ = parse_thinking(raw, strip_unclosed=True)
        emit_rfc_data("actual_answer", clean[:500])

        actual = self._extract_weekday(clean)
        passed = (actual or "").lower() == expected_weekday.lower()
        reason = f"extracted={actual!r}, expected={expected_weekday!r}"
        return self._emit_and_return(
            passed, expected_weekday, reason, {"actual_weekday": actual}
        )

    @keyword("Assert Temporal Result Passed")
    def assert_temporal_result_passed(self, result: Dict[str, Any]) -> None:
        """Assert that a temporal question result has ``passed=True``.

        Args:
            result: Dict returned by one of the ``Ask Temporal *`` keywords.

        Raises:
            AssertionError: If ``result['passed']`` is falsy.
        """
        if not result.get("passed"):
            raise AssertionError(
                f"Temporal reasoning check failed: {result.get('reason', 'no reason')}"
            )

    @keyword("Get Temporal Results Summary")
    def get_temporal_results_summary(
        self, results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Summarise a list of temporal result dicts.

        Args:
            results: List of dicts from ``Ask Temporal *`` keywords.

        Returns:
            Dict with ``total``, ``passed``, ``failed``, ``pass_rate``.
        """
        total = len(results)
        passed = sum(1 for r in results if r.get("passed"))
        failed = total - passed
        pass_rate = passed / total if total > 0 else 0.0
        summary = {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": pass_rate,
        }
        logger.info(
            f"Temporal summary: {passed}/{total} passed ({pass_rate:.0%})"
        )
        return summary
