"""Import an external Hugging Face benchmark as committed RFC test data.

Static-import pattern (see .claude/skills/importing-huggingface-data):
download once, convert to a small curated YAML subset, commit the YAML.
The raw dataset is never committed; this script is the reproducible source.

Data is fetched via the public HF datasets-server REST API
(https://datasets-server.huggingface.co/rows) so no extra dependency is
needed — plain ``requests``.  Set ``HF_TOKEN`` in the environment for gated
datasets or to avoid rate limits (optional for public datasets).

Usage:
    uv run python scripts/import_hf_benchmark.py ifeval --limit 50
    uv run python scripts/import_hf_benchmark.py code_review_defect --limit 50
    uv run python scripts/import_hf_benchmark.py ifeval --limit 25 \
        --output robot/tier1/ifeval/variables/ifeval_hf.yaml

How to add the next benchmark
-----------------------------
1. Write a converter ``convert_<name>_rows(rows, limit)`` that maps raw HF
   rows to small, self-contained dict items the Robot suite will consume.
   Filter out items the framework cannot grade deterministically.
2. If grading needs new logic, TDD it into a keyword library under
   ``src/rfc/`` first (see ``rfc.ifeval_keywords.SUPPORTED_INSTRUCTIONS``
   for the cross-check pattern: the converter's supported set must match
   the verifier's so committed data is always gradable).
3. Register a :class:`BenchmarkSpec` in :data:`BENCHMARKS` (dataset id,
   config, split, license, output path, converter).
4. Run this script once, commit the generated YAML, and add a Robot suite
   that loads the YAML via ``Variables`` and iterates the items.
5. Register the suite path in ``config/test_suites.yaml`` (and CI job
   groups) if it is a new directory; verify with ``make robot-dryrun``.
6. Note the license and the sampling strategy in the YAML header and PR.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List

import requests
import yaml

# Make src/ importable when run as a script from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rfc.ifeval_keywords import SUPPORTED_INSTRUCTIONS  # noqa: E402

ROWS_ENDPOINT = "https://datasets-server.huggingface.co/rows"
PAGE_SIZE = 100
REQUEST_TIMEOUT = 60


def fetch_rows(
    dataset: str, config: str, split: str, max_rows: int = 600
) -> List[Dict[str, Any]]:
    """Fetch up to *max_rows* raw rows from the HF datasets-server API."""
    headers = {}
    token = os.environ.get("HF_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    rows: List[Dict[str, Any]] = []
    offset = 0
    while len(rows) < max_rows:
        length = min(PAGE_SIZE, max_rows - len(rows))
        response = requests.get(
            ROWS_ENDPOINT,
            params={
                "dataset": dataset,
                "config": config,
                "split": split,
                "offset": offset,
                "length": length,
            },
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        page = [entry["row"] for entry in response.json().get("rows", [])]
        rows.extend(page)
        if len(page) < length:
            break  # End of split.
        offset += len(page)
    return rows[:max_rows]


def convert_ifeval_rows(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Convert raw google/IFEval rows to committed test items.

    Keeps only items whose instructions are ALL gradable by
    ``rfc.ifeval_keywords`` (deterministic, dependency-free checkers), takes
    the first *limit* such items of the train split (deterministic
    sampling), and strips the ``None`` padding the datasets-server struct
    schema adds to per-instruction kwargs.
    """
    items: List[Dict[str, Any]] = []
    for row in rows:
        if len(items) >= limit:
            break
        instruction_ids = row["instruction_id_list"]
        if not all(iid in SUPPORTED_INSTRUCTIONS for iid in instruction_ids):
            continue
        instructions = [
            {
                "id": iid,
                "kwargs": {k: v for k, v in kwargs.items() if v is not None},
            }
            for iid, kwargs in zip(instruction_ids, row["kwargs"])
        ]
        items.append(
            {
                "key": row["key"],
                "prompt": row["prompt"],
                "instructions": instructions,
            }
        )
    return items


# Devign functions can run to tens of thousands of characters; cap committed
# items so they fit comfortably in small local models' context windows.
MAX_FUNC_CHARS = 4000

IFEVAL_SAMPLING_NOTE = (
    "first-N items of the source split whose instructions are all\n"
    "deterministically gradable — see\n"
    "rfc.ifeval_keywords.SUPPORTED_INSTRUCTIONS."
)

DEFECT_SAMPLING_NOTE = (
    f"balanced subset of the Devign test split: the dataset's doubled\n"
    f"newlines are collapsed, functions longer than {MAX_FUNC_CHARS} chars\n"
    f"are dropped (small-model context budget), then the first N/2\n"
    f"vulnerable and first N/2 safe functions are kept and interleaved so\n"
    f"any prefix of the list stays class-balanced. vulnerable=true means\n"
    f"the function contains a known defect/vulnerability."
)


