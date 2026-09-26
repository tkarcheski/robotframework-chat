#!/usr/bin/env python3
"""Paired descriptive model comparison with case-cluster uncertainty.

Repeated greedy trials are not independent samples. Bootstrap entire case IDs,
retaining all paired positions/trials of a case in every resampled cluster.
This report is exploratory; it does not replace the required-profile gate.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random
import statistics

from rfc.hardware_eval import compare_runs, load_benchmark

DEFAULT_FIXTURES = (
    Path(__file__).resolve().parents[1]
    / "robot/10__tier1/hardware_engineering/fixtures"
)

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


def hardware_known(row):
    hardware = row["runtime_manifest"].get("hardware")

    def sha256(value):
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(c in "0123456789abcdef" for c in value)
        )

    if not isinstance(hardware, dict) or not (
        sha256(hardware.get("host_sha256"))
        and isinstance(hardware.get("cpu_model"), str)
        and hardware["cpu_model"].strip()
        and all(
            type(hardware.get(key)) is int and hardware[key] > 0
            for key in ("logical_cpus", "ram_bytes")
        )
        and type(hardware.get("uses_gpu")) is bool
        and isinstance(hardware.get("gpus"), list)
        and bool(hardware["gpus"]) == hardware["uses_gpu"]
    ):
        return False
    return all(
        isinstance(gpu, dict)
        and sha256(gpu.get("uuid_sha256"))
        and all(
            isinstance(gpu.get(key), str) and gpu[key].strip()
            for key in ("name", "driver")
        )
        and type(gpu.get("memory_mib")) is int
        and gpu["memory_mib"] > 0
        for gpu in hardware["gpus"]
    )


def finite_latency(row):
    value = row.get("latency_ms")
    try:
        return type(value) in (int, float) and value >= 0 and math.isfinite(value)
    except OverflowError:
        return False


def compare(old, new, benchmark=None):
    if not old or old.keys() != new.keys():
        raise ValueError("Missing or unequal coverage")
    gate = compare_runs(
        list(old.values()),
        list(new.values()),
        set(old),
        benchmark if benchmark is not None else load_benchmark(DEFAULT_FIXTURES),
    )
    if gate["verdict"] == "incomplete":
        raise ValueError(f"Unverified comparison: {gate['reasons']}")
    all_rows = [*old.values(), *new.values()]
    latency_available = (
        all(hardware_known(row) and finite_latency(row) for row in all_rows)
        and len(
            {
                json.dumps(row["runtime_manifest"].get("hardware"), sort_keys=True)
                for row in all_rows
            }
        )
        == 1
    )
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
        for metric in (
            "accuracy",
            "citation_accuracy",
            "passed",
            *(("latency_ms",) if latency_available else ()),
        ):
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
        "latency": {
            "reported": latency_available,
            "scope": "matched declared hardware; load and thermal state are not controlled"
            if latency_available
            else "omitted: missing/mixed hardware identity or invalid latency",
        },
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
    p.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    args = p.parse_args()
    result = compare(
        read(args.baseline), read(args.candidate), load_benchmark(args.fixtures)
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps({k: v for k, v in result.items() if k not in ("cases",)}, indent=2)
    )


if __name__ == "__main__":
    main()
