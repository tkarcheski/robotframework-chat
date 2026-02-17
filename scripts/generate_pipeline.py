#!/usr/bin/env python3
"""Generate GitLab CI child pipeline YAML from config/test_suites.yaml.

Modes
-----
``regular``
    One job per CI job-group, each using the configured default model.
    This is the everyday pipeline triggered on every push / MR.

``dynamic``
    Discovers all Ollama nodes on the network (see ``discover_ollama.py``),
    enumerates every model on every node, and creates a job for each
    (node, model, suite) combination.  Designed for manual "play-button"
    runs that exercise the full test matrix.

Usage::

    # Write the regular child pipeline
    python scripts/generate_pipeline.py --mode regular -o generated-pipeline.yml

    # Write the dynamic child pipeline (discovers nodes first)
    python scripts/generate_pipeline.py --mode dynamic -o generated-pipeline.yml

    # Dry-run to stdout
    python scripts/generate_pipeline.py --mode dynamic
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# Ensure project root is on sys.path so we can import rfc / scripts
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from rfc.suite_config import ci_config, load_config  # noqa: E402
from scripts.discover_ollama import discover_nodes  # noqa: E402


def _slug(text: str) -> str:
    """Turn arbitrary text into a CI-job-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _listener_flags(listeners: list[str]) -> str:
    """Build the ``--listener ...`` portion of the robot command."""
    return " ".join(f"--listener {name}" for name in listeners)


# ---------------------------------------------------------------------------
# Regular pipeline generation
# ---------------------------------------------------------------------------


def generate_regular(config: dict[str, Any]) -> dict[str, Any]:
    """Produce a child-pipeline dict for the regular (single-model) run."""
    ci = config.get("ci", {})
    defs = config.get("defaults", {})
    listeners = ci.get("listeners", [])
    job_groups = ci.get("job_groups", {})
    model = defs.get("model", "llama3")
    endpoint = defs.get("ollama_endpoint", "http://localhost:11434")

    pipeline: dict[str, Any] = {
        "stages": ["test", "report"],
    }

    job_names: list[str] = []

    for job_name, job_def in job_groups.items():
        path = job_def["path"]
        output_dir = job_def["output_dir"]
        tags = job_def.get("tags", ["ollama"])

        robot_cmd = (
            f"uv run robot -d {output_dir} "
            f"{_listener_flags(listeners)} "
            f"-v OLLAMA_ENDPOINT:$OLLAMA_ENDPOINT "
            f"-v DEFAULT_MODEL:$DEFAULT_MODEL "
            f"{path}"
        )

        pipeline[job_name] = {
            "stage": "test",
            "tags": tags,
            "variables": {
                "OLLAMA_ENDPOINT": endpoint,
                "DEFAULT_MODEL": model,
            },
            "before_script": [
                "uv sync --extra dev --extra superset",
                (
                    'echo "Checking Ollama at $OLLAMA_ENDPOINT..." && '
                    'if curl -s "$OLLAMA_ENDPOINT/api/tags" > /dev/null; then '
                    'echo "Ollama is available"; else '
                    'echo "ERROR: Ollama not available"; exit 1; fi'
                ),
                (
                    'echo "Checking model $DEFAULT_MODEL..." && '
                    'if curl -sf "$OLLAMA_ENDPOINT/api/show" -d "{\\"name\\": \\"$DEFAULT_MODEL\\"}" > /dev/null 2>&1; then '
                    'echo "Model $DEFAULT_MODEL is available"; else '
                    'echo "ERROR: Model $DEFAULT_MODEL not found on $OLLAMA_ENDPOINT. '
                    'Available models:" && curl -s "$OLLAMA_ENDPOINT/api/tags" | python3 -c '
                    "\"import sys,json; [print(f\\\"  - {m['name']}\\\") for m in json.load(sys.stdin).get('models',[])]\" "
                    "2>/dev/null; exit 1; fi"
                ),
            ],
            "script": [robot_cmd],
            "artifacts": {
                "when": "always",
                "paths": [f"{output_dir}/", "data/"],
                "reports": {
                    "junit": f"{output_dir}/output.xml",
                },
                "expire_in": "30 days",
            },
            "allow_failure": True,
        }
        job_names.append(job_name)

    # Report job
    pipeline["aggregate-results"] = _report_job(job_names, model)

    return pipeline


# ---------------------------------------------------------------------------
# Dynamic pipeline generation
# ---------------------------------------------------------------------------


