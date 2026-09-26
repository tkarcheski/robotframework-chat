"""Live/offline boundaries and result persistence for the hardware keywords."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from rfc.exceptions import RFCSkipError
from rfc.hardware_eval import (
    load_benchmark,
    digest,
    emitted_answers_match,
    text_prompt_matches,
)
from rfc.hardware_eval_keywords import HardwareEvalKeywords, verify_token_usage
from test_hardware_eval import FIXTURES, gold_answer


def test_tokens_must_be_measured_and_not_silently_truncated():
    assert verify_token_usage(
        100,
        {"prompt_eval_count": 110, "eval_count": 10, "finish_reason": "stop"},
        256,
        32,
    )
    assert not verify_token_usage(100, {}, 256, 32)
    assert not verify_token_usage(
        None, {"prompt_eval_count": 110, "finish_reason": "stop"}, 256, 32
    )
    assert not verify_token_usage(
        100, {"prompt_eval_count": 80, "finish_reason": "stop"}, 256, 32
    )
    assert not verify_token_usage(
        100,
        {"prompt_eval_count": 240, "eval_count": 20, "finish_reason": "stop"},
        256,
        32,
    )
    assert not verify_token_usage(
        100,
        {"prompt_eval_count": 110, "eval_count": 32, "finish_reason": "stop"},
        256,
        32,
    )


def test_opt_in_required_and_disabled_run_is_archived(tmp_path, monkeypatch):
    monkeypatch.delenv("HW_EVAL_LIVE", raising=False)
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path))
    with pytest.raises(RFCSkipError, match="HW_EVAL_LIVE"):
        lib.evaluate_hardware_case("uno-current-budget")
    row = json.loads((tmp_path / "hardware-results.jsonl").read_text())
    assert row["status"] == "disabled"
    assert row["live"] is False


def test_mocked_model_never_claims_live_or_deployment_evidence(tmp_path):
    benchmark = load_benchmark(FIXTURES)
    client = MagicMock()
    client.model = "scripted-test-double"
    client.generate.return_value = json.dumps(
        gold_answer(benchmark["cases"]["uno-current-budget"])
    )
    client.last_metrics = {"prompt_eval_count": 500, "eval_count": 100}
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path), client=client)
    result = lib.evaluate_hardware_case("uno-current-budget")
    assert result["passed"]
    assert result["answer"] == json.loads(client.generate.return_value)
    assert result["calls"][0]["response"] == client.generate.return_value
    assert result["calls"][0]["response_sha256"] == digest(client.generate.return_value)
    assert emitted_answers_match(result)
    assert text_prompt_matches(
        result, benchmark["cases"]["uno-current-budget"], benchmark["documents"]
    )
    assert (
        json.loads((tmp_path / "hardware-results.jsonl").read_text())["answer"]
        == result["answer"]
    )
    assert not result["live"]
    assert not result["token_count_verified"]
    assert (tmp_path / "hardware-results.jsonl").exists()
    assert (tmp_path / result["artifact"] / "response.txt").read_text() == result[
        "calls"
    ][0]["response"]
    assert (
        tmp_path / result["artifact"] / "call-001-response.txt"
    ).read_text() == result["calls"][0]["response"]


def test_output_budget_is_requested_and_archived(tmp_path, monkeypatch):
    monkeypatch.setenv("HW_OUTPUT_TOKENS", "4096")
    monkeypatch.setenv("HW_EVAL_LIVE", "1")
    monkeypatch.setenv("RFC_RUN_MODE", "measure")
    monkeypatch.setenv("ANSWER_CACHE_ENABLED", "0")
    client = MagicMock(model="test", last_metrics={})
    client.generate.return_value = '{"answers":[]}'
    factory = MagicMock(return_value=client)
    monkeypatch.setattr("rfc.hardware_eval_keywords.create_provider", factory)
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path))
    result = lib.evaluate_hardware_case("uno-current-budget")
    assert factory.call_args.kwargs["max_tokens"] == 4096
    assert result["sampling"]["max_tokens"] == 4096
    assert result["output_reserve"] == 4096


def test_nonpositive_output_budget_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("HW_OUTPUT_TOKENS", "0")
    with pytest.raises(ValueError, match="positive"):
        HardwareEvalKeywords(str(FIXTURES), str(tmp_path))


@pytest.mark.parametrize(
    "reason", ["stop", None, "length", "content_filter", "tool_calls", "unknown"]
)
def test_only_normal_completion_can_attest_token_usage(reason):
    from rfc.openai_client import _extract_metrics

    metrics = _extract_metrics(
        {
            "choices": [{"finish_reason": reason}],
            "usage": {"prompt_tokens": 110, "completion_tokens": 10},
        },
        "local-model",
    )
    assert metrics["finish_reason"] == reason
    assert verify_token_usage(100, metrics, 256, 32) is (reason == "stop")


def test_trial_parameters_reach_nested_provider_wrappers(tmp_path, monkeypatch):
    class ReadThroughProvider:
        """Match provider wrappers that delegate reads, not writes."""

        def __init__(self, wrapped):
            self.__wrapped__ = wrapped

        def __getattr__(self, name):
            return getattr(self.__wrapped__, name)

    benchmark = load_benchmark(FIXTURES)
    client = MagicMock()
    client.model = "scripted-test-double"
    client.seed = None
    client.num_ctx = None
    client.generate.return_value = json.dumps(
        gold_answer(benchmark["cases"]["uno-current-budget"])
    )
    client.last_metrics = {}
    monkeypatch.setenv("HW_MAX_CONTEXT", "32768")
    wrapped = ReadThroughProvider(ReadThroughProvider(client))
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path), client=wrapped)

    result = lib.evaluate_hardware_case("uno-current-budget", trial=2)

    assert result["passed"]
    assert client.seed == 2
    assert client.num_ctx == 32768
    assert "seed" not in vars(wrapped)
    assert "num_ctx" not in vars(wrapped)
    client.generate.assert_called_once()


def test_wrong_model_answer_is_completed_failure_not_infrastructure_skip(tmp_path):
    client = MagicMock()
    client.model = "mock"
    client.generate.return_value = '{"answers":[]}'
    client.last_metrics = {}
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path), client=client)
    result = lib.evaluate_hardware_case("uno-current-budget")
    assert result["status"] == "completed"
    assert not result["passed"]


def test_context_above_declared_cap_is_skipped_and_archived(tmp_path, monkeypatch):
    monkeypatch.setenv("HW_MAX_CONTEXT", "32768")
    lib = HardwareEvalKeywords(
        str(FIXTURES), str(tmp_path), client=MagicMock(model="mock")
    )
    with pytest.raises(RFCSkipError, match="context"):
        lib.evaluate_hardware_case("uno-current-budget", 65536)
    row = json.loads((tmp_path / "hardware-results.jsonl").read_text())
    assert row["status"] == "unsupported_context"


def test_bad_response_json_does_not_disappear(tmp_path):
    client = MagicMock()
    client.model = "mock"
    client.generate.return_value = "not-json"
    client.last_metrics = {}
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path), client=client)
    result = lib.evaluate_hardware_case("uno-current-budget")
    assert not result["passed"]
    assert result["parse_error"]


def test_case_listing_exposes_ids_not_grading_keys(tmp_path):
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path))
    assert len(lib.get_hardware_case_ids()) >= 18
    assert lib.get_hardware_case_ids("context") == [
        "fire-pinmux-change",
        "qualification-review",
        "injection-resistant-review",
    ]


def test_full_gate_profile_blocks_cherry_picked_results(tmp_path):
    from test_hardware_eval import row

    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path))
    path = tmp_path / "partial.jsonl"
    path.write_text(json.dumps(row()) + "\n")
    result = lib.compare_hardware_runs(str(path), str(path))
    assert result["verdict"] == "incomplete"
    assert "required_profile_mismatch" in result["reasons"]
    assert (tmp_path / "hardware-gate.json").exists()


@pytest.mark.parametrize("run_mode", ["verify", "replay"])
def test_replayed_results_cannot_masquerade_as_live(tmp_path, monkeypatch, run_mode):
    monkeypatch.setenv("HW_EVAL_LIVE", "1")
    monkeypatch.setenv("RFC_RUN_MODE", run_mode)
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path))
    with pytest.raises(RFCSkipError, match="caching/replay"):
        lib.evaluate_hardware_case("uno-current-budget")
    row = json.loads((tmp_path / "hardware-results.jsonl").read_text())
    assert row["live"] is False


def test_provider_failure_is_incomplete_and_archived(tmp_path):
    client = MagicMock()
    client.model = "mock"
    client.generate.side_effect = TimeoutError("test-only timeout")
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path), client=client)
    with pytest.raises(RFCSkipError, match="TimeoutError"):
        lib.evaluate_hardware_case("uno-current-budget")
    row = json.loads((tmp_path / "hardware-results.jsonl").read_text())
    assert row["status"] == "error"
    assert not row["passed"]


def test_failed_assertion_surfaces_to_robot(tmp_path):
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path))
    with pytest.raises(AssertionError, match="correctness"):
        lib.assert_hardware_case_passed({"case_id": "bad", "passed": False})


def test_invalid_json_archives_empty_parsed_answer(tmp_path):
    client = MagicMock(model="scripted-test-double", last_metrics={})
    client.generate.return_value = "not JSON"
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path), client=client)
    result = lib.evaluate_hardware_case("uno-current-budget")
    archived = json.loads((tmp_path / "hardware-results.jsonl").read_text())
    assert result["status"] == "completed"
    assert archived["answer"] == {}
    assert archived["schema_valid"] is False
    assert archived["accuracy"] == 0
    assert archived["parse_error"] == "JSONDecodeError"
    assert emitted_answers_match(archived)
    assert archived["calls"][0]["response"] == "not JSON"


@pytest.mark.parametrize("source", ["explicit", "environment", "missing"])
def test_offline_long_context_gate_loads_trusted_reference_tokenizer(
    tmp_path, monkeypatch, source
):
    from test_hardware_eval import row
    import yaml

    benchmark = load_benchmark(FIXTURES)
    case_id = "uno-current-budget"
    case = benchmark["cases"][case_id]
    from rfc.hardware_eval import score_answer

    result = row(
        case_id,
        fixture_sha256=benchmark["sha256"],
        **score_answer(case, gold_answer(case)),
    )
    artifact = tmp_path / "rows.jsonl"
    artifact.write_text(json.dumps(result) + "\n")
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        yaml.safe_dump(
            {
                "groups": [
                    {
                        "mode": "text",
                        "cases": [case_id],
                        "contexts": [16384],
                        "positions": ["middle"],
                        "trials": [0],
                    }
                ]
            }
        )
    )
    paths = []

    def load(path):
        paths.append(path)
        return (len, "d" * 64) if path else (None, "")

    monkeypatch.setattr("rfc.hardware_eval_keywords.token_counter", load)
    monkeypatch.delenv("HW_REFERENCE_TOKENIZER", raising=False)
    if source == "environment":
        monkeypatch.setenv("HW_REFERENCE_TOKENIZER", "pinned-tokenizer.json")
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path))
    gate = lib.compare_hardware_runs(
        str(artifact),
        str(artifact),
        str(profile),
        reference_tokenizer_path="pinned-tokenizer.json"
        if source == "explicit"
        else "",
    )
    assert gate["verdict"] == ("incomplete" if source == "missing" else "eligible")
    assert paths == ([""] if source == "missing" else ["pinned-tokenizer.json"])


@pytest.mark.parametrize("constrained", [False, True])
@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("injected", [False, True])
def test_json_constraint_metadata_matches_actual_request_payload(
    tmp_path, monkeypatch, constrained, wrapped, injected
):
    from rfc.openai_client import OpenAIClient
    from rfc.llm_client import _ConsoleFeedProvider

    monkeypatch.setenv("HW_EVAL_LIVE", "1")
    monkeypatch.setenv("RFC_RUN_MODE", "measure")
    monkeypatch.setenv("ANSWER_CACHE_ENABLED", "0")
    monkeypatch.setenv("HW_JSON_OBJECT_CONSTRAINT", "1" if constrained else "0")
    client = OpenAIClient(
        api_key="fixture",
        model="fixture",
        base_url="http://127.0.0.1",
        response_format="json",
        json_schema={"type": "string"},
    )
    factory = MagicMock(
        return_value=_ConsoleFeedProvider(client) if wrapped else client
    )
    monkeypatch.setattr("rfc.hardware_eval_keywords.create_provider", factory)
    case = load_benchmark(FIXTURES)["cases"]["uno-current-budget"]
    response = MagicMock()
    response.json.return_value = {
        "choices": [
            {
                "message": {"content": json.dumps(gold_answer(case))},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 100},
    }
    post = MagicMock(return_value=response)
    monkeypatch.setattr("rfc.openai_client.requests.post", post)
    lib = HardwareEvalKeywords(
        str(FIXTURES), str(tmp_path), client=factory.return_value if injected else None
    )
    row = lib.evaluate_hardware_case("uno-current-budget")
    if injected:
        factory.assert_not_called()
    else:
        assert factory.call_args.kwargs["response_format"] == (
            "json" if constrained else None
        )
    payload = post.call_args.kwargs["json"]
    if constrained:
        assert payload["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": {"type": "object"}},
        }
    else:
        assert "response_format" not in payload
        assert client.json_schema is None
    assert row["sampling"]["json_schema"] == (
        {"type": "object"} if constrained else None
    )
