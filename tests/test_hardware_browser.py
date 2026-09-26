"""Sandbox controls; scripted clients below test the harness, NOT model ability."""

from __future__ import annotations

from unittest.mock import MagicMock
import copy
import json
import os
import importlib

import pytest
import requests

from rfc.hardware_browser import HardwareSandbox, run_browser_agent
from rfc.hardware_eval import load_benchmark, document_text
from test_hardware_eval import FIXTURES, gold_answer


@pytest.fixture
def benchmark():
    return load_benchmark(FIXTURES)


@pytest.fixture
def browser():
    obj = MagicMock()
    obj.get_page_source.return_value = "<p>test page</p>"
    obj.get_text.return_value = ""
    obj.take_screenshot.return_value = "step.png"
    return obj


def test_server_only_exposes_public_documents_and_no_answers(
    benchmark, browser, tmp_path
):
    with HardwareSandbox(benchmark["documents"], browser, tmp_path) as box:
        page = requests.get(box.base_url + "/", timeout=2)
        assert page.status_code == 200
        assert "uno-spec" in page.text
        assert "Content-Security-Policy" in page.headers
        doc = requests.get(box.base_url + "/doc/fire-bom", timeout=2)
        assert "MPFS025T-FCVG484E" in doc.text
        assert "expected" not in doc.text
        assert (
            requests.get(box.base_url + "/answers.yaml", timeout=2).status_code == 404
        )
        assert requests.get(box.base_url + "/../.env", timeout=2).status_code == 404
        assert requests.post(box.base_url + "/report", timeout=2).status_code != 200


@pytest.mark.parametrize(
    "tool,args",
    [
        ("browser_new_page", {"url": "https://example.com"}),
        ("browser_new_page", {"url": "file:///etc/passwd"}),
        ("browser_new_page", {"url": "sandbox:/../.env"}),
        ("browser_new_page", {"url": "sandbox:/doc/unknown"}),
        ("browser_click", {"selector": "a[href^='https:']"}),
        ("browser_type_text", {"selector": "#other", "text": "secret"}),
        ("browser_screenshot", {"filename": "/tmp/escape"}),
        ("execute_shell", {"command": "id"}),
        ("browser_click", {"selector": []}),
    ],
)
def test_external_or_arbitrary_actions_blocked_before_dispatch(
    benchmark, browser, tmp_path, tool, args
):
    with HardwareSandbox(benchmark["documents"], browser, tmp_path) as box:
        result = box.dispatch(tool, args)
        assert not result["success"]
        assert box.unsafe_actions == 1
        browser.new_page.assert_not_called()
        browser.click.assert_not_called()
        browser.type_text.assert_not_called()


def test_model_must_read_document_not_just_open_it(
    benchmark, browser, tmp_path, monkeypatch
):
    # This tests observation tracking, not optional HTML conversion. The real
    # Chromium smoke below exercises markdownify with the playwright extra.
    monkeypatch.setattr(
        "rfc.computer_use_keywords._default_markdown_converter", lambda text: text
    )
    with HardwareSandbox(benchmark["documents"], browser, tmp_path) as box:
        assert box.dispatch("browser_new_page", {"url": "sandbox:/doc/uno-spec"})[
            "success"
        ]
        assert not box.observed
        browser.get_page_source.return_value = (
            "<pre>" + document_text(benchmark["documents"]["uno-spec"]) + "</pre>"
        )
        assert box.dispatch("browser_read_markdown", {})["success"]
        assert box.observed == {"uno-spec"}


def test_fixture_injection_is_escaped_html(benchmark, browser, tmp_path):
    docs = {**benchmark["documents"]}
    docs["injection-note"] = {
        **docs["injection-note"],
        "text": "<script>fetch('/secret')</script>",
    }
    with HardwareSandbox(docs, browser, tmp_path) as box:
        text = requests.get(box.base_url + "/doc/injection-note", timeout=2).text
        assert "<script>fetch" not in text
        assert "&lt;script&gt;" in text


def test_browser_final_answer_without_actions_cannot_pass(benchmark, browser, tmp_path):
    case = benchmark["cases"]["uno-current-budget"]
    with HardwareSandbox(benchmark["documents"], browser, tmp_path) as box:
        result = run_browser_agent(
            case,
            box,
            lambda prompt: json.dumps({"final": gold_answer(case)}),
            max_actions=5,
        )
        assert not result["passed"]
        assert not result["sources_observed"]
        assert not result["report_saved"]


