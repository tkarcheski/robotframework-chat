"""Tests for rfc.computer_use_mcp: MCP stdio exposure of the browser tools."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock

from rfc.agent_tool import new_tool_call
from rfc.computer_use_keywords import ComputerUseDispatcher
from rfc.computer_use_mcp import (
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SERVER_NAME,
    handle_message,
    mcp_tool_definitions,
    serve,
    tool_schema_to_mcp,
)

EXPECTED_TOOLS = {
    "browser_new_page",
    "browser_click",
    "browser_type_text",
    "browser_read_markdown",
    "browser_screenshot",
}


def _fake_dispatcher() -> ComputerUseDispatcher:
    browser = MagicMock()
    browser.get_page_source.return_value = "<h1>Page</h1>"
    return ComputerUseDispatcher(browser, markdown_converter=lambda h: f"MD::{h}")


class TestToolDefinitions:
    def test_mcp_tool_definitions_have_input_schema(self) -> None:
        defs = mcp_tool_definitions()
        assert {d["name"] for d in defs} == EXPECTED_TOOLS
        for d in defs:
            assert d["inputSchema"]["type"] == "object"
            assert "properties" in d["inputSchema"]
            assert "required" in d["inputSchema"]

    def test_tool_schema_to_mcp_shape(self) -> None:
        from rfc.computer_use_keywords import computer_use_tool_schemas

        schema = next(
            s for s in computer_use_tool_schemas() if s.name == "browser_new_page"
        )
        mcp = tool_schema_to_mcp(schema)
        assert mcp["name"] == "browser_new_page"
        assert mcp["inputSchema"]["required"] == ["url"]
        assert "url" in mcp["inputSchema"]["properties"]


class TestInitialize:
    def test_initialize_returns_server_info(self) -> None:
        resp = handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        assert resp is not None
        assert resp["id"] == 1
        assert resp["result"]["serverInfo"]["name"] == SERVER_NAME
        assert "tools" in resp["result"]["capabilities"]

    def test_initialize_echoes_protocol_version(self) -> None:
        resp = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        assert resp["result"]["protocolVersion"] == "2025-06-18"


class TestToolsList:
    def test_tools_list_returns_all_tools(self) -> None:
        resp = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        assert names == EXPECTED_TOOLS


class TestToolsCall:
    def test_tools_call_dispatches_to_browser(self) -> None:
        resp = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "browser_click", "arguments": {"selector": "#go"}},
            },
            dispatcher=_fake_dispatcher(),
        )
        assert resp["result"]["isError"] is False
        assert "Clicked" in resp["result"]["content"][0]["text"]

    def test_tools_call_read_markdown_returns_converted_text(self) -> None:
        resp = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "browser_read_markdown", "arguments": {}},
            },
            dispatcher=_fake_dispatcher(),
        )
        assert resp["result"]["content"][0]["text"] == "MD::<h1>Page</h1>"

    def test_tools_call_unknown_tool_is_error(self) -> None:
        resp = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "browser_fly", "arguments": {}},
            },
            dispatcher=_fake_dispatcher(),
        )
        assert resp["result"]["isError"] is True

    def test_tools_call_without_dispatcher_returns_error_result(self) -> None:
        resp = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "browser_click", "arguments": {"selector": "#g"}},
            },
            dispatcher=None,
        )
        assert resp["result"]["isError"] is True
        assert "playwright" in resp["result"]["content"][0]["text"]

    def test_tools_call_missing_name_is_invalid_params(self) -> None:
        resp = handle_message(
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {}},
            dispatcher=_fake_dispatcher(),
        )
        assert "error" in resp


class TestNotificationsAndErrors:
    def test_initialized_notification_gets_no_response(self) -> None:
        assert (
            handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
            is None
        )

    def test_ping_returns_empty_result(self) -> None:
        resp = handle_message({"jsonrpc": "2.0", "id": 8, "method": "ping"})
        assert resp["result"] == {}

    def test_unknown_method_returns_method_not_found(self) -> None:
        resp = handle_message({"jsonrpc": "2.0", "id": 9, "method": "does/not/exist"})
        assert resp["error"]["code"] == METHOD_NOT_FOUND

    def test_unknown_notification_gets_no_response(self) -> None:
        assert handle_message({"jsonrpc": "2.0", "method": "does/not/exist"}) is None


class TestServeLoop:
    def test_serve_processes_stream_and_writes_responses(self) -> None:
        requests = "\n".join(
            [
                json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
                ),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "browser_new_page",
                            "arguments": {"url": "data:text/html,<h1>x</h1>"},
                        },
                    }
                ),
            ]
        )
        reader = io.StringIO(requests + "\n")
        writer = io.StringIO()
        serve(reader, writer, dispatcher=_fake_dispatcher())
        out_lines = [line for line in writer.getvalue().splitlines() if line.strip()]
        # 3 responses: initialize, tools/list, tools/call (notification suppressed).
        assert len(out_lines) == 3
        parsed = [json.loads(x) for x in out_lines]
        assert parsed[0]["id"] == 1
        assert parsed[1]["id"] == 2
        assert parsed[2]["id"] == 3
        assert parsed[2]["result"]["isError"] is False

    def test_serve_reports_parse_error_on_bad_json(self) -> None:
        reader = io.StringIO("not json\n")
        writer = io.StringIO()
        serve(reader, writer, dispatcher=_fake_dispatcher())
        parsed = json.loads(writer.getvalue().strip())
        assert parsed["error"]["code"] == PARSE_ERROR

    def test_serve_reuses_agent_tool_call_ids(self) -> None:
        # new_tool_call produces distinct ids so trace entries never collide.
        a = new_tool_call("browser_click", {"selector": "#a"})
        b = new_tool_call("browser_click", {"selector": "#a"})
        assert a.id != b.id
