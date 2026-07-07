"""The reusable Grader Protocol shared by every OpenAI-Evals grader (#621).

A grader scores a model ``response`` against an ``instance`` (the dataset row
that produced it) and returns ``(score, reason)``. A Protocol (not a base
class) lets the dispatcher treat ``exact``, ``regex``, and ``llm_judge``
uniformly, and lets suites depend on behaviour, not implementation.
"""

from __future__ import annotations

from typing import Any, Dict, Protocol, Tuple, runtime_checkable


@runtime_checkable
class Grader(Protocol):
    """Scores a response against a dataset instance.

    Implementations must be import-safe (no network / LLM at construction for
    the pure graders) so Robot ``--dryrun`` and unit tests stay offline.
    """

    def grade(self, instance: Dict[str, Any], response: str) -> Tuple[float, str]:
        """Return ``(score, reason)`` for ``response``; ``score`` is in ``[0.0, 1.0]``."""
        ...