@pytest.mark.parametrize("replace_boolean", [False, True])
def test_saved_report_preserves_json_value_types(
    benchmark, browser, tmp_path, monkeypatch, replace_boolean
):
    case = benchmark["cases"]["uno-current-budget"]
    answer = gold_answer(case)
    saved = copy.deepcopy(answer)
    if replace_boolean:
        item = next(item for item in saved["answers"] if type(item["value"]) is bool)
        item["value"] = int(item["value"])
    with HardwareSandbox(benchmark["documents"], browser, tmp_path) as box:
        box.observed = set().union(
            *(rule["evidence"] for rule in case["expected"].values())
        )
        monkeypatch.setattr(box, "saved_report", lambda: saved)
        result = run_browser_agent(
            case, box, lambda prompt: json.dumps({"final": answer})
        )
    assert result["accuracy"] == 1.0
    assert result["report_saved"] is not replace_boolean
    assert result["passed"] is not replace_boolean


def test_budget_exhaustion_is_not_completion(benchmark, browser, tmp_path):
    case = benchmark["cases"]["uno-current-budget"]
    with HardwareSandbox(benchmark["documents"], browser, tmp_path) as box:
        result = run_browser_agent(
            case,
            box,
            lambda prompt: '{"tool":"browser_read_markdown","arguments":{}}',
            max_actions=2,
        )
        assert not result["passed"]
        assert result["agent_status"] == "action_budget_exhausted"
        assert len(result["trace"]) == 2


def test_broken_json_is_model_failure_not_skip(benchmark, browser, tmp_path):
    with HardwareSandbox(benchmark["documents"], browser, tmp_path) as box:
        result = run_browser_agent(
            benchmark["cases"]["uno-current-budget"], box, lambda prompt: "not JSON"
        )
        assert not result["passed"]
        assert result["agent_status"] == "invalid_action"


@pytest.mark.skipif(
    os.getenv("HW_BROWSER_SMOKE") != "1", reason="opt-in actual Chromium harness smoke"
)
def test_real_browser_saves_report_with_scripted_instrument_control(
    benchmark, tmp_path
):
    """Real browser with a SCRIPTED oracle, not evidence of LLM competence."""
    browser = importlib.import_module("Browser").Browser()
    browser.new_browser("chromium", headless=True)
    browser.new_context(acceptDownloads=False)
    case = benchmark["cases"]["uno-current-budget"]
    answer = gold_answer(case)
    actions = [
        {"tool": "browser_new_page", "arguments": {"url": "sandbox:/"}},
        {"tool": "browser_read_markdown", "arguments": {}},
        {"tool": "browser_click", "arguments": {"selector": "#doc-uno-power"}},
        {"tool": "browser_read_markdown", "arguments": {}},
        {"tool": "browser_click", "arguments": {"selector": "#home"}},
        {"tool": "browser_click", "arguments": {"selector": "#doc-sensor-loads"}},
        {"tool": "browser_read_markdown", "arguments": {}},
        {"tool": "browser_click", "arguments": {"selector": "#report"}},
        {
            "tool": "browser_type_text",
            "arguments": {"selector": "#report-text", "text": json.dumps(answer)},
        },
        {"tool": "browser_click", "arguments": {"selector": "#save"}},
        {"final": answer},
    ]
    stream = iter(actions)
    try:
        with HardwareSandbox(benchmark["documents"], browser, tmp_path) as box:
            result = run_browser_agent(
                case, box, lambda prompt: json.dumps(next(stream))
            )
            assert result["passed"], result
            assert result["sources_observed"]
            assert result["report_saved"]
            assert result["action_count"] == 10
            from rfc.hardware_eval import browser_workflow_matches

            result["browser_trace"] = result["trace"]
            assert browser_workflow_matches(result, case, benchmark["documents"])
            assert list(tmp_path.glob("*.png"))
    finally:
        browser.close_browser()


@pytest.mark.parametrize("tool", ["browser_read_markdown", "browser_screenshot"])
@pytest.mark.parametrize("arguments", [None, False, 0, "", []])
def test_falsey_nonobject_tool_arguments_are_rejected_as_model_actions(
    benchmark, browser, tmp_path, monkeypatch, tool, arguments
):
    with HardwareSandbox(benchmark["documents"], browser, tmp_path) as box:
        monkeypatch.setattr(
            box.dispatcher, "dispatch", lambda call: pytest.fail("Invalid dispatch")
        )
        assert box._allowed(tool, {})
        result = run_browser_agent(
            benchmark["cases"]["uno-current-budget"],
            box,
            lambda prompt: json.dumps({"tool": tool, "arguments": arguments}),
        )
        assert result["agent_status"] == "unsafe_action"
        assert result["unsafe_actions"] == 1
        assert result["action_count"] == 1
        assert result["passed"] is False
        assert result["trace"][0]["observation"]["error"] == "action_not_allowlisted"


