"""Run SWE-bench evaluation against one or more LLM models.

Usage:
    uv run python scripts/run_swebench.py                      # default model
    uv run python scripts/run_swebench.py --model phi4:14b     # specific model
    uv run python scripts/run_swebench.py --discover           # list instances
    uv run python scripts/run_swebench.py --max-instances 5    # limit instances
    uv run python scripts/run_swebench.py --slice easy         # Verified slice
    uv run python scripts/run_swebench.py --dataset princeton-nlp/SWE-bench
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Any, Dict, List

# Default dataset — must stay in lockstep with the Robot suite's loader
# (core/src/rfc/swebench_keywords.py:_SWEBENCH_DATASET); a pytest guards the
# pairing (modules/ops/tests/test_run_swebench.py).
_SWEBENCH_DATASET = "princeton-nlp/SWE-bench_Verified"
_SLICE_CHOICES = ("all", "easy", "hard")


def _filter_by_slice(
    rows: List[Dict[str, Any]], swebench_slice: str
) -> List[Dict[str, Any]]:
    """Filter dataset rows by difficulty slice (easy/hard).

    Mirrors rfc.swebench_keywords._filter_by_slice: rows without a
    'difficulty' field, or where no rows match, fall back to returning all
    rows (skip-and-log behaviour) so a slice request against a dataset
    without annotations never yields an empty run.
    """
    if swebench_slice == "all":
        return rows
    filtered = [
        r for r in rows if str(r.get("difficulty", "")).lower() == swebench_slice
    ]
    if not filtered:
        print(
            f"warning: SWEBENCH_SLICE={swebench_slice!r}: no rows matched "
            f"difficulty={swebench_slice!r}; using all rows "
            "(dataset may lack a 'difficulty' field)",
            file=sys.stderr,
        )
        return rows
    return filtered


def run_swebench(
    model: str,
    max_instances: int = 10,
    split: str = "test",
    output_dir: str = "results/swebench",
    dataset: str = _SWEBENCH_DATASET,
    swebench_slice: str = "all",
) -> int:
    """Run the SWE-bench Robot Framework suite for a single model."""
    cmd = [
        "uv",
        "run",
        "robot",
        "--variable",
        f"DEFAULT_MODEL:{model}",
        "--variable",
        f"MAX_INSTANCES:{max_instances}",
        "--variable",
        f"SWEBENCH_SPLIT:{split}",
        "--variable",
        f"SWEBENCH_DATASET:{dataset}",
        "--variable",
        f"SWEBENCH_SLICE:{swebench_slice}",
        "--outputdir",
        output_dir,
        "--listener",
        "rfc.db_listener.DbListener",
        "--listener",
        "rfc.git_metadata_listener.GitMetaData",
        "--listener",
        "rfc.ollama_timestamp_listener.OllamaTimestampListener",
        "robot/swebench/swebench.robot",
    ]
    print(
        f"Running SWE-bench: model={model}, max_instances={max_instances}, "
        f"dataset={dataset}, slice={swebench_slice}"
    )
    result = subprocess.run(cmd)
    return result.returncode


def discover_instances(
    split: str = "test",
    max_instances: int = 10,
    dataset: str = _SWEBENCH_DATASET,
    swebench_slice: str = "all",
) -> None:
    """List available SWE-bench instances without running tests."""
    try:
        from datasets import load_dataset  # type: ignore[import-untyped]
    except ImportError:
        print(
            "Error: 'datasets' package required. "
            "Install with: uv pip install 'robotframework-chat[swebench]'",
            file=sys.stderr,
        )
        sys.exit(1)

    ds = load_dataset(dataset, split=split)
    rows = _filter_by_slice(list(ds), swebench_slice)
    for i, row in enumerate(rows):
        if i >= max_instances:
            break
        difficulty = str(row.get("difficulty", "") or "")
        suffix = f"  [{difficulty}]" if difficulty else ""
        print(
            f"  {row['instance_id']:40s}  {row['repo']:30s}  v{row['version']}{suffix}"
        )
    print(f"\nShowing {min(max_instances, len(rows))} of {len(rows)} instances")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SWE-bench evaluation")
    parser.add_argument(
        "--model",
        default=os.environ.get("DEFAULT_MODEL"),
        help="LLM model to evaluate (default: $DEFAULT_MODEL; required if unset)",
    )
    parser.add_argument(
        "--max-instances",
        type=int,
        default=10,
        help="Maximum SWE-bench instances to evaluate (default: 10)",
    )
    parser.add_argument(
        "--split",
        default="test",
        choices=["test", "dev", "train"],
        help="Dataset split (default: test; SWE-bench Verified only has 'test')",
    )
    parser.add_argument(
        "--dataset",
        default=_SWEBENCH_DATASET,
        help="HuggingFace dataset name (default: %(default)s)",
    )
    parser.add_argument(
        "--slice",
        dest="swebench_slice",
        default="all",
        choices=list(_SLICE_CHOICES),
        help=(
            "Difficulty slice filter (default: all). Requires a dataset with "
            "a 'difficulty' column (SWE-bench Verified); falls back to all "
            "rows with a warning otherwise."
        ),
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="List available instances without running tests",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.discover:
        discover_instances(
            split=args.split,
            max_instances=args.max_instances,
            dataset=args.dataset,
            swebench_slice=args.swebench_slice,
        )
    else:
        if not args.model:
            parser.error("--model is required when DEFAULT_MODEL env var is not set")
        sys.exit(
            run_swebench(
                args.model,
                args.max_instances,
                args.split,
                dataset=args.dataset,
                swebench_slice=args.swebench_slice,
            )
        )


if __name__ == "__main__":
    main()
