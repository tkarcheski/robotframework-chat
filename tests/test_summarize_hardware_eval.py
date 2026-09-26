"""Avoid treating repeated deterministic trials as independent comparisons."""

from copy import deepcopy

import pytest

from scripts.summarize_hardware_eval import compare
from test_hardware_eval import row


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
    result = compare(old, new)
    assert result["paired_rows"] == 6
    assert result["independent_case_clusters"] == 2
    assert result["metrics"]["accuracy"]["delta"] == 1
    assert result["metrics"]["accuracy"]["case_cluster_bootstrap_95_percent"] == [1, 1]


def test_changed_runtime_does_not_pass_as_model_only_comparison():
    old = rows()
    new = deepcopy(old)
    next(iter(new.values()))["runtime_manifest"]["enable_thinking"] = True
    with pytest.raises(ValueError, match="Unverified comparison"):
        compare(old, new)


def test_incomplete_comparison_is_rejected():
    old = rows()
    new = deepcopy(old)
    new.pop(next(iter(new)))
    with pytest.raises(ValueError, match="coverage"):
        compare(old, new)
