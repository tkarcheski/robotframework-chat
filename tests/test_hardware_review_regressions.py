"""PR 714 review reproducers; no live inference."""

import copy
import json
from unittest.mock import Mock

import pytest

from rfc.hardware_eval import score_answer
from rfc.hardware_eval_keywords import HardwareEvalKeywords
from rfc.llm_client import _ConsoleFeedProvider
from test_hardware_eval import FIXTURES, compare_runs, gold_answer, load_benchmark, row


def test_sampling_reaches_wrapped_transport(tmp_path, monkeypatch):
    monkeypatch.setenv("HW_MAX_CONTEXT", "8192")
    case = load_benchmark(FIXTURES)["cases"]["uno-current-budget"]
    transport = Mock(
        model="test",
        base_url="http://127.0.0.1",
        seed=None,
        num_ctx=None,
        last_metrics={},
    )
    transport.generate.return_value = json.dumps(gold_answer(case))
    wrapped = _ConsoleFeedProvider(transport)
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path), client=wrapped)
    lib.evaluate_hardware_case("uno-current-budget", trial=2)
    assert transport.seed == 2
    assert transport.num_ctx == 8192
    saved = json.loads((tmp_path / "hardware-results.jsonl").read_text())
    assert saved["effective_context_tokens"] == 8192


def test_short_run_effective_context_is_held_fixed():
    assert (
        compare_runs(
            [row(effective_context_tokens=16384)], [row(effective_context_tokens=8192)]
        )["verdict"]
        == "incomplete"
    )


@pytest.mark.parametrize("candidate_format", ["BF16", "", None, "unspecified"])
def test_gate_rejects_changed_or_unknown_weights(candidate_format):
    assert (
        compare_runs(
            [row(weights_format="UD-Q4_K_M")], [row(weights_format=candidate_format)]
        )["verdict"]
        == "incomplete"
    )


def test_large_wrong_integer_is_a_model_failure():
    case = load_benchmark(FIXTURES)["cases"]["uno-current-budget"]
    answer = gold_answer(case)
    answer["answers"][0]["value"] = 10**400
    score = score_answer(case, answer)
    assert not score["passed"]
    assert not score["checks"]["total_ma"]["correct"]


def test_equal_aggregate_scores_do_not_hide_question_regression():
    checks = {
        "one": {"correct": True, "citation_correct": True},
        "two": {"correct": False, "citation_correct": True},
    }
    old = row(weights_format="UD-Q4_K_M", checks=checks, accuracy=0.5)
    new = copy.deepcopy(old)
    new["checks"]["one"]["correct"] = False
    new["checks"]["two"]["correct"] = True
    assert compare_runs([old], [new])["verdict"] == "blocked"


@pytest.mark.parametrize(
    "checks",
    [
        None,
        {},
        [],
        {"q": {}},
        {"q": {"correct": 1, "citation_correct": True}},
        {"q": None},
    ],
)
def test_missing_or_malformed_checks_cannot_pass(checks):
    old = row(checks=checks)
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


def test_omitted_check_maps_cannot_pass():
    old = row()
    del old["checks"]
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


@pytest.mark.parametrize("flag", ["false", "true", 1])
def test_token_verification_requires_boolean_true(flag):
    old = row(token_count_verified=flag)
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


def test_partial_question_coverage_cannot_pass():
    old = row()
    new = copy.deepcopy(old)
    del old["checks"]["q0"]
    assert compare_runs([old], [new])["verdict"] == "incomplete"


@pytest.mark.parametrize("cap", [32768, 65536])
def test_long_pack_records_server_allocation_not_input_coordinate(
    tmp_path, monkeypatch, cap
):
    from rfc.openai_client import OpenAIClient

    monkeypatch.setenv("HW_MAX_CONTEXT", str(cap))
    monkeypatch.setattr(
        "rfc.hardware_eval_keywords.token_counter",
        lambda path: (len, "test-character-counter"),
    )
    case = load_benchmark(FIXTURES)["cases"]["uno-current-budget"]
    client = OpenAIClient(api_key="test", model="test", base_url="http://127.0.0.1")
    monkeypatch.setattr(
        client, "generate", lambda prompt: json.dumps(gold_answer(case))
    )
    lib = HardwareEvalKeywords(
        str(FIXTURES), str(tmp_path), client=_ConsoleFeedProvider(client)
    )
    result = lib.evaluate_hardware_case("uno-current-budget", context_tokens=16384)
    assert result["context_tokens"] == 16384
    assert result["effective_context_tokens"] == cap
    assert client.num_ctx == cap
