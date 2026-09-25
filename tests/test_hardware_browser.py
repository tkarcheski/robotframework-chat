"""Sandbox controls; scripted clients below test the harness, NOT model ability."""

from __future__ import annotations

from unittest.mock import MagicMock
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


def test_model_must_read_document_not_just_open_it(benchmark, browser, tmp_path):
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
            assert list(tmp_path.glob("*.png"))
    finally:
        browser.close_browser()
