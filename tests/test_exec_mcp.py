"""Hermetic tests for the rfc-exec MCP server + harness wiring (#235).

The JSON-RPC surface is a pure function of the request and an injected
BrokerDispatcher, so the protocol round-trips with no live Docker. The dispatcher
is exercised against a real ContainerExecBroker over a fake ``docker exec``
backend, so ``tools/call`` covers the full MCP-args -> SandboxToolCall -> broker
path. The config builders assert the exact deny-settings + mcp-config a harness
emits.
"""

from __future__ import annotations

import io
import json

from rfc.container_exec_broker import ContainerExecBroker
from rfc.exec_mcp import (
    CONTAINER_ID_ENV,
    METRICS_PATH_ENV,
    SERVER_NAME,
    BrokerDispatcher,
    SandboxExecRouting,
    claude_mcp_config,
    deny_settings,
    deny_settings_json,
    handle_message,
    mcp_tool_definitions,
    opencode_mcp_config,
    serve,
)


class FakeExecBackend:
    def __init__(self, results: list[dict] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[dict] = []

    def execute_command(self, container_id, command, timeout=30, workdir=None) -> dict:
        self.calls.append({"command": command, "workdir": workdir})
        if self.results:
            return self.results.pop(0)
        return {"stdout": "", "stderr": "", "exit_code": 0, "duration_ms": 1}


def _dispatcher(results: list[dict] | None = None) -> BrokerDispatcher:
    backend = FakeExecBackend(results)
    broker = ContainerExecBroker(backend, "cid-1")
    dispatcher = BrokerDispatcher(broker)
    dispatcher.backend = backend  # type: ignore[attr-defined]  # test handle
    return dispatcher


class TestProtocolSurface:
    def test_initialize_reports_server_name(self) -> None:
        resp = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert resp is not None
        assert resp["result"]["serverInfo"]["name"] == SERVER_NAME

    def test_tools_list_exposes_bash_write_edit(self) -> None:
        resp = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert resp is not None
        names = {t["name"] for t in resp["result"]["tools"]}
        assert names == {"bash", "write", "edit"}

    def test_tool_definitions_have_input_schema(self) -> None:
        for defn in mcp_tool_definitions():
            assert defn["inputSchema"]["type"] == "object"
            assert "required" in defn["inputSchema"]

    def test_initialized_notification_has_no_response(self) -> None:
        assert handle_message({"method": "notifications/initialized"}) is None

    def test_unknown_method_errors(self) -> None:
        resp = handle_message({"jsonrpc": "2.0", "id": 9, "method": "frobnicate"})
        assert resp is not None
        assert resp["error"]["code"] == -32601


class TestToolsCall:
    def test_bash_call_round_trips_through_broker(self) -> None:
        dispatcher = _dispatcher(
            [{"stdout": "hello\n", "stderr": "", "exit_code": 0, "duration_ms": 3}]
        )
        resp = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "bash", "arguments": {"command": "echo hello"}},
            },
            dispatcher,
        )
        assert resp is not None
        assert resp["result"]["isError"] is False
        assert resp["result"]["content"][0]["text"] == "hello\n"
        assert "echo hello" in dispatcher.backend.calls[0]["command"]  # type: ignore[attr-defined]

    def test_write_call_marshals_to_broker(self) -> None:
        dispatcher = _dispatcher([{"stdout": "", "exit_code": 0, "duration_ms": 1}])
        resp = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "write",
                    "arguments": {"path": "a.py", "content": "x=1\n"},
                },
            },
            dispatcher,
        )
        assert resp is not None
        assert resp["result"]["isError"] is False
        cmd = dispatcher.backend.calls[0]["command"]  # type: ignore[attr-defined]
        assert "/workspace/a.py" in cmd and "base64 -d" in cmd

    def test_nonzero_exit_sets_is_error(self) -> None:
        dispatcher = _dispatcher(
            [{"stdout": "nope", "stderr": "", "exit_code": 1, "duration_ms": 1}]
        )
        resp = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "bash", "arguments": {"command": "false"}},
            },
            dispatcher,
        )
        assert resp is not None
        assert resp["result"]["isError"] is True

    def test_missing_command_argument_is_error_not_crash(self) -> None:
        dispatcher = _dispatcher()
        resp = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "bash", "arguments": {}},
            },
            dispatcher,
        )
        assert resp is not None
        assert resp["result"]["isError"] is True

    def test_no_dispatcher_returns_clear_error_result(self) -> None:
        resp = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "bash", "arguments": {"command": "echo hi"}},
            },
            None,
        )
        assert resp is not None
        assert resp["result"]["isError"] is True
        assert CONTAINER_ID_ENV in resp["result"]["content"][0]["text"]


class TestServeLoop:
    def test_serve_answers_ndjson_requests(self) -> None:
        reader = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
        )
        writer = io.StringIO()
        serve(reader, writer, None)
        writer.seek(0)
        line = writer.read().strip()
        payload = json.loads(line)
        assert {t["name"] for t in payload["result"]["tools"]} == {
            "bash",
            "write",
            "edit",
        }


class TestHarnessWiring:
    def test_deny_settings_lists_the_native_code_tools(self) -> None:
        assert deny_settings() == {
            "permissions": {"deny": ["Bash", "Write", "Edit", "Read"]}
        }
        # round-trips as JSON for --settings
        assert json.loads(deny_settings_json()) == deny_settings()

    def test_claude_mcp_config_registers_stdio_server(self) -> None:
        routing = SandboxExecRouting(
            container_id="abc123", metrics_path="/tmp/o.jsonl", python_bin="python3"
        )
        cfg = claude_mcp_config(routing)
        server = cfg["mcpServers"][SERVER_NAME]
        assert server["type"] == "stdio"
        assert server["command"] == "python3"
        assert server["args"] == ["-m", "rfc.exec_mcp"]
        assert server["env"][CONTAINER_ID_ENV] == "abc123"
        assert server["env"][METRICS_PATH_ENV] == "/tmp/o.jsonl"

    def test_claude_mcp_config_omits_metrics_env_when_unset(self) -> None:
        routing = SandboxExecRouting(container_id="abc123")
        server = claude_mcp_config(routing)["mcpServers"][SERVER_NAME]
        assert METRICS_PATH_ENV not in server["env"]
        assert server["env"][CONTAINER_ID_ENV] == "abc123"

    def test_opencode_mcp_config_uses_local_type(self) -> None:
        routing = SandboxExecRouting(container_id="abc123", python_bin="python3")
        server = opencode_mcp_config(routing)["mcp"][SERVER_NAME]
        assert server["type"] == "local"
        assert server["command"] == ["python3", "-m", "rfc.exec_mcp"]
        assert server["environment"][CONTAINER_ID_ENV] == "abc123"