def convert_defect_detection_rows(
    rows: List[Dict[str, Any]], limit: int
) -> List[Dict[str, Any]]:
    """Convert raw Devign (CodeXGLUE defect-detection) rows to test items.

    Drops functions longer than :data:`MAX_FUNC_CHARS`, then takes the first
    ``limit // 2`` vulnerable and first ``limit // 2`` safe functions (in
    split order — deterministic sampling) and interleaves the two classes so
    truncated runs still see a balanced mix.  Output is strictly balanced:
    if one class runs short, the other is capped to match.
    """
    vulnerable: List[Dict[str, Any]] = []
    safe: List[Dict[str, Any]] = []
    per_class = limit // 2
    for row in rows:
        if len(vulnerable) >= per_class and len(safe) >= per_class:
            break
        # Devign stores every source line followed by a blank line; collapse
        # the padding to recover the original line structure (halves tokens).
        func = row["func"].replace("\n\n", "\n")
        if len(func) > MAX_FUNC_CHARS:
            continue
        bucket = vulnerable if row["target"] else safe
        if len(bucket) >= per_class:
            continue
        bucket.append(
            {
                "id": row["id"],
                "project": row["project"],
                "commit_id": row["commit_id"],
                "func": func,
                "vulnerable": bool(row["target"]),
            }
        )

    n = min(len(vulnerable), len(safe))
    items: List[Dict[str, Any]] = []
    for pair in zip(vulnerable[:n], safe[:n]):
        items.extend(pair)
    return items[:limit]


def write_benchmark_yaml(
    output_path: Path,
    variable_name: str,
    items: List[Dict[str, Any]],
    source: str,
    note: str = "",
) -> None:
    """Write *items* as a Robot Framework YAML variable file with a header.

    *note* documents the sampling strategy; each line is rendered as a
    ``#`` comment in the header.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    note_lines = "".join(f"# {line}\n" for line in note.splitlines())
    header = (
        f"# Auto-generated by scripts/import_hf_benchmark.py — do not edit by hand.\n"
        f"# Source: https://huggingface.co/datasets/{source}\n"
        f"# Items: {len(items)}\n"
        f"{note_lines}"
    )
    body = yaml.safe_dump(
        {variable_name: items},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=88,
    )
    output_path.write_text(header + "\n" + body)


@dataclass(frozen=True)
class BenchmarkSpec:
    """Everything needed to statically import one HF benchmark."""

    dataset: str
    config: str
    split: str
    license_id: str
    variable_name: str
    default_output: Path
    converter: Callable[[List[Dict[str, Any]], int], List[Dict[str, Any]]]
    sampling_note: str = ""
    supported_instructions: FrozenSet[str] = field(default_factory=frozenset)


BENCHMARKS: Dict[str, BenchmarkSpec] = {
    "ifeval": BenchmarkSpec(
        dataset="google/IFEval",
        config="default",
        split="train",
        license_id="Apache-2.0",
        variable_name="IFEVAL_HF",
        default_output=Path("robot/tier1/ifeval/variables/ifeval_hf.yaml"),
        converter=convert_ifeval_rows,
        sampling_note=IFEVAL_SAMPLING_NOTE,
        supported_instructions=SUPPORTED_INSTRUCTIONS,
    ),
    "code_review_defect": BenchmarkSpec(
        dataset="google/code_x_glue_cc_defect_detection",
        config="default",
        split="test",
        license_id="C-UDA-1.0",
        variable_name="CODE_REVIEW_DEFECT_HF",
        default_output=Path("robot/tier1/code_review/variables/defect_detection_hf.yaml"),
        converter=convert_defect_detection_rows,
        sampling_note=DEFECT_SAMPLING_NOTE,
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Statically import an HF benchmark as committed YAML"
    )
    parser.add_argument("benchmark", choices=sorted(BENCHMARKS))
    parser.add_argument("--limit", type=int, default=50, help="Max items to commit")
    parser.add_argument("--output", type=Path, default=None, help="Output YAML path")
    parser.add_argument(
        "--max-fetch",
        type=int,
        default=600,
        help="Max raw rows to fetch before filtering",
    )
    args = parser.parse_args()

    spec = BENCHMARKS[args.benchmark]
    rows = fetch_rows(spec.dataset, spec.config, spec.split, max_rows=args.max_fetch)
    items = spec.converter(rows, args.limit)
    output = args.output or spec.default_output
    write_benchmark_yaml(
        output, spec.variable_name, items, source=spec.dataset, note=spec.sampling_note
    )
    print(
        f"Wrote {len(items)} {args.benchmark} items "
        f"(from {len(rows)} fetched rows) to {output}"
    )


if __name__ == "__main__":
    main()
