"""PR 714 review reproducers; no live inference."""

import copy
import json
from unittest.mock import Mock

import pytest

from rfc.hardware_eval import score_answer
from rfc.hardware_eval_keywords import HardwareEvalKeywords
from rfc.llm_client import _ConsoleFeedProvider
from test_hardware_eval import (
    FIXTURES,
    compare_runs,
    gold_answer,
    load_benchmark,
    row,
    synthetic_benchmark,
)


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
        "one": {"correct": True, "citation_correct": True, "critical": False},
        "two": {"correct": False, "citation_correct": True, "critical": False},
    }
    old = row(weights_format="UD-Q4_K_M", checks=checks, accuracy=0.5)
    new = copy.deepcopy(old)
    new["checks"]["one"]["correct"] = False
    new["checks"]["two"]["correct"] = True
    assert (
        compare_runs([old], [new], synthetic_benchmark({"one": False, "two": False}))[
            "verdict"
        ]
        == "blocked"
    )


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


@pytest.mark.parametrize(
    "sampling",
    [
        {},
        {"temperature": 0, "seed": 1, "max_tokens": 2048},
        {"temperature": "0", "seed": 0, "max_tokens": 2048},
        {"temperature": 0, "seed": 0, "max_tokens": 0},
        {"temperature": float("inf"), "seed": 0, "max_tokens": 2048},
    ],
)
def test_sampling_attestation_is_complete_and_matches_trial(sampling):
    old = row(sampling=sampling)
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


@pytest.mark.parametrize("field", ["accuracy", "citation_accuracy"])
def test_aggregate_scores_cannot_contradict_question_checks(field):
    old = row()
    new = copy.deepcopy(old)
    new[field] = 0.25 if field == "citation_accuracy" else 1.0
    assert compare_runs([old], [new])["verdict"] == "incomplete"


@pytest.mark.parametrize("adapter", [None, "", " "])
def test_adapter_identity_must_be_explicit(adapter):
    old = row(adapter_id=adapter)
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


def test_explicit_schema_reaches_wrapped_chat_transport(tmp_path, monkeypatch):
    from rfc.openai_client import OpenAIClient

    monkeypatch.setenv("HW_JSON_OBJECT_CONSTRAINT", "1")
    client = OpenAIClient(api_key="test", model="test", base_url="http://127.0.0.1")
    monkeypatch.setattr(client, "generate", lambda prompt: '{"answers":[]}')
    lib = HardwareEvalKeywords(
        str(FIXTURES), str(tmp_path), client=_ConsoleFeedProvider(client)
    )
    result = lib.evaluate_hardware_case("uno-current-budget")
    assert client.json_schema == {"type": "object"}
    assert client.response_format == "json"
    assert result["sampling"]["json_schema"] == {"type": "object"}


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


@pytest.mark.parametrize("field", ["sources_observed", "report_saved"])
def test_browser_workflow_regression_blocks_even_with_equal_answers(field):
    old = row(
        case_id="task:browser",
        accuracy=1.0,
        passed=True,
        sources_observed=True,
        report_saved=True,
    )
    new = copy.deepcopy(old)
    new[field] = False
    new["passed"] = False
    from rfc.hardware_eval import compare_runs as compare_paired

    assert (
        compare_paired(
            [old], [new], {("task:browser", 16384, "middle", 0)}, synthetic_benchmark()
        )["verdict"]
        == "blocked"
    )


def test_critical_count_cannot_contradict_question_checks():
    old = row()
    old["checks"]["q3"]["critical"] = True
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


@pytest.mark.parametrize("critical", [None, 1, "false"])
def test_critical_attestation_must_be_boolean(critical):
    old = row()
    old["checks"]["q0"]["critical"] = critical
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


@pytest.mark.parametrize(
    "field", ["prompt_sha256", "fixture_sha256", "harness_version", "grader_version"]
)
@pytest.mark.parametrize("value", ["", " ", None])
def test_required_provenance_cannot_be_empty(field, value):
    old = row(**{field: value})
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


def test_harness_identity_includes_transitive_module_names_and_contents(tmp_path):
    from rfc.hardware_eval_keywords import harness_digest

    module = tmp_path / "openai_client.py"
    module.write_text("first")
    initial = harness_digest(tmp_path)
    module.write_text("second")
    changed = harness_digest(tmp_path)
    assert changed != initial
    module.rename(tmp_path / "thinking.py")
    assert harness_digest(tmp_path) != changed


@pytest.mark.parametrize("field", ["reference_tokenizer", "model_tokenizer"])
@pytest.mark.parametrize("identity", [None, "", "not-a-hash"])
def test_tokenizer_identities_are_required_for_long_context(field, identity):
    old = row(**{field: identity})
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


