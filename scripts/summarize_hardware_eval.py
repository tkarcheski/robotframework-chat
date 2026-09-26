#!/usr/bin/env python3
"""Paired descriptive model comparison with case-cluster uncertainty.

Repeated greedy trials are not independent samples. Bootstrap entire case IDs,
retaining all paired positions/trials of a case in every resampled cluster.
This report is exploratory; it does not replace the required-profile gate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import statistics

from rfc.hardware_eval import compare_runs

FIELDS = ("case_id", "context_tokens", "position", "trial")
FIXED = (
    "prompt_sha256",
    "fixture_sha256",
    "harness_version",
    "grader_version",
    "reference_tokenizer",
    "sampling",
    "runtime_manifest",
    "weights_format",
    "effective_context_tokens",
)


def read(path):
    rows = [
        json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()
    ]
    by_key = {tuple(r[k] for k in FIELDS): r for r in rows}
    if len(rows) != len(by_key):
        raise ValueError("Duplicate coordinates")
    return by_key


def compare(old, new):
    if not old or old.keys() != new.keys():
        raise ValueError("Missing or unequal coverage")
    gate = compare_runs(list(old.values()), list(new.values()), set(old))
    if gate["verdict"] == "incomplete":
        raise ValueError(f"Unverified comparison: {gate['reasons']}")
    cases = {}
    for key, a in old.items():
        b = new[key]
        if any(a.get(k) != b.get(k) for k in FIXED):
            raise ValueError(f"Changed comparison coordinates: {key}")
        if any(
            r.get("status") != "completed"
            or not r.get("live")
            or not r.get("token_count_verified")
            for r in (a, b)
        ):
            raise ValueError(f"Incomplete/unverified result: {key}")
        cases.setdefault(key[0], []).append((a, b))
    details = []
    for case, pairs in sorted(cases.items()):
        item = {"case_id": case, "paired_rows": len(pairs)}
        for metric in ("accuracy", "citation_accuracy", "passed", "latency_ms"):
            for arm, i in (("baseline", 0), ("candidate", 1)):
                item[f"{arm}_{metric}"] = statistics.mean(p[i][metric] for p in pairs)
            item[f"delta_{metric}"] = (
                item[f"candidate_{metric}"] - item[f"baseline_{metric}"]
            )
        details.append(item)
    rng = random.Random(714)
    summary = {
        "paired_rows": len(old),
        "independent_case_clusters": len(cases),
        "baseline_model": next(iter(old.values()))["model"],
        "candidate_model": next(iter(new.values()))["model"],
        "scope": "exploratory paired comparison, not full-profile eligibility",
        "reasoning": next(iter(old.values()))["runtime_manifest"].get(
            "enable_thinking"
        ),
        "cases": details,
        "metrics": {},
    }
    for metric in ("accuracy", "citation_accuracy", "passed"):
        deltas = [d[f"delta_{metric}"] for d in details]
        draws = sorted(
            statistics.mean(rng.choices(deltas, k=len(deltas))) for _ in range(10000)
        )
        delta = statistics.mean(deltas)
        ci = [draws[250], draws[9749]]
        summary["metrics"][metric] = {
            "baseline": statistics.mean(d[f"baseline_{metric}"] for d in details),
            "candidate": statistics.mean(d[f"candidate_{metric}"] for d in details),
            "delta": delta,
            "case_cluster_bootstrap_95_percent": ci,
            "practical_improvement_at_least_10pp_and_ci_above_zero": delta >= 0.1
            and ci[0] > 0,
        }
    summary["unanimous_full_pass_cases"] = [
        d["case_id"]
        for d in details
        if d["baseline_passed"] == d["candidate_passed"] == 1
    ]
    summary["note"] = (
        "A unanimous pass is a ceiling-effect candidate, not automatic skip:low-value. "
        "Retain safety/negative controls and confirm across contexts/model arms before demotion. "
        "Intervals describe variation across this small public task set; no population/general superiority claim."
    )
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("baseline", type=Path)
    p.add_argument("candidate", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = compare(read(args.baseline), read(args.candidate))
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps({k: v for k, v in result.items() if k not in ("cases",)}, indent=2)
    )


if __name__ == "__main__":
    main()
