"""Generic HuggingFace dataset loader for OpenAI-Evals benchmark suites.

Generalizes the SWE-bench-specific ``_load_dataset()`` helper (which lived in
``swebench_keywords``) into a reusable interface every eval suite can share
(#621). Two entry points:

- :func:`load_hf_dataset` — load a HuggingFace dataset split as a list of
  row dicts, with optional offline cache directory, an instance cap, and
  *deterministic* seeded subsampling.
- :func:`iter_instances` — normalize raw rows into dicts that are guaranteed
  to carry an ``instance_id``, optionally projecting to a field subset.

The single import seam (:func:`_import_load_dataset`) keeps the loader fully
mockable: unit tests patch it so no dataset is ever downloaded and the
optional ``datasets`` dependency is not required in CI.
"""

from __future__ import annotations

import random
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence

# The id field every normalized instance is guaranteed to expose.
INSTANCE_ID_FIELD = "instance_id"


def _import_load_dataset() -> Callable[..., Any]:
    """Return ``datasets.load_dataset``, or raise a skip-able error.

    Isolated as the single seam so tests can patch it and never hit the
    network. Mirrors the import-skip contract of the original swebench
    loader: a missing optional dependency raises :class:`MissingDependencyError`
    (an ``RFCSkipError``), never a bare ``ImportError``.
    """
    try:
        from datasets import load_dataset  # type: ignore[import-untyped]
    except ImportError as e:
        from .exceptions import MissingDependencyError

        raise MissingDependencyError(
            package="datasets",
            install_hint="uv pip install 'robotframework-chat[swebench]'",
        ) from e
    return load_dataset


def load_hf_dataset(
    repo: str,
    split: str,
    max_instances: Optional[int] = None,
    cache_dir: Optional[str] = None,
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Load a HuggingFace dataset split as a list of row dicts.

    Args:
        repo: HuggingFace dataset identifier (e.g. ``princeton-nlp/SWE-bench``).
        split: Dataset split (``test``, ``dev``, ``train``, ...).
        max_instances: Cap on rows returned. ``None`` returns all rows;
            ``0`` returns an empty list.
        cache_dir: Optional offline/local cache directory. When provided it is
            forwarded to ``datasets.load_dataset(cache_dir=...)`` for
            air-gapped / pre-downloaded runs. When omitted, the kwarg is not
            passed at all (some ``datasets`` versions reject ``cache_dir=None``).
        seed: When set together with a ``max_instances`` smaller than the
            dataset, selects a *deterministic* random subset (same seed →
            same subset). When ``None``, the first ``max_instances`` rows are
            taken (stable, dataset-order slice).

    Returns:
        A list of raw row dicts (not yet normalized — see
        :func:`iter_instances`).
    """
    load_dataset = _import_load_dataset()

    kwargs: Dict[str, Any] = {"split": split}
    if cache_dir is not None:
        kwargs["cache_dir"] = cache_dir

    ds = load_dataset(repo, **kwargs)
    rows: List[Dict[str, Any]] = [dict(row) for row in ds]

    if max_instances is None:
        return rows
    max_instances = int(max_instances)
    if max_instances <= 0:
        return []
    if max_instances >= len(rows):
        return rows

    if seed is None:
        # Stable dataset-order slice — reproducible without a seed.
        return rows[:max_instances]

    # Deterministic subsample: shuffle a copy with a seeded RNG, then take the
    # head. Using a local Random keeps global RNG state untouched.
    rng = random.Random(seed)
    indices = list(range(len(rows)))
    rng.shuffle(indices)
    chosen = sorted(indices[:max_instances])
    return [rows[i] for i in chosen]


def iter_instances(
    dataset: Iterable[Dict[str, Any]],
    fields: Optional[Sequence[str]] = None,
    id_field: str = INSTANCE_ID_FIELD,
) -> Iterator[Dict[str, Any]]:
    """Yield normalized instance dicts, each guaranteed an ``instance_id``.

    Args:
        dataset: Iterable of raw row dicts (e.g. from :func:`load_hf_dataset`).
        fields: When given, project each row to just these fields (plus the
            always-retained ``instance_id``). When ``None``, all fields are
            kept.
        id_field: Source field to read the instance id from. If a row lacks
            it (and lacks ``instance_id``), a stable synthetic id is assigned
            from the row's position so downstream code never KeyErrors.

    Yields:
        Normalized dicts with a non-empty ``instance_id`` key.
    """
    for position, row in enumerate(dataset):
        raw_id = row.get(id_field) or row.get(INSTANCE_ID_FIELD)
        instance_id = (
            str(raw_id) if raw_id not in (None, "") else f"instance-{position}"
        )

        if fields is None:
            normalized: Dict[str, Any] = dict(row)
        else:
            normalized = {k: row[k] for k in fields if k in row}

        normalized[INSTANCE_ID_FIELD] = instance_id
        yield normalized