def test_model_tokenizer_must_be_stable_within_each_arm():
    from rfc.hardware_eval import compare_runs as compare_paired

    rows = [row(trial=0), row(trial=1, model_tokenizer="f" * 64)]
    required = {("a", 16384, "middle", trial) for trial in [0, 1]}
    assert (
        compare_paired(rows, copy.deepcopy(rows), required, synthetic_benchmark())[
            "verdict"
        ]
        == "incomplete"
    )


def test_distinct_models_may_use_distinct_tokenizers():
    assert (
        compare_runs([row()], [row(model_tokenizer="f" * 64)])["verdict"] == "eligible"
    )


def test_browser_workflow_failure_blocks_even_when_baseline_also_failed():
    from rfc.hardware_eval import compare_runs as compare_paired

    old = row(
        case_id="a:browser",
        accuracy=1.0,
        passed=False,
        sources_observed=True,
        report_saved=False,
    )
    assert (
        compare_paired(
            [old],
            [copy.deepcopy(old)],
            {("a:browser", 16384, "middle", 0)},
            synthetic_benchmark(),
        )["verdict"]
        == "blocked"
    )


def test_browser_row_keeps_question_failures_separate_from_workflow(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    import rfc.hardware_eval_keywords as keywords

    case = load_benchmark(FIXTURES)["cases"]["uno-current-budget"]
    grade = score_answer(case, gold_answer(case))
    assert grade["critical_failures"] == 0
    original_import = keywords.importlib.import_module
    monkeypatch.setattr(
        keywords.importlib,
        "import_module",
        lambda name: SimpleNamespace(Browser=MagicMock)
        if name == "Browser"
        else original_import(name),
    )
    monkeypatch.setattr(keywords, "HardwareSandbox", MagicMock())
    monkeypatch.setattr(
        keywords,
        "run_browser_agent",
        lambda *args: {
            **grade,
            "passed": False,
            "sources_observed": True,
            "report_saved": False,
            "unsafe_actions": 0,
            "trace": [],
        },
    )
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path), client=Mock(model="test"))
    result = lib.evaluate_hardware_browser_task("uno-current-budget")
    assert result["passed"] is False
    assert result["report_saved"] is False
    assert result["critical_failures"] == 0


@pytest.mark.parametrize(
    "field", ["fixture_sha256", "grader_version", "harness_version"]
)
def test_combined_profile_rejects_mixed_benchmark_revisions(field):
    from rfc.hardware_eval import compare_runs as compare_paired

    rows = [row(trial=0), row(trial=1, **{field: "f" * 64})]
    required = {("a", 16384, "middle", trial) for trial in [0, 1]}
    assert (
        compare_paired(rows, copy.deepcopy(rows), required, synthetic_benchmark())[
            "verdict"
        ]
        == "incomplete"
    )


@pytest.mark.parametrize("identity", [None, "", " \t", 0, 123])
def test_blank_or_nonstring_model_digest_cannot_pass(identity):
    old = row(model_digest=identity)
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


@pytest.mark.parametrize(
    "field", ["model", "model_digest", "adapter_id", "weights_format"]
)
@pytest.mark.parametrize("value", [None, "", " \t", True, 7, [1], {"id": "untyped"}])
def test_model_provenance_fields_require_nonblank_strings(field, value):
    old = row(**{field: value})
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


@pytest.mark.parametrize("field", ["engine", "version", "rope", "kv_cache_dtype"])
@pytest.mark.parametrize("value", [None, "", " \t", True, 7, [1], {"id": "untyped"}])
def test_runtime_provenance_fields_require_nonblank_strings(field, value):
    old = row()
    old["runtime_manifest"][field] = value
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


def test_unknown_weight_format_marker_cannot_hide_in_whitespace():
    old = row(weights_format=" Unspecified ")
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


def test_context_coordinate_cannot_exceed_declared_allocation():
    old = row(context_tokens=16384, effective_context_tokens=4096)
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


@pytest.mark.parametrize("accuracy", [0.75, 1.0])
def test_candidate_cannot_reclassify_critical_questions(accuracy):
    old = row(accuracy=accuracy)
    old["checks"]["q3"]["critical"] = True
    old["critical_failures"] = int(accuracy < 1)
    new = copy.deepcopy(old)
    new["checks"]["q3"]["critical"] = False
    new["critical_failures"] = 0
    result = compare_runs([old], [new])
    assert result["verdict"] == "incomplete"
    assert "question_criticality_changed" in result["reasons"]


