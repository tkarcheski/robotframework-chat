"""Pluggable grader dispatcher for OpenAI-Evals suites (#621).

Three graders behind one :func:`get_grader` factory, all satisfying the
:class:`rfc.graders.base.Grader` Protocol:

- ``exact``     — deterministic string equality (:class:`ExactGrader`).
- ``regex``     — deterministic pattern search (:class:`RegexGrader`).
- ``llm_judge`` — LLM-as-judge, wrapping the existing ``rfc.grader.Grader``
  (:class:`LLMJudgeGrader`); requires an ``llm_client``.

Suites name their grader in config and resolve it here, so adding a benchmark
never means reaching into grader internals.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import Grader
from .exact import ExactGrader
from .llm_judge import LLMJudgeGrader
from .regex import RegexGrader

__all__ = [
    "Grader",
    "ExactGrader",
    "RegexGrader",
    "LLMJudgeGrader",
    "get_grader",
    "GRADERS",
]

# Names of the graders that need no LLM client (constructed directly).
GRADERS = ("exact", "regex", "llm_judge")


def get_grader(name: str, llm_client: Optional[Any] = None) -> Grader:
    """Return a grader instance by name.

    Args:
        name: One of ``exact``, ``regex``, ``llm_judge``.
        llm_client: Required for ``llm_judge`` (the model used as judge);
            ignored by the pure graders.

    Raises:
        ValueError: for an unknown grader name, or when ``llm_judge`` is
            requested without an ``llm_client``.
    """
    key = name.strip().lower()
    if key == "exact":
        return ExactGrader()
    if key == "regex":
        return RegexGrader()
    if key == "llm_judge":
        if llm_client is None:
            raise ValueError("llm_judge grader requires an llm_client")
        return LLMJudgeGrader(llm_client)
    raise ValueError(f"Unknown grader {name!r}; expected one of {GRADERS}")
