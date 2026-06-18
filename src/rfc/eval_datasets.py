"""Shared Hugging Face dataset loader for OpenAI Evals and AIEFS harnesses (#621)."""

from __future__ import annotations

from typing import Any, Dict, List


def load_hf_dataset(dataset: str, split: str) -> List[Dict[str, Any]]:
    """Load a Hugging Face dataset split. Isolated for mocking in tests.

    Raises MissingDependencyError when the ``datasets`` package is absent so
    callers see a clear actionable message rather than a bare ImportError.
    """
    try:
        from datasets import load_dataset  # type: ignore[import-untyped]
    except ImportError as e:
        from .exceptions import MissingDependencyError

        raise MissingDependencyError(
            package="datasets",
            install_hint="uv pip install 'robotframework-chat[swebench]'",
        ) from e
    ds = load_dataset(dataset, split=split)
    return list(ds)


def iter_instances(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return rows as a new list.

    A no-op today; the indirection gives future transforms (filtering,
    field normalisation) a single place to land without changing callers.
    """
    return list(rows)