def generate_dynamic(config: dict[str, Any]) -> dict[str, Any]:
    """Produce a child-pipeline dict for the dynamic (multi-node/model) run.

    Discovers Ollama nodes, enumerates models, and creates one job per
    ``(node, model, ci-job-group)`` tuple.
    """
    ci = config.get("ci", {})
    listeners = ci.get("listeners", [])
    job_groups = ci.get("job_groups", {})

    nodes = discover_nodes()
    if not nodes:
        # No nodes found -- return a minimal pipeline with a notice
        return {
            "stages": ["test"],
            "no-ollama-nodes-found": {
                "stage": "test",
                "script": [
                    'echo "No Ollama nodes were discovered on the network."',
                    'echo "Set OLLAMA_NODES or OLLAMA_SUBNET and re-run."',
                    "exit 1",
                ],
            },
        }

    pipeline: dict[str, Any] = {"stages": ["test", "report"]}
    job_names: list[str] = []

    for node in nodes:
        endpoint = node["endpoint"]
        node_slug = _slug(endpoint.replace("http://", "").replace("https://", ""))

        for model_name in node["models"]:
            model_slug = _slug(model_name)

            for group_name, group_def in job_groups.items():
                path = group_def["path"]
                tags = group_def.get("tags", ["ollama"])
                group_slug = _slug(group_name)

                output_dir = f"results/dynamic/{node_slug}/{model_slug}/{group_slug}"
                job_id = f"{group_slug}-{node_slug}-{model_slug}"

                robot_cmd = (
                    f"uv run robot -d {output_dir} "
                    f"{_listener_flags(listeners)} "
                    f"-v OLLAMA_ENDPOINT:$OLLAMA_ENDPOINT "
                    f"-v DEFAULT_MODEL:$DEFAULT_MODEL "
                    f"{path}"
                )

                pipeline[job_id] = {
                    "stage": "test",
                    "tags": tags,
                    "variables": {
                        "OLLAMA_ENDPOINT": endpoint,
                        "DEFAULT_MODEL": model_name,
                    },
                    "before_script": [
                        "uv sync --extra dev --extra superset",
                        (
                            f'echo "Node: {endpoint}  Model: {model_name}" && '
                            f'echo "Checking Ollama at $OLLAMA_ENDPOINT..." && '
                            'if curl -s "$OLLAMA_ENDPOINT/api/tags" > /dev/null; then '
                            'echo "Ollama is available"; else '
                            'echo "ERROR: Ollama not available"; exit 1; fi'
                        ),
                        (
                            'echo "Checking model $DEFAULT_MODEL..." && '
                            'if curl -sf "$OLLAMA_ENDPOINT/api/show" -d "{\\"name\\": \\"$DEFAULT_MODEL\\"}" > /dev/null 2>&1; then '
                            'echo "Model $DEFAULT_MODEL is available"; else '
                            'echo "ERROR: Model $DEFAULT_MODEL not found on $OLLAMA_ENDPOINT. '
                            'Available models:" && curl -s "$OLLAMA_ENDPOINT/api/tags" | python3 -c '
                            "\"import sys,json; [print(f\\\"  - {m['name']}\\\") for m in json.load(sys.stdin).get('models',[])]\" "
                            "2>/dev/null; exit 1; fi"
                        ),
                    ],
                    "script": [robot_cmd],
                    "artifacts": {
                        "when": "always",
                        "paths": [f"{output_dir}/", "data/"],
                        "reports": {
                            "junit": f"{output_dir}/output.xml",
                        },
                        "expire_in": "30 days",
                    },
                    "allow_failure": True,
                }
                job_names.append(job_id)

    # Aggregate results from all dynamic jobs
    pipeline["aggregate-results"] = _report_job(
        job_names,
        output_pattern="results/dynamic/**/output.xml",
        combined_dir="results/combined-dynamic",
    )

    return pipeline


# ---------------------------------------------------------------------------
# Shared report job
# ---------------------------------------------------------------------------


def _report_job(
    upstream_jobs: list[str],
    model: str = "llama3",
    output_pattern: str | None = None,
    combined_dir: str = "results/combined",
) -> dict[str, Any]:
    """Build the aggregate-results job definition."""
    needs = [
        {"job": name, "artifacts": True, "optional": True} for name in upstream_jobs
    ]

    if output_pattern is None:
        # Collect from known output dirs
        ci = ci_config()
        job_groups = ci.get("job_groups", {})
        find_expr = " ".join(
            f"{jd['output_dir']}/output.xml" for jd in job_groups.values()
        )
        collect_script = (
            'OUTPUT_FILES="" && '
            f"for f in {find_expr}; do "
            '[ -f "$f" ] && OUTPUT_FILES="$OUTPUT_FILES $f"; done'
        )
    else:
        collect_script = 'OUTPUT_FILES=$(find results/dynamic -name "output.xml" 2>/dev/null | tr "\\n" " ")'

    return {
        "stage": "report",
        "needs": needs,
        "before_script": ["uv sync --extra dev --extra superset"],
        "script": [
            f"mkdir -p {combined_dir}",
            collect_script,
            (
                f'if [ -z "$OUTPUT_FILES" ]; then '
                f'echo "No output.xml files found"; exit 0; fi && '
                f'echo "Combining:$OUTPUT_FILES" && '
                f"uv run rebot "
                f'--name "Combined Results" '
                f"--outputdir {combined_dir} "
                f"--output output.xml "
                f"--log log.html "
                f"--report report.html "
                f"--nostatusrc "
                f"$OUTPUT_FILES && "
                f'echo "Combined report: {combined_dir}/report.html"'
            ),
            f'uv run python scripts/import_test_results.py {combined_dir}/output.xml --model "{model}"',
            "uv run python scripts/generate_ci_metadata.py || echo 'Metadata generation skipped'",
        ],
        "artifacts": {
            "when": "always",
            "paths": [f"{combined_dir}/"],
            "reports": {
                "junit": f"{combined_dir}/output.xml",
            },
            "expire_in": "30 days",
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate GitLab CI child pipeline from config/test_suites.yaml"
    )
    parser.add_argument(
        "--mode",
        choices=["regular", "dynamic"],
        default="regular",
        help="Pipeline mode (default: regular)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output file (default: stdout)",
    )
    args = parser.parse_args()

    config = load_config()

    if args.mode == "regular":
        pipeline = generate_regular(config)
    else:
        pipeline = generate_dynamic(config)

    out = yaml.dump(pipeline, default_flow_style=False, sort_keys=False)

    if args.output:
        Path(args.output).write_text(out)
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(out)


if __name__ == "__main__":
    main()
