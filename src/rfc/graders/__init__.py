"""Pluggable grader dispatcher for OpenAI-Evals suites (#621).

Three graders behind one :func:`get_grader` factory, all satisfying the
:class:`rfc.graders.base.Grader` Protocol: ``exact`` and ``regex`` are
deterministic and offline; ``llm_judge`` wraps ``rfc.grader.Grader`` and needs
an ``llm_client``. Suites name their grader in config and resolve it here.
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

# Valid grader names accepted by get_grader.
GRADERS = ("exact", "regex", "llm_judge")


def get_grader(name: str, llm_client: Optional[Any] = None) -> Grader:
    """Return a grader instance by name (``exact``/``regex``/``llm_judge``).

    ``llm_judge`` requires an ``llm_client``; raises ``ValueError`` for an
    unknown name or a missing client.
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
