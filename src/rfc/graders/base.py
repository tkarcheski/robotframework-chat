"""The reusable Grader Protocol shared by every OpenAI-Evals grader (#621).

A grader scores a model ``response`` against an ``instance`` (the dataset row
that produced it) and returns ``(score, reason)``. Keeping this a
:class:`typing.Protocol` lets the dispatcher treat ``exact``, ``regex``, and
``llm_judge`` uniformly without a shared base class, and lets suites depend on
the behaviour, not the implementation.
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
        """Return ``(score, reason)`` for ``response`` given ``instance``.

        Args:
            instance: The dataset row (normalized dict; see
                :func:`rfc.eval_datasets.iter_instances`). Graders read the
                fields they need (e.g. ``expected_answer``, ``pattern``,
                ``problem_statement``).
            response: The model's answer text under evaluation.

        Returns:
            A ``(score, reason)`` tuple where ``score`` is a float in
            ``[0.0, 1.0]`` and ``reason`` is a short human-readable
            explanation.
        """
        ...
