"""Instrument controls: wrong, empty, contaminated and incomplete runs cannot pass."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from rfc.hardware_eval import (
    build_pack,
    compare_runs as compare_paired,
    load_benchmark,
    parse_answer,
    score_answer,
)

FIXTURES = (
    Path(__file__).resolve().parents[1]
    / "robot/10__tier1/hardware_engineering/fixtures"
)


def compare_runs(baseline, candidate):
    return compare_paired(baseline, candidate, {("a", 16384, "middle", 0)})


def test_gate_requires_an_independent_coverage_manifest():
    assert compare_paired([row()], [row()])["verdict"] == "incomplete"
    required = {("a", 16384, "middle", 0), ("b", 16384, "middle", 0)}
    assert compare_paired([row()], [row()], required)["verdict"] == "incomplete"


@pytest.fixture
def benchmark():
    return load_benchmark(FIXTURES)


@pytest.fixture
def case(benchmark):
    return benchmark["cases"]["uno-current-budget"]


def gold_answer(case):
    return {
        "answers": [
            {"id": k, "value": v["value"], "evidence": v["evidence"]}
            for k, v in case["expected"].items()
        ],
        "explanation": "Fixture oracle; never use this response as live model evidence.",
    }


def test_fixture_catalog_has_real_sources_and_held_out_answers(benchmark):
    assert len(benchmark["cases"]) >= 16
    for doc in benchmark["documents"].values():
        assert doc["revision"]
        assert doc["location"]
        assert doc["sha256"]
        if doc["kind"] == "public":
            assert doc["url"].startswith("https://")
            assert doc["license"]
    for item in benchmark["cases"].values():
        assert item["expected"]
        assert {q["id"] for q in item["questions"]} == set(item["expected"])
        for expected in item["expected"].values():
            assert expected["evidence"]
            assert set(expected["evidence"]) <= set(item["documents"])


def test_pack_has_no_grading_key(case, benchmark):
    pack = build_pack(case, benchmark["documents"])
    assert '"expected"' not in pack["prompt"]
    assert "critical" not in pack["prompt"]
    assert pack["prompt_sha256"]
    assert pack["reference_tokens"] is None
    assert "UNO" in pack["prompt"]


def test_gold_answer_passes(case):
    result = score_answer(case, gold_answer(case))
    assert result["passed"]
    assert result["accuracy"] == result["citation_accuracy"] == 1
    assert result["critical_failures"] == 0


@pytest.mark.parametrize("bad", [{}, {"answers": []}, {"answers": "garbage"}, None])
def test_empty_or_malformed_answer_fails_closed(case, bad):
    result = score_answer(case, bad)
    assert not result["passed"]
    assert result["critical_failures"] > 0


def test_correct_words_in_explanation_do_not_override_wrong_answer(case):
    answer = gold_answer(case)
    answer["answers"][0]["value"] = "unsafe invented answer"
    answer["explanation"] = json.dumps(gold_answer(case))
    assert not score_answer(case, answer)["passed"]


def test_duplicate_answer_ids_are_rejected(case):
    answer = gold_answer(case)
    answer["answers"].append(answer["answers"][0])
    assert not score_answer(case, answer)["passed"]


def test_unknown_question_is_not_ignored(case):
    answer = gold_answer(case)
    answer["answers"].append({"id": "invented", "value": True, "evidence": []})
    assert not score_answer(case, answer)["passed"]


def test_correct_answer_with_wrong_source_fails(case):
    answer = gold_answer(case)
    answer["answers"][0]["evidence"] = ["made-up-datasheet"]
    score = score_answer(case, answer)
    assert not score["passed"]
    assert score["citation_accuracy"] < 1


def test_boolean_does_not_pass_as_number(case):
    answer = gold_answer(case)
    numeric = next(a for a in answer["answers"] if type(a["value"]) is int)
    numeric["value"] = True
    assert not score_answer(case, answer)["passed"]


def test_numeric_tolerance_and_nan(benchmark):
    case = benchmark["cases"]["uno-led-resistor"]
    answer = gold_answer(case)
    field = next(a for a in answer["answers"] if a["id"] == "resistance_ohm")
    field["value"] += 0.1
    assert score_answer(case, answer)["passed"]
    field["value"] = float("nan")
    assert not score_answer(case, answer)["passed"]


def test_parse_only_final_json_not_thinking():
    assert parse_answer('<think>{"answers":[]}</think>{"answers":[1]}') == {
        "answers": [1]
    }
    with pytest.raises(ValueError):
        parse_answer('<think>{"answers":[1]}</think>')
    with pytest.raises(ValueError):
        parse_answer('{"answers": [], "answers": [1]}')
    with pytest.raises(ValueError):
        parse_answer('{"value":NaN}')


def test_long_pack_requires_real_tokenizer(case, benchmark):
    with pytest.raises(ValueError, match="token"):
        build_pack(case, benchmark["documents"], context_tokens=16384)


def test_long_pack_is_deterministic_and_places_evidence(case, benchmark):
    # A character counter is an injected test double, never a live tokenizer.
    a = build_pack(
        case,
        benchmark["documents"],
        context_tokens=16384,
        counter=len,
        position="middle",
        seed=7,
    )
    b = build_pack(
        case,
        benchmark["documents"],
        context_tokens=16384,
        counter=len,
        position="middle",
        seed=7,
    )
    assert a == b
    assert 0.9 * a["input_budget"] <= a["reference_tokens"] <= a["input_budget"]
    assert 0.35 < min(a["evidence_positions"].values()) < 0.65
    assert len(set(a["distractor_ids"])) == len(a["distractor_ids"])


@pytest.mark.parametrize("position", ["start", "middle", "end", "spread"])
def test_context_budget_includes_question_and_output(case, benchmark, position):
    pack = build_pack(
        case,
        benchmark["documents"],
        context_tokens=16384,
        counter=len,
        position=position,
    )
    assert pack["reference_tokens"] + pack["output_reserve"] + 256 <= 16384
    for doc_id in case["documents"]:
        assert pack["prompt"].count(f"[DOCUMENT {doc_id}]") == 1


def test_tiny_budget_never_truncates_evidence(case, benchmark):
    with pytest.raises(ValueError, match="budget"):
        build_pack(case, benchmark["documents"], context_tokens=100, counter=len)


def row(case_id="a", **overrides):
    result = {
        "case_id": case_id,
        "context_tokens": 16384,
        "position": "middle",
        "trial": 0,
        "prompt_sha256": "prompt",
        "fixture_sha256": "fixture",
        "grader_version": "v1",
        "harness_version": "v1",
        "reference_tokenizer": "abc",
        "sampling": {"temperature": 0.0, "seed": 0, "max_tokens": 2048},
        "model": "baseline",
        "model_digest": "sha-a",
        "adapter_id": "none",
        "status": "completed",
        "live": True,
        "accuracy": 0.75,
        "citation_accuracy": 1.0,
        "critical_failures": 0,
        "unsafe_actions": 0,
        "schema_valid": True,
        "token_count_verified": True,
    }
    result.update(overrides)
    return result


def test_gate_requires_nonempty_identical_coverage():
    assert compare_runs([], [])["verdict"] == "incomplete"
    assert compare_runs([row()], [])["verdict"] == "incomplete"
    assert compare_runs([row()], [row("b")])["verdict"] == "incomplete"


def test_gate_eligible_does_not_mean_deployed():
    result = compare_runs(
        [row()], [row(model="candidate", model_digest="sha-b", accuracy=1.0)]
    )
    assert result["verdict"] == "eligible"
    assert result["deployment_performed"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"critical_failures": 1},
        {"unsafe_actions": 1},
        {"accuracy": 0.5},
        {"citation_accuracy": 0.5},
        {"schema_valid": False},
    ],
)
def test_regression_blocks_gate(change):
    assert compare_runs([row()], [row(**change)])["verdict"] == "blocked"


@pytest.mark.parametrize(
    "change",
    [
        {"status": "unsupported_context"},
        {"status": "error"},
        {"live": False},
        {"model_digest": ""},
        {"token_count_verified": False},
        {"prompt_sha256": "different"},
        {"fixture_sha256": "different"},
        {"sampling": {"temperature": 0.7}},
        {"harness_version": "v2"},
    ],
)
def test_missing_or_noncomparable_evidence_is_incomplete(change):
    assert compare_runs([row()], [row(**change)])["verdict"] == "incomplete"


def test_duplicate_coordinates_and_mixed_models_rejected():
    assert compare_runs([row(), row()], [row(), row()])["verdict"] == "incomplete"
    baseline = [row("a"), row("b")]
    candidate = [row("a", model="x"), row("b", model="y")]
    assert compare_runs(baseline, candidate)["verdict"] == "incomplete"


def test_all_gold_answers_pass_and_all_corruptions_fail(benchmark):
    for case in benchmark["cases"].values():
        answer = gold_answer(case)
        assert score_answer(case, answer)["passed"], case["id"]
        broken = copy.deepcopy(answer)
        broken["answers"][0]["value"] = {"invented": 999}
        assert not score_answer(case, broken)["passed"], case["id"]


def test_real_tokenizer_builds_one_million_budget_without_truncating_sources(benchmark):
    """Instrument capacity test only, not a 1M-token model-serving claim."""
    tokenizers = pytest.importorskip("tokenizers")
    tokenizer = tokenizers.Tokenizer(
        tokenizers.models.WordLevel({"[UNK]": 0}, unk_token="[UNK]")
    )
    tokenizer.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    counter = lambda text: len(tokenizer.encode(text).ids)  # noqa: E731
    case = benchmark["cases"]["mixed-voltage-review"]
    pack = build_pack(
        case,
        benchmark["documents"],
        context_tokens=1000000,
        counter=counter,
        position="spread",
    )
    assert 990000 <= pack["reference_tokens"] <= pack["input_budget"]
    assert pack["reference_tokens"] + 2048 + 256 <= 1000000
    assert len(pack["evidence_positions"]) == len(case["documents"])
    assert "N1: UNO.D1_TX" in pack["prompt"]
