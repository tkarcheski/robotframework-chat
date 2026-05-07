"""Robot Framework keywords for LLM code review and bug detection tests."""

from typing import Any, Dict, List, Optional, Tuple

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data
from .thinking import parse_thinking

_KNOWN_BUG_TYPES = frozenset(
    [
        "off-by-one",
        "null-pointer",
        "resource-leak",
        "type-mismatch",
        "infinite-loop",
        "race-condition",
        "integer-overflow",
        "logic-error",
    ]
)


class CodeReviewKeywords:
    """Keywords for testing LLM code review and bug detection.

    Grades by checking whether specific keywords about the bug (variable
    name, error category, corrected line) appear in the response
    (Tier 1 — no secondary LLM grader).
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self, timeout: Optional[int] = None, max_retries: int = 2) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _keyword_recall(
        self, response: str, required: List[str]
    ) -> Tuple[float, List[str], List[str]]:
        """Return (recall, found, missing) for *required* keywords."""
        lower = response.lower()
        found = [kw for kw in required if kw.lower() in lower]
        missing = [kw for kw in required if kw.lower() not in lower]
        score = len(found) / len(required) if required else 0.0
        return score, found, missing

    def _detect_bug_type(self, response: str) -> Optional[str]:
        """Return the first recognised bug-type string found in *response*."""
        lower = response.lower()
        for bt in _KNOWN_BUG_TYPES:
            if bt in lower or bt.replace("-", " ") in lower:
                return bt
        return None

    # ------------------------------------------------------------------
    # Public keywords
    # ------------------------------------------------------------------

    @keyword("Ask LLM To Find Bug")
    def ask_llm_to_find_bug(
        self,
        code: str,
        bug_description: str,
        required_keywords: List[str],
        language: str = "Python",
        min_score: float = 0.5,
    ) -> Dict[str, Any]:
        """Present buggy code to the LLM and check it identifies the bug.

        Grades by checking what fraction of *required_keywords* appear in
        the response.  Keywords can be variable names, error categories,
        or corrected-code fragments — anything specific to the planted bug.

        Args:
            code: Source code containing the bug.
            bug_description: Human-readable description (not used for grading).
            required_keywords: Words/phrases the response must contain.
            language: Programming language label for the prompt.
            min_score: Minimum keyword recall fraction required to pass.

        Returns:
            Dict with ``score``, ``found_keywords``, ``missing_keywords``,
            ``passed``.
        """
        prompt = (
            f"Review the following {language} code and identify any bugs or errors. "
            f"Be specific: name the variable, line, or construct that is wrong.\n\n"
            f"```{language.lower()}\n{code}\n```"
        )
        logger.info(f"Code review: {code[:200]}")
        raw = self.client.generate(prompt)
        clean, _ = parse_thinking(raw, strip_unclosed=True)
        emit_rfc_data("actual_answer", clean[:800])
        emit_rfc_data("bug_description", bug_description)

        score, found, missing = self._keyword_recall(clean, required_keywords)
        passed = score >= min_score
        reason = (
            f"recall={score:.2f} ({len(found)}/{len(required_keywords)}), "
            f"found={found}, missing={missing}"
        )
        emit_rfc_data("score", f"{score:.2f}")
        emit_rfc_data("expected_answer", f"bug: {bug_description}")
        emit_rfc_data("grading_reason", reason)
        logger.info(f"Code review grading: {reason}")
        return {
            "score": score,
            "found_keywords": found,
            "missing_keywords": missing,
            "passed": passed,
        }

    @keyword("Ask LLM To Classify Bug")
    def ask_llm_to_classify_bug(
        self,
        code: str,
        expected_bug_type: str,
        language: str = "Python",
    ) -> Dict[str, Any]:
        """Ask the LLM to classify the type of bug in a code snippet.

        The LLM is constrained to the known category list so extraction
        is unambiguous.

        Args:
            code: Code snippet with exactly one known bug.
            expected_bug_type: One of: ``off-by-one``, ``null-pointer``,
                ``resource-leak``, ``type-mismatch``, ``infinite-loop``,
                ``race-condition``, ``integer-overflow``, ``logic-error``.
            language: Programming language label.

        Returns:
            Dict with ``passed``, ``actual_bug_type``, ``reason``.
        """
        categories = ", ".join(sorted(_KNOWN_BUG_TYPES))
        prompt = (
            f"The following {language} code contains exactly one bug. "
            f"Classify it using one of these categories only: {categories}.\n\n"
            f"```{language.lower()}\n{code}\n```\n\n"
            f"Reply with only the category name — nothing else."
        )
        logger.info(f"Bug classification: {code[:150]}")
        raw = self.client.generate(prompt)
        clean, _ = parse_thinking(raw, strip_unclosed=True)
        emit_rfc_data("actual_answer", clean[:200])

        actual = self._detect_bug_type(clean)
        passed = actual == expected_bug_type.lower()
        reason = f"actual={actual!r}, expected={expected_bug_type!r}"
        emit_rfc_data("score", str(1 if passed else 0))
        emit_rfc_data("expected_answer", expected_bug_type)
        emit_rfc_data("grading_reason", reason)
        logger.info(f"Bug classification grading: {reason}, passed={passed}")
        return {"passed": passed, "actual_bug_type": actual, "reason": reason}

    @keyword("Ask LLM To Suggest Fix")
    def ask_llm_to_suggest_fix(
        self,
        code: str,
        expected_fix_keywords: List[str],
        language: str = "Python",
        min_score: float = 0.5,
    ) -> Dict[str, Any]:
        """Ask the LLM to fix buggy code and check the fix contains key tokens.

        Grades by checking that the suggested fix mentions required tokens
        (e.g. the corrected identifier, operator, or method call).

        Args:
            code: Buggy source code.
            expected_fix_keywords: Tokens the fixed code or explanation must contain.
            language: Programming language label.
            min_score: Minimum keyword recall to pass.

        Returns:
            Dict with ``score``, ``found_keywords``, ``missing_keywords``,
            ``passed``.
        """
        prompt = (
            f"The following {language} code contains a bug. "
            f"Show the corrected version and briefly explain the fix.\n\n"
            f"```{language.lower()}\n{code}\n```"
        )
        logger.info(f"Fix suggestion: {code[:150]}")
        raw = self.client.generate(prompt)
        clean, _ = parse_thinking(raw, strip_unclosed=True)
        emit_rfc_data("actual_answer", clean[:800])

        score, found, missing = self._keyword_recall(clean, expected_fix_keywords)
        passed = score >= min_score
        reason = (
            f"recall={score:.2f} ({len(found)}/{len(expected_fix_keywords)}), "
            f"found={found}, missing={missing}"
        )
        emit_rfc_data("score", f"{score:.2f}")
        emit_rfc_data("grading_reason", reason)
        logger.info(f"Fix suggestion grading: {reason}")
        return {
            "score": score,
            "found_keywords": found,
            "missing_keywords": missing,
            "passed": passed,
        }

    @keyword("Assert Code Review Passed")
    def assert_code_review_passed(
        self, result: Dict[str, Any], label: str = "code review"
    ) -> None:
        """Assert that a code review result has ``passed=True``.

        Args:
            result: Dict returned by an ``Ask LLM To *`` keyword.
            label: Human-readable label for the error message.

        Raises:
            AssertionError: If ``result['passed']`` is falsy.
        """
        if not result.get("passed"):
            raise AssertionError(
                f"{label} failed: {result.get('reason', 'no reason')}"
            )