@pytest.mark.parametrize("browser", [False, True])
@pytest.mark.parametrize("corruption", ["omit", "add", "demote", "fixture_hash"])
def test_both_artifacts_must_match_trusted_benchmark(tmp_path, browser, corruption):
    benchmark = load_benchmark(FIXTURES)
    case_id = "uno-current-budget"
    case = benchmark["cases"][case_id]
    result = row(
        case_id=case_id + (":browser" if browser else ""),
        fixture_sha256=benchmark["sha256"],
        sources_observed=True,
        report_saved=True,
        **score_answer(case, gold_answer(case)),
    )
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        json.dumps(
            {
                "groups": [
                    {
                        "mode": "browser" if browser else "text",
                        "cases": [case_id],
                        "contexts": [16384],
                        "positions": ["middle"],
                        "trials": [0],
                    }
                ]
            }
        )
    )
    artifact = tmp_path / "artifact.jsonl"
    lib = HardwareEvalKeywords(str(FIXTURES), str(tmp_path), client=Mock())
    artifact.write_text(json.dumps(result) + "\n")
    assert (
        lib.compare_hardware_runs(str(artifact), str(artifact), str(profile))["verdict"]
        == "eligible"
    )

    critical = next(q for q, check in result["checks"].items() if check["critical"])
    if corruption == "omit":
        del result["checks"][critical]
    elif corruption == "add":
        result["checks"]["invented"] = {
            "correct": True,
            "citation_correct": True,
            "critical": False,
        }
    elif corruption == "demote":
        result["checks"][critical]["critical"] = False
    else:
        result["fixture_sha256"] = "f" * 64
    # Both artifacts retain mutually consistent perfect aggregate scores.
    artifact.write_text(json.dumps(result) + "\n")
    gate = lib.compare_hardware_runs(str(artifact), str(artifact), str(profile))
    assert gate["verdict"] == "incomplete"
    assert "benchmark_question_schema_mismatch" in gate["reasons"]


def test_core_gate_requires_benchmark_independent_of_artifacts():
    from rfc.hardware_eval import compare_runs as compare_paired

    result = compare_paired([row()], [row()], {("a", 16384, "middle", 0)})
    assert result["reasons"] == ["missing_trusted_benchmark"]


@pytest.mark.parametrize(
    "accuracy,passed", [(0.75, True), (1.0, False), (1.0, 1), (1.0, None)]
)
def test_full_pass_attestation_must_match_question_checks(accuracy, passed):
    old = row(accuracy=accuracy, passed=passed)
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


@pytest.mark.parametrize("schema", [None, 0, 1, "true"])
def test_schema_attestation_requires_boolean(schema):
    old = row(schema_valid=schema)
    assert compare_runs([old], [copy.deepcopy(old)])["verdict"] == "incomplete"


def test_browser_full_pass_cannot_ignore_failed_workflow():
    from rfc.hardware_eval import compare_runs as compare_paired

    old = row(
        case_id="a:browser",
        accuracy=1.0,
        passed=True,
        sources_observed=True,
        report_saved=False,
    )
    result = compare_paired(
        [old],
        [copy.deepcopy(old)],
        {("a:browser", 16384, "middle", 0)},
        synthetic_benchmark(),
    )
    assert result["verdict"] == "incomplete"


def test_robot_product_gate_uses_configured_fixture_root(tmp_path, monkeypatch):
    import io
    import yaml
    from robot import run

    fixtures = FIXTURES / "product"
    benchmark = load_benchmark(fixtures)
    profile = yaml.safe_load((fixtures / "gate_profile.yaml").read_text())
    rows = [
        row(
            case_id=case_id,
            context_tokens=context,
            position=position,
            trial=trial,
            fixture_sha256=benchmark["sha256"],
            **score_answer(
                benchmark["cases"][case_id], gold_answer(benchmark["cases"][case_id])
            ),
        )
        for group in profile["groups"]
        for case_id in group["cases"]
        for context in group["contexts"]
        for position in group["positions"]
        for trial in group["trials"]
    ]
    artifact = tmp_path / "synthetic-product.jsonl"
    artifact.write_text("".join(json.dumps(item) + "\n" for item in rows))
    monkeypatch.setenv("HW_BASELINE_RESULTS", str(artifact))
    monkeypatch.setenv("HW_CANDIDATE_RESULTS", str(artifact))
    monkeypatch.setenv("HW_GATE_PROFILE", str(fixtures / "gate_profile.yaml"))
    monkeypatch.setenv("HW_GATE_FIXTURES", str(fixtures))
    stream = io.StringIO()
    result = run(
        str(FIXTURES.parent / "evaluation_gate.robot"),
        outputdir=str(tmp_path / "gate"),
        stdout=stream,
        stderr=stream,
    )
    assert result == 0, stream.getvalue()
    gate = json.loads((tmp_path / "gate/hardware-gate.json").read_text())
    assert gate["verdict"] == "eligible"
    assert gate["paired_cases"] == 12
