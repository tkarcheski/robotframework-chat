"""Shared grader functions for OpenAI Evals and AIEFS harnesses (#621).

Wraps ``Grader.grade()`` as a module-level callable so downstream harnesses
import a stable function, not a class internals contract.  ``exec_judge``
(Docker sandbox grading) lives in the Docker-touching slice of #562.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .grader import Grader
    from .models import GradeResult


def llm_judge(
    grader: "Grader",
    question: str,
    expected: str,
    actual: str,
) -> "GradeResult":
    """LLM-judge grader — delegates to ``Grader.grade()``.

    Args:
        grader: A ``Grader`` instance backed by an LLM client.
        question: The question posed to the model under test.
        expected: The reference / gold-standard answer.
        actual: The model's actual answer to evaluate.

    Returns:
        ``GradeResult`` with ``score`` (0.0–1.0) and ``reason``.
    """
    return grader.grade(question, expected, actual)
