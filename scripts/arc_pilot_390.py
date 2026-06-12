"""ARC pilot driver for issue #390.

Runs ONE SWE-bench-Lite instance through the existing harness exactly as
robot/swebench/swebench.robot would — same keyword library, same prompt —
and packages the artifacts requested by the ARC reviewer:

    instance.json, generated.patch, gold.patch, scope.json,
    verification.sh, result.json   (verification.log is produced by
    running verification.sh, done separately so the log is unedited).

Gold patch and test_patch are never shown to the generation model; they
are only serialized AFTER generation completes.

Usage:
    uv run python scripts/arc_pilot_390.py --instance-id pytest-dev__pytest-11148
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from rfc.keywords import LLMKeywords
from rfc.swebench_keywords import SWEBenchKeywords
from rfc.swebench_models import SWEBenchInstance

_DATASET = "princeton-nlp/SWE-bench_Lite"
_SCHEMA_VERSION = "arc-pilot-result-v1"

# Verbatim copy of the prompt template in robot/swebench/swebench.robot.
_PROMPT_TEMPLATE = (
    "Generate a minimal git diff patch that resolves this issue:\n\n"
    "Repository: {repo}\n"
    "Base commit: {base_commit}\n\n"
    "Issue:\n{problem_statement}\n\n"
    "Respond with ONLY the unified diff patch, no explanation."
)


def _gold_patch_files(gold_patch: str) -> List[str]:
    """File paths touched by the gold patch (from diff --git headers)."""
    files = []
    for line in gold_patch.splitlines():
        if line.startswith("diff --git "):
            files.append(line.split(" b/")[-1])
    return sorted(set(files))


def _ollama_digest(model: str) -> str:
    """Resolve the immutable digest for an installed Ollama model tag."""
    import requests

    resp = requests.post(
        "http://localhost:11434/api/show", json={"name": model}, timeout=30
    )
    resp.raise_for_status()
    body: Dict[str, Any] = resp.json()
    digest = body.get("details", {}).get("digest") or body.get("digest", "")
    if not digest:
        # Fall back to the tags listing, which always carries the digest.
        tags = requests.get("http://localhost:11434/api/tags", timeout=30).json()
        for entry in tags.get("models", []):
            if entry.get("name") == model:
                digest = entry.get("digest", "")
    return str(digest)


def _verification_script(instance: SWEBenchInstance) -> str:
    """Standalone reproduction of SWEBenchKeywords.apply_and_test_patch."""
    return f"""#!/usr/bin/env bash
# Reproduces the robotframework-chat SWE-bench harness verification for
# {instance.instance_id} (see src/rfc/swebench_keywords.py, apply_and_test_patch).
# Run from the directory containing generated.patch and test_patch.diff.
# Exits with the real verification exit code.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="arc-pilot-{instance.instance_id[:30]}"

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --cpus 1.0 --memory 2048m --user root \\
    -w /workspace python:3.11-slim sleep 3600 >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1' EXIT

x() {{ docker exec -w /workspace "$NAME" sh -c "$1"; }}

x "apt-get update -qq && apt-get install -y -qq git >/dev/null 2>&1"
x "git clone --quiet https://github.com/{instance.repo}.git /workspace \\
   && cd /workspace && git checkout -q {instance.base_commit}" || exit $?

docker cp "$HERE/test_patch.diff" "$NAME:/tmp/test_patch.diff"
x "git apply --allow-empty /tmp/test_patch.diff" || exit $?

x "pip install -e . 2>/dev/null || pip install -r requirements.txt 2>/dev/null || true"

docker cp "$HERE/generated.patch" "$NAME:/tmp/patch.diff"
x "git apply --allow-empty /tmp/patch.diff" || exit $?

x "python -m pytest --tb=short -q"
exit $?
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--model", default="llama3:latest")
    parser.add_argument("--out", default="pilots/arc-issue-390")
    args = parser.parse_args()

    kw = SWEBenchKeywords()
    instances = kw.load_swebench_instances(
        split="test", max_instances=1000, dataset=_DATASET
    )
    matches = [i for i in instances if i.instance_id == args.instance_id]
    if not matches:
        print(f"instance {args.instance_id} not found in {_DATASET}", file=sys.stderr)
        return 2
    instance = matches[0]

    out_dir = Path(args.out) / instance.instance_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Generation (no gold/test patch in scope) -------------------------
    prompt = _PROMPT_TEMPLATE.format(
        repo=instance.repo,
        base_commit=instance.base_commit,
        problem_statement=instance.problem_statement,
    )
    llm = LLMKeywords()
    llm.set_llm_model(args.model)
    print(f"Generating patch for {instance.instance_id} with {args.model} ...")
    patch = llm.ask_llm(prompt)
    (out_dir / "generated.patch").write_text(patch)
    print(f"generated.patch written ({len(patch)} bytes)")

    # --- Post-generation artifacts ----------------------------------------
    (out_dir / "instance.json").write_text(
        json.dumps(dataclasses.asdict(instance), indent=2)
    )
    (out_dir / "gold.patch").write_text(instance.patch)
    (out_dir / "test_patch.diff").write_text(instance.test_patch)
    (out_dir / "scope.json").write_text(
        json.dumps(
            {
                "source": "files touched by gold.patch",
                "expected_files": _gold_patch_files(instance.patch),
                "prohibited_scope": "all files not listed in expected_files",
            },
            indent=2,
        )
    )
    script_path = out_dir / "verification.sh"
    script_path.write_text(_verification_script(instance))
    script_path.chmod(0o755)

    # --- Harness verification (authoritative PatchResult) ------------------
    print("Running harness verification (apply_and_test_patch) ...")
    result = kw.apply_and_test_patch(instance, patch)
    print(f"PatchResult: passed={result.passed} exit_code={result.exit_code}")

    harness_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    (out_dir / "result.json").write_text(
        json.dumps(
            {
                "schema_version": _SCHEMA_VERSION,
                "instance_id": instance.instance_id,
                "dataset": _DATASET,
                "generation": {
                    "provider": "ollama",
                    "model": args.model,
                    "model_version_or_digest": _ollama_digest(args.model),
                    "harness": "robotframework-chat SWE-bench",
                    "harness_commit": harness_commit,
                },
                "artifacts": {
                    "instance": "instance.json",
                    "generated_patch": "generated.patch",
                    "gold_patch": "gold.patch",
                    "scope": "scope.json",
                    "verification_script": "verification.sh",
                    "verification_log": "verification.log",
                },
                "patch_result": {
                    "passed": result.passed,
                    "exit_code": result.exit_code,
                    "test_output": result.test_output,
                },
            },
            indent=2,
        )
    )
    print(f"Package written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
