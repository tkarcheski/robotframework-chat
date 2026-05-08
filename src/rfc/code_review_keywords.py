"""Code review and bug detection keywords for Robot Framework.

Tests whether an LLM can identify bugs and security vulnerabilities in code
snippets using a multiple-choice format.  The letter answer is extracted
deterministically from the first line of the response — Tier 1 / verify:python.
"""

import re
from typing import Any, Dict, Optional

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data

_LETTER_RE = re.compile(r"^\s*([A-Da-d])\b")

_BUG_DETECTION_PROMPT = """\
Review the following code snippet carefully and identify the bug.

```
{code}
```

{question}

Write the letter of the correct answer (A, B, C, or D) on the very first line \
of your response, then briefly explain your reasoning.

Answer:"""

_SECURITY_REVIEW_PROMPT = """\
Review the following code for security vulnerabilities.

```
{code}
```

{question}

Write the letter of the correct answer (A, B, C, or D) on the very first line \
of your response, then briefly explain the vulnerability.

Answer:"""


class CodeReviewKeywords:
    """Robot Framework keywords for code review and bug detection evaluation."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))

    @keyword("Identify Bug In Code")
    def identify_bug_in_code(
        self,
        code: str,
        question: str,
        expected_letter: str,
    ) -> Dict[str, Any]:
        """Ask the LLM to identify the bug in a code snippet.

        Args:
            code: The code snippet containing a bug.
            question: Multiple-choice question with options A–D.
            expected_letter: Correct answer letter (A, B, C, or D).

        Returns:
            Dict with keys: chosen_letter, correct, response, expected.

        Raises:
            ValueError: If expected_letter is not A–D.
        """
        expected_letter = expected_letter.strip().upper()
        if expected_letter not in {"A", "B", "C", "D"}:
            raise ValueError(
                f"expected_letter must be A–D, got {expected_letter!r}"
            )

        prompt = _BUG_DETECTION_PROMPT.format(code=code, question=question)
        logger.info(f"Bug detection prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        chosen = _extract_letter(response)
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

    @keyword("Identify Security Vulnerability")
    def identify_security_vulnerability(
        self,
        code: str,
        question: str,
        expected_letter: str,
    ) -> Dict[str, Any]:
        """Ask the LLM to identify the security vulnerability in a code snippet.

        Args:
            code: The code snippet containing a security issue.
            question: Multiple-choice question with options A–D.
            expected_letter: Correct answer letter (A, B, C, or D).

        Returns:
            Dict with keys: chosen_letter, correct, response, expected.

        Raises:
            ValueError: If expected_letter is not A–D.
        """
        expected_letter = expected_letter.strip().upper()
        if expected_letter not in {"A", "B", "C", "D"}:
            raise ValueError(
                f"expected_letter must be A–D, got {expected_letter!r}"
            )

        prompt = _SECURITY_REVIEW_PROMPT.format(code=code, question=question)
        logger.info(f"Security review prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        chosen = _extract_letter(response)
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


def _extract_letter(response: str) -> Optional[str]:
    """Extract the answer letter A–D from the first line of the response only.

    The prompt instructs the model to put the letter on the first line.
    Searching beyond the first line risks matching option labels in the
    explanatory text (e.g. "option A states …"), producing false results.
    Non-compliant responses return ``None``; callers treat that as a failure.
    """
    first_line = response.strip().splitlines()[0] if response.strip() else ""
    m = _LETTER_RE.search(first_line)
    if m:
        return m.group(1).upper()
    return None