def test_actual_agent_prompts_reconstruct_from_archived_trace(
    benchmark, browser, tmp_path
):
    from rfc.hardware_eval import browser_calls_bound, browser_task_prompt, digest

    case = benchmark["cases"]["uno-current-budget"]
    outputs = iter(
        [
            {"tool": "browser_new_page", "arguments": {"url": "sandbox:/"}},
            {"final": gold_answer(case)},
        ]
    )
    calls = []

    def generate(prompt):
        calls.append({"prompt_sha256": digest(prompt)})
        return json.dumps(next(outputs))

    with HardwareSandbox(benchmark["documents"], browser, tmp_path) as box:
        result = run_browser_agent(case, box, generate)
    row = {
        "prompt_sha256": digest(browser_task_prompt(case)),
        "calls": calls,
        "browser_trace": result["trace"],
        "agent_status": result["agent_status"],
        "passed": result["passed"],
    }
    assert browser_calls_bound(json.loads(json.dumps(row, sort_keys=True)), case)
    # A final-only response has one call and an empty action trace; this
    # establishes prompt accounting, not successful evidence collection.
    row["calls"] = calls[:1]
    row["browser_trace"] = []
    assert browser_calls_bound(row, case)


def test_live_agent_workflow_matches_offline_trace_replay(
    benchmark, browser, tmp_path, monkeypatch
):
    from rfc.hardware_eval import browser_workflow_matches

    case = benchmark["cases"]["uno-current-budget"]
    answer = gold_answer(case)
    required = sorted(set().union(*(r["evidence"] for r in case["expected"].values())))
    pages = iter("[DOCUMENT " + doc_id + "]" for doc_id in required)
    browser.get_text.return_value = json.dumps(answer)
    actions = []
    for doc_id in required:
        actions += [
            {
                "tool": "browser_new_page",
                "arguments": {"url": "sandbox:/doc/" + doc_id},
            },
            {"tool": "browser_read_markdown", "arguments": {}},
        ]
    actions += [
        {"tool": "browser_new_page", "arguments": {"url": "sandbox:/report"}},
        {
            "tool": "browser_type_text",
            "arguments": {"selector": "#report-text", "text": json.dumps(answer)},
        },
        {"tool": "browser_click", "arguments": {"selector": "#save"}},
        {"final": answer},
    ]
    stream = iter(actions)
    with HardwareSandbox(benchmark["documents"], browser, tmp_path) as box:
        monkeypatch.setattr(box.dispatcher, "_to_markdown", lambda html: next(pages))
        result = run_browser_agent(case, box, lambda prompt: json.dumps(next(stream)))
    assert result["passed"]
    result["browser_trace"] = result["trace"]
    assert browser_workflow_matches(result, case, benchmark["documents"])
    result["answer"]["answers"][0]["value"] = "different final answer"
    assert not browser_workflow_matches(result, case, benchmark["documents"])


@pytest.mark.parametrize(
    "ending,expected_status",
    [
        ("not json", "invalid_action"),
        ('{"unexpected": true}', "invalid_action"),
        ('{"tool": "execute_shell", "arguments": {}}', "unsafe_action"),
        (
            '{"tool": "browser_read_markdown", "arguments": {}}',
            "action_budget_exhausted",
        ),
    ],
)
def test_failed_live_workflows_remain_consistent_evidence(
    benchmark, browser, tmp_path, monkeypatch, ending, expected_status
):
    from rfc.hardware_eval import browser_workflow_matches

    case = benchmark["cases"]["uno-current-budget"]
    stream = iter(
        ['{"tool": "browser_new_page", "arguments": {"url": "sandbox:/"}}', ending]
    )
    with HardwareSandbox(benchmark["documents"], browser, tmp_path) as box:
        monkeypatch.setattr(box.dispatcher, "_to_markdown", lambda html: "catalog")
        result = run_browser_agent(
            case, box, lambda prompt: next(stream), max_actions=2
        )
    assert result["agent_status"] == expected_status
    assert not result["passed"]
    result["browser_trace"] = result["trace"]
    assert browser_workflow_matches(result, case, benchmark["documents"])
