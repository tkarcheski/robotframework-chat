"""Live/offline boundaries and result persistence for the hardware keywords."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from rfc.exceptions import RFCSkipError
from rfc.hardware_eval import load_benchmark
from rfc.hardware_eval_keywords import HardwareEvalKeywords, verify_token_usage
from test_hardware_eval import FIXTURES, gold_answer


def test_tokens_must_be_measured_and_not_silently_truncated():
    assert verify_token_usage(
        100, {"prompt_eval_count": 110, "eval_count": 10}, 256, 32
    )
    assert not verify_token_usage(100, {}, 256, 32)
    assert not verify_token_usage(None, {"prompt_eval_count": 110}, 256, 32)
    assert not verify_token_usage(100, {"prompt_eval_count": 80}, 256, 32)
    assert not verify_token_usage(
        100, {"prompt_eval_count": 240, "eval_count": 20}, 256, 32
    )
    assert not verify_token_usage(
        100, {"prompt_eval_count": 110, "eval_count": 32}, 256, 32
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
    assert not result["live"]
    assert not result["token_count_verified"]
    assert (tmp_path / "hardware-results.jsonl").exists()
    assert (tmp_path / result["artifact"] / "response.txt").exists()


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
