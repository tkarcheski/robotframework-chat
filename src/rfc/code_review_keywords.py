"""Code review and bug detection keywords for Robot Framework.

Tests whether an LLM can identify bugs and security vulnerabilities in code
snippets using a multiple-choice format.  The letter answer is extracted
deterministically from the first line of the response — Tier 1 / verify:python.
"""

import re
from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data

# Require an explicit choice delimiter after the letter: A), A., A:, or a bare
# letter at end-of-line.  \b alone would match "A bug occurs..." as option A.
_LETTER_RE = re.compile(r"^\s*([A-Da-d])(?:[).:]\s*|\s*$)")

# YES/NO verdict for binary defect classification.  Requires a delimiter (or
# end-of-line) after the word so "Nothing wrong..." / "Yesterday..." never
# match as NO / YES.
_VERDICT_RE = re.compile(r"^\s*(yes|no)(?:[\s,.:;!)—-]|$)", re.IGNORECASE)

_DEFECT_CLASSIFICATION_PROMPT = """\
You are reviewing a C function from a real open-source project (FFmpeg or \
QEMU). Decide whether the function contains a defect or security \
vulnerability (e.g. buffer overflow, missing bounds or NULL check, integer \
overflow, use-after-free, off-by-one).

```c
{func}
```

Does this function contain a defect or vulnerability? Write YES or NO on the \
very first line of your response, then briefly explain your reasoning.

Answer:"""

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
        """Ask the LLM to identify the bug in a code snippet."""
        expected_letter = expected_letter.strip().upper()
        if expected_letter not in {"A", "B", "C", "D"}:
            raise ValueError(f"expected_letter must be A–D, got {expected_letter!r}")

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
        """Ask the LLM to identify the security vulnerability in a code snippet."""
        expected_letter = expected_letter.strip().upper()
        if expected_letter not in {"A", "B", "C", "D"}:
            raise ValueError(f"expected_letter must be A–D, got {expected_letter!r}")

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

    @keyword("Classify Defect In Code")
    def classify_defect_in_code(
        self,
        func: str,
        vulnerable: Any,
    ) -> Dict[str, Any]:
        """Ask the LLM whether a function contains a defect — YES/NO (Devign subset)."""
        expected = _coerce_bool(vulnerable)

        prompt = _DEFECT_CLASSIFICATION_PROMPT.format(func=func)
        logger.info(f"Defect classification prompt:\n{prompt}")

        response = self.client.generate(prompt)
        logger.info(f"LLM response:\n{response}")

        verdict = _extract_verdict(response)
        correct = verdict is not None and verdict == expected

        emit_rfc_data("expected_vulnerable", str(expected))
        emit_rfc_data("verdict", "UNKNOWN" if verdict is None else str(verdict))
        emit_rfc_data("correct", str(correct))

        return {
            "verdict": verdict,
            "correct": correct,
            "response": response,
            "expected": expected,
        }

    @keyword("Record Defect Detection Accuracy")
    def record_defect_detection_accuracy(self, results: List[Any]) -> float:
        """Emit aggregate accuracy as ``RFC_DATA:score`` — per-item ``correct``
        emissions are not treated as scores by the listeners."""
        if not results:
            raise ValueError("results must contain at least one result")
        flags = [_coerce_bool(r) for r in results]
        accuracy = sum(flags) / len(flags)
        emit_rfc_data("score", f"{accuracy:.4f}")
        logger.info(
            f"Defect-detection accuracy: {accuracy:.4f} over {len(flags)} items"
        )
        return accuracy


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _coerce_bool(value: Any) -> bool:
    """Coerce a Robot-supplied truth value (bool or string) to a bool."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    raise ValueError(f"vulnerable must be a boolean, got {value!r}")


def _extract_verdict(response: str) -> Optional[bool]:
    """First line only — searching further risks matching the explanation.
    Non-compliant responses return ``None``."""
    first_line = response.strip().splitlines()[0] if response.strip() else ""
    m = _VERDICT_RE.search(first_line)
    if m:
        return m.group(1).lower() == "yes"
    return None


def _extract_letter(response: str) -> Optional[str]:
    """First line only — beyond it risks matching option labels in the
    explanation ("option A states …"). Non-compliant responses return ``None``."""
    first_line = response.strip().splitlines()[0] if response.strip() else ""
    m = _LETTER_RE.search(first_line)
    if m:
        return m.group(1).upper()
    return None
