"""Instrument controls: wrong, empty, contaminated and incomplete runs cannot pass."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from rfc.hardware_eval import (
    GRADER_VERSION,
    browser_task_prompt,
    browser_history_prompt,
    digest,
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


def synthetic_benchmark(questions=None):
    """Independent synthetic answer schema for artifact-validation unit tests."""
    questions = (
        questions if questions is not None else {f"q{i}": False for i in range(4)}
    )
    return {
        "sha256": "b" * 64,
        "cases": {
            case: {
                "task": "Synthetic fixture task",
                "questions": [{"id": q, "question": q} for q in questions],
                "expected": {
                    q: {"critical": critical} for q, critical in questions.items()
                },
            }
            for case in ("a", "b", "task")
        },
    }


def compare_runs(baseline, candidate, benchmark=None):
    return compare_paired(
        baseline,
        candidate,
        {("a", 16384, "middle", 0)},
        benchmark if benchmark is not None else synthetic_benchmark(),
    )


def test_gate_requires_an_independent_coverage_manifest():
    assert compare_paired([row()], [row()])["verdict"] == "incomplete"
    required = {("a", 16384, "middle", 0), ("b", 16384, "middle", 0)}
    assert (
        compare_paired([row()], [row()], required, synthetic_benchmark())["verdict"]
        == "incomplete"
    )


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
        "effective_context_tokens": 16384,
        "position": "middle",
        "trial": 0,
        "prompt_sha256": "a" * 64,
        "fixture_sha256": "b" * 64,
        "grader_version": GRADER_VERSION,
        "harness_version": "c" * 64,
        "reference_tokenizer": "d" * 64,
        "model_tokenizer": "e" * 64,
        "sampling": {
            "temperature": 0.0,
            "seed": 0,
            "max_tokens": 2048,
            "json_schema": None,
        },
        "runtime_manifest": {
            "server_build": {"executable_sha256": "f" * 64, "shared_libraries": []},
            "engine": "vllm",
            "version": "fixture-v1",
            "rope": "native",
            "kv_cache_dtype": "bf16",
            "gpu_layers": 999,
            "kv_placement": "gpu",
            "cpu_ffn_layers": 0,
            "cpu_moe_layers": 0,
            "parallel": 1,
            "n_batch": 512,
            "n_ubatch": 128,
            "threads": 8,
            "host_prompt_cache_mib": 0,
            "enable_thinking": False,
            "speculation": "off",
            "vision": False,
            "fit": False,
            "context_shift": False,
            "cuda_managed_memory": False,
        },
        "model": "baseline",
        "model_digest": "sha-a",
        "adapter_id": "none",
        "weights_format": "UD-Q4_K_M",
        "status": "completed",
        "live": True,
        "accuracy": 0.75,
        "citation_accuracy": 1.0,
        "critical_failures": 0,
        "unsafe_actions": 0,
        "schema_valid": True,
        "token_count_verified": True,
        "calls": [
            {
                "prompt_sha256": "a" * 64,
                "local_input_tokens": 100,
                "server_metrics": {
                    "prompt_eval_count": 112,
                    "eval_count": 20,
                    "finish_reason": "stop",
                },
                "token_count_verified": True,
            }
        ],
    }
    result.update(overrides)
    if case_id.endswith(":browser"):
        name = case_id.removesuffix(":browser")
        case = synthetic_benchmark()["cases"].get(name)
        if case is None:
            case = load_benchmark(FIXTURES)["cases"][name]
        prompt = browser_task_prompt(case)
        if "prompt_sha256" not in overrides:
            result["prompt_sha256"] = digest(prompt)
        result.setdefault("browser_trace", [])
        result.setdefault("agent_status", "completed")
        if "calls" not in overrides:
            result["calls"][0]["prompt_sha256"] = digest(
                browser_history_prompt(prompt, [])
            )
    elif "calls" not in overrides:
        result["calls"][0]["prompt_sha256"] = result["prompt_sha256"]
    if "sampling" not in overrides:
        result["sampling"]["seed"] = result["trial"]
    if "checks" not in overrides:
        result["checks"] = {
            f"q{i}": {
                "correct": i < result["accuracy"] * 4,
                "citation_correct": i < result["citation_accuracy"] * 4,
                "critical": i >= 4 - result["critical_failures"],
            }
            for i in range(4)
        }
    if "passed" not in overrides:
        result["passed"] = (
            result["schema_valid"] is True
            and result["accuracy"] == result["citation_accuracy"] == 1
            and result["unsafe_actions"] == 0
            and (
                not case_id.endswith(":browser")
                or (
                    result.get("sources_observed") is True
                    and result.get("report_saved") is True
                )
            )
        )
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
    baseline = row()
    candidate = row(**change)
    if "critical_failures" in change:
        baseline = row(accuracy=1.0)
        for question, check in candidate["checks"].items():
            baseline["checks"][question]["critical"] = check["critical"]
    benchmark = (
        synthetic_benchmark({f"q{i}": i == 3 for i in range(4)})
        if "critical_failures" in change
        else synthetic_benchmark()
    )
    assert compare_runs([baseline], [candidate], benchmark)["verdict"] == "blocked"


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
        {
            "runtime_manifest": {
                "engine": "different",
                "version": "v2",
                "rope": "yarn",
                "kv_cache_dtype": "fp8",
            }
        },
        {"runtime_manifest": {}},
    ],
)
def test_missing_or_noncomparable_evidence_is_incomplete(change):
    assert compare_runs([row()], [row(**change)])["verdict"] == "incomplete"


def test_duplicate_coordinates_and_mixed_models_rejected():
    assert compare_runs([row(), row()], [row(), row()])["verdict"] == "incomplete"
    baseline = [row("a"), row("b")]
    candidate = [row("a", model="x"), row("b", model="y")]
    assert compare_runs(baseline, candidate)["verdict"] == "incomplete"


def test_both_arms_missing_runtime_metadata_do_not_pass():
    assert (
        compare_runs([row(runtime_manifest={})], [row(runtime_manifest={})])["verdict"]
        == "incomplete"
    )


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
