"""Avoid treating repeated deterministic trials as independent comparisons."""

import json
from rfc.hardware_eval import digest

from copy import deepcopy

import pytest

from scripts.summarize_hardware_eval import compare
from test_hardware_eval import row, synthetic_benchmark


def rows():
    return {
        (case, 0, "spread", trial): row(
            case_id=case,
            context_tokens=0,
            position="spread",
            trial=trial,
            accuracy=0.0,
            citation_accuracy=1.0,
            passed=False,
            latency_ms=10.0,
        )
        for case in ("a", "b")
        for trial in range(3)
    }


def test_repetitions_remain_two_case_clusters():
    old = rows()
    new = deepcopy(old)
    for r in new.values():
        r.update(model="candidate", accuracy=1.0, passed=True)
        for check in r["checks"].values():
            check["correct"] = True
        for answer in r["answer"]["answers"]:
            answer["value"] = 1
        r["calls"][0]["response"] = json.dumps(r["answer"])
        r["calls"][0]["response_sha256"] = digest(r["calls"][0]["response"])
    result = compare(old, new, synthetic_benchmark())
    assert result["paired_rows"] == 6
    assert result["independent_case_clusters"] == 2
    assert result["metrics"]["accuracy"]["delta"] == 1
    assert result["metrics"]["accuracy"]["case_cluster_bootstrap_95_percent"] == [1, 1]
    assert not result["latency"]["reported"]
    assert not any("latency" in key for case in result["cases"] for key in case)


def with_hardware():
    result = rows()
    for value in result.values():
        value["runtime_manifest"]["hardware"] = {
            "host_sha256": "a" * 64,
            "cpu_model": "Test CPU",
            "logical_cpus": 8,
            "ram_bytes": 32 * 1024**3,
            "uses_gpu": False,
            "gpus": [],
        }
    return result


def test_matched_hardware_allows_descriptive_latency():
    old = with_hardware()
    new = deepcopy(old)
    for value in new.values():
        value["latency_ms"] = 20.0
    result = compare(old, new, synthetic_benchmark())
    assert result["latency"]["reported"]
    assert all(case["delta_latency_ms"] == 10.0 for case in result["cases"])


def test_different_hardware_does_not_become_a_model_latency_effect():
    old = with_hardware()
    new = deepcopy(old)
    for value in new.values():
        value["runtime_manifest"]["hardware"]["host_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="Unverified comparison"):
        compare(old, new, synthetic_benchmark())


@pytest.mark.parametrize("latency", [None, -1, float("nan"), float("inf"), True])
def test_invalid_latency_is_omitted(latency):
    old = with_hardware()
    for value in old.values():
        value["latency_ms"] = latency
    assert not compare(old, deepcopy(old), synthetic_benchmark())["latency"]["reported"]


def test_changed_runtime_does_not_pass_as_model_only_comparison():
    old = rows()
    new = deepcopy(old)
    next(iter(new.values()))["runtime_manifest"]["enable_thinking"] = True
    with pytest.raises(ValueError, match="Unverified comparison"):
        compare(old, new, synthetic_benchmark())


def test_incomplete_comparison_is_rejected():
    old = rows()
    new = deepcopy(old)
    new.pop(next(iter(new)))
    with pytest.raises(ValueError, match="coverage"):
        compare(old, new, synthetic_benchmark())
