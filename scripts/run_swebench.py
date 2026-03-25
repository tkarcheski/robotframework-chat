"""Run SWE-bench evaluation against one or more LLM models.

Usage:
    uv run python scripts/run_swebench.py                      # default model
    uv run python scripts/run_swebench.py --model phi4:14b     # specific model
    uv run python scripts/run_swebench.py --discover           # list instances
    uv run python scripts/run_swebench.py --max-instances 5    # limit instances
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def run_swebench(
    model: str,
    max_instances: int = 10,
    split: str = "test",
    output_dir: str = "results/swebench",
) -> int:
    """Run the SWE-bench Robot Framework suite for a single model."""
    cmd = [
        "uv",
        "run",
        "robot",
        "--variable",
        f"MODEL:{model}",
        "--variable",
        f"MAX_INSTANCES:{max_instances}",
        "--variable",
        f"SWEBENCH_SPLIT:{split}",
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
    print(f"Running SWE-bench: model={model}, max_instances={max_instances}")
    result = subprocess.run(cmd)
    return result.returncode


def discover_instances(split: str = "test", max_instances: int = 10) -> None:
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

    ds = load_dataset("princeton-nlp/SWE-bench", split=split)
    for i, row in enumerate(ds):
        if i >= max_instances:
            break
        print(f"  {row['instance_id']:40s}  {row['repo']:30s}  v{row['version']}")
    print(f"\nShowing {min(max_instances, len(ds))} of {len(ds)} instances")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SWE-bench evaluation")
    parser.add_argument(
        "--model",
        default=os.environ.get("DEFAULT_MODEL", "phi4:14b"),
        help="LLM model to evaluate (default: $DEFAULT_MODEL or phi4:14b)",
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
        help="Dataset split (default: test)",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="List available instances without running tests",
    )

    args = parser.parse_args()

    if args.discover:
        discover_instances(split=args.split, max_instances=args.max_instances)
    else:
        sys.exit(run_swebench(args.model, args.max_instances, args.split))


if __name__ == "__main__":
    main()
