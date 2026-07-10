"""MCP (Model Context Protocol) server for the computer-use browser tools.

Exposes the same browser-action tools as ``computer_use_keywords`` over the MCP
stdio transport so external harnesses can call them. The transport is
newline-delimited JSON-RPC 2.0 on stdin/stdout -- exactly what an MCP stdio
server speaks -- implemented here without the ``mcp`` SDK so the module imports
and unit-tests with zero extra dependencies and no live browser.

Message handling (``handle_message``) is a pure function of the request and an
injected dispatcher, so the full protocol surface (initialize / tools/list /
tools/call / notifications) is hermetically testable. The ``serve`` loop wires
those to real streams; ``main`` additionally boots a real Browser instance,
which is the only part that needs the ``playwright`` extra + ``rfbrowser init``.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional, TextIO

from .agent_tool import ToolSchema, new_tool_call
from .computer_use_keywords import (
    ComputerUseDispatcher,
    computer_use_tool_schemas,
)

SERVER_NAME = "rfc-computer-use"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"

# JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def tool_schema_to_mcp(schema: ToolSchema) -> Dict[str, Any]:
    """Convert a ToolSchema to an MCP tool definition (with ``inputSchema``)."""
    return {
        "name": schema.name,
        "description": schema.description,
        "inputSchema": {
            "type": "object",
            "properties": schema.parameters,
            "required": list(schema.required),
        },
    }


def mcp_tool_definitions() -> List[Dict[str, Any]]:
    """The computer-use tools as MCP tool definitions."""
    return [tool_schema_to_mcp(s) for s in computer_use_tool_schemas()]


def _result(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _handle_initialize(request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    protocol_version = params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION
    return _result(
        request_id,
        {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        },
    )


def _handle_tools_call(
    request_id: Any,
    params: Dict[str, Any],
    dispatcher: Optional[ComputerUseDispatcher],
) -> Dict[str, Any]:
    name = params.get("name")
    if not isinstance(name, str) or not name:
        return _error(request_id, INVALID_PARAMS, "tools/call requires a 'name'")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _error(request_id, INVALID_PARAMS, "'arguments' must be an object")

    if dispatcher is None:
        # Protocol is alive but no browser is wired (e.g. playwright absent).
        return _result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "No browser is available to execute tool calls. "
                            "Install the playwright extra and run 'rfbrowser init'."
                        ),
                    }
                ],
                "isError": True,
            },
        )

    call = new_tool_call(name, arguments)
    tool_result = dispatcher.dispatch(call)
    text = tool_result.output if tool_result.success else (tool_result.error or "")
    return _result(
        request_id,
        {
            "content": [{"type": "text", "text": text}],
            "isError": not tool_result.success,
        },
    )


def handle_message(
    message: Dict[str, Any],
    dispatcher: Optional[ComputerUseDispatcher] = None,
) -> Optional[Dict[str, Any]]:
    """Handle one JSON-RPC message; return a response, or None for notifications.

    ``dispatcher`` executes ``tools/call``; when it is None the protocol still
    works and tool calls come back as an MCP error result rather than crashing.
    """
    request_id = message.get("id")
    method = message.get("method")

    # Notifications (no id) never get a response.
    is_notification = "id" not in message
    if method is None:
        if is_notification:
            return None
        return _error(request_id, INVALID_REQUEST, "missing 'method'")

    params = message.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    if method == "initialize":
        return _handle_initialize(request_id, params)
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": mcp_tool_definitions()})
    if method == "tools/call":
        return _handle_tools_call(request_id, params, dispatcher)

    if is_notification:
        return None
    return _error(request_id, METHOD_NOT_FOUND, f"Unknown method: {method}")


def serve(
    reader: TextIO,
    writer: TextIO,
    dispatcher: Optional[ComputerUseDispatcher] = None,
) -> None:
    """Run the newline-delimited JSON-RPC stdio loop until EOF."""
    for line in reader:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _write(writer, _error(None, PARSE_ERROR, "invalid JSON"))
            continue
        if not isinstance(message, dict):
            _write(writer, _error(None, INVALID_REQUEST, "message must be an object"))
            continue
        response = handle_message(message, dispatcher)
        if response is not None:
            _write(writer, response)


def _write(writer: TextIO, payload: Dict[str, Any]) -> None:
    writer.write(json.dumps(payload) + "\n")
    writer.flush()


def _build_browser() -> Any:  # pragma: no cover - requires playwright + rfbrowser
    """Boot a headless Browser instance for the standalone server.

    Only exercised by ``main``; needs the ``playwright`` extra and
    ``rfbrowser init``. Kept out of unit tests (no live browser in CI).
    """
    from Browser import Browser  # type: ignore[import-not-found]

    browser = Browser()
    browser.new_browser(headless=True)
    browser.new_context()
    return browser


def main() -> None:  # pragma: no cover - process entrypoint
    """Entrypoint: ``python -m rfc.computer_use_mcp``.

    Boots a real browser if available; otherwise serves the protocol so
    ``tools/list`` still works and ``tools/call`` returns a clear MCP error.
    """
    dispatcher: Optional[ComputerUseDispatcher]
    try:
        dispatcher = ComputerUseDispatcher(_build_browser())
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[{SERVER_NAME}] browser unavailable: {exc}\n")
        dispatcher = None
    serve(sys.stdin, sys.stdout, dispatcher)


if __name__ == "__main__":  # pragma: no cover
    main()
