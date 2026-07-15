"""MCP (Model Context Protocol) server ``rfc-exec``: code execution routed into
the sandbox container (#235).

Exposes ``bash`` / ``write`` / ``edit`` tools over the MCP stdio transport. Each
tool call is serviced by a host-side :class:`~rfc.container_exec_broker.ContainerExecBroker`
that ``docker exec``s into a pre-warmed, network-isolated container. A harness is
configured to DENY its native host-executing code tools and call these instead
(claude-code: ``--settings`` deny-rules + ``--mcp-config``), so the untrusted,
model-generated commands run behind the network boundary rather than on the host.

The transport is newline-delimited JSON-RPC 2.0 on stdin/stdout -- exactly what
an MCP stdio server speaks -- implemented here without the ``mcp`` SDK so the
module imports and unit-tests with zero extra dependencies and no live Docker.
Message handling (:func:`handle_message`) is a pure function of the request and
an injected :class:`BrokerDispatcher`, so the whole protocol surface is
hermetically testable; :func:`main` wires a real broker from the container id in
``RFC_EXEC_CONTAINER_ID``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

from .container_exec_broker import ContainerExecBroker, SandboxToolCall

SERVER_NAME = "rfc-exec"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"

# Env var the sandbox sets on the MCP server child so the broker binds to the
# run's pre-warmed container.
CONTAINER_ID_ENV = "RFC_EXEC_CONTAINER_ID"
# Env var pointing at the file the broker appends per-call overhead samples to,
# so the sandbox parent collects them after the run (the dispatching broker
# lives in this child process).
METRICS_PATH_ENV = "RFC_EXEC_METRICS_PATH"

# The native host-executing code tools a harness must DENY so all code-exec
# routes through this server instead (claude-code names, capitalized). Read is
# denied too (MVP coherence ruling, #235): the agent reads via broker'd
# ``bash cat`` so it never sees the stale host CWD stub.
DENY_TOOLS: tuple[str, ...] = ("Bash", "Write", "Edit", "Read")

# opencode's native code tools (lowercase, opencode's own tool ids), the
# opencode-name parallel to :data:`DENY_TOOLS`. Denying these is how opencode's
# per-tool-call bash/write/edit stop running host-native and route through the
# rfc-exec MCP server into the container instead (#381 F5). ``patch`` is
# opencode's structured whole-file edit tool -- denied too so an edit can't slip
# past to the host. ``read`` is denied for the same MVP coherence reason as
# claude-code: the agent reads via the broker'd ``rfc-exec_bash`` (cat) and never
# sees the stale host CWD stub. The namespaced MCP tools (``rfc-exec_bash`` etc.)
# are NOT gated by these native tool ids -- verified live: denying native
# ``bash`` leaves ``rfc-exec_bash`` fully callable.
OPENCODE_DENY_TOOLS: tuple[str, ...] = ("bash", "edit", "write", "patch", "read")

# JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# The tools the model calls instead of its denied native code tools. Names are
# deliberately the plain verbs; claude-code surfaces them in stream-json as
# ``mcp__rfc-exec__bash`` etc. (pattern ``mcp__<server>__<tool>``).
_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "bash",
        "description": (
            "Run a shell command inside the sandbox container's /workspace. "
            "Use this for ALL shell work (including reading files via cat)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command."}
            },
            "required": ["command"],
        },
    },
    {
        "name": "write",
        "description": (
            "Write a file inside the sandbox container's /workspace (path is "
            "workspace-relative and confined to /workspace), creating parent "
            "directories as needed. Overwrites any existing file. Content of any "
            "size is supported."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Workspace-relative file path.",
                },
                "content": {"type": "string", "description": "Full file content."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit",
        "description": (
            "Replace a file's full content inside the sandbox container's "
            "/workspace (MVP: whole-file write at the workspace-relative, "
            "/workspace-confined path)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Workspace-relative file path.",
                },
                "content": {"type": "string", "description": "Full new content."},
            },
            "required": ["path", "content"],
        },
    },
]


def mcp_tool_definitions() -> List[Dict[str, Any]]:
    """The rfc-exec tools as MCP tool definitions."""
    return [dict(defn) for defn in _TOOL_DEFINITIONS]


# ---------------------------------------------------------------------------
# Harness wiring: how to launch this server and deny the native code tools.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SandboxExecRouting:
    """How a harness launches the rfc-exec server against one run's container.

    ``container_id`` binds the server's broker to the run's pre-warmed container;
    ``metrics_path`` is where the broker appends overhead samples for the parent.
    The defaults launch ``python -m rfc.exec_mcp`` under the current interpreter
    so ``rfc`` is importable in the child.
    """

    container_id: str
    metrics_path: str = ""
    python_bin: str = field(default_factory=lambda: sys.executable)
    mcp_module: str = "rfc.exec_mcp"
    server_name: str = SERVER_NAME


def deny_settings() -> Dict[str, Any]:
    """The ``--settings`` payload that denies the native host code tools."""
    return {"permissions": {"deny": list(DENY_TOOLS)}}


def deny_settings_json() -> str:
    return json.dumps(deny_settings())


def _server_env(routing: SandboxExecRouting) -> Dict[str, str]:
    env = {CONTAINER_ID_ENV: routing.container_id}
    if routing.metrics_path:
        env[METRICS_PATH_ENV] = routing.metrics_path
    return env


def claude_mcp_config(routing: SandboxExecRouting) -> Dict[str, Any]:
    """The claude-code ``--mcp-config`` payload registering the stdio server."""
    return {
        "mcpServers": {
            routing.server_name: {
                "type": "stdio",
                "command": routing.python_bin,
                "args": ["-m", routing.mcp_module],
                "env": _server_env(routing),
            }
        }
    }


def claude_mcp_config_json(routing: SandboxExecRouting) -> str:
    return json.dumps(claude_mcp_config(routing))


def opencode_mcp_config(routing: SandboxExecRouting) -> Dict[str, Any]:
    """The opencode ``mcp`` config block registering this server as a local tool.

    LIVE-CONFORMED (#381): verified against the real opencode 1.2.9 CLI with a
    local Ollama model -- with this block merged into the run config, opencode
    launches ``python -m rfc.exec_mcp`` as a local MCP server and the model calls
    its ``rfc-exec_bash`` / ``rfc-exec_write`` / ``rfc-exec_edit`` tools, whose
    edits land in the bound container's ``/workspace`` (not a host tree).
    """
    return {
        "mcp": {
            routing.server_name: {
                "type": "local",
                "command": [routing.python_bin, "-m", routing.mcp_module],
                "enabled": True,
                "environment": _server_env(routing),
            }
        }
    }


def opencode_deny_config() -> Dict[str, Any]:
    """opencode config keys that DENY its native host-executing code tools (#381).

    The opencode-name parallel to claude-code's ``--settings`` deny payload
    (:func:`deny_settings`). Two config-level layers, both honoured by opencode's
    own config loader:

      * ``permission`` -- opencode's permission engine gates each native tool to
        ``deny`` (the enforced, fail-closed layer: a denied tool call is refused
        before it executes on the host). This is the load-bearing mechanism --
        verified live that ``tools``-disable alone can be bypassed under
        adversarial prompting while a ``permission: deny`` native ``bash`` call is
        refused.
      * ``tools`` -- disables each native tool in the registry (the primary layer;
        the model is not offered the native tool at all).

    Together they are the F4 defense-in-depth for opencode's deny surface:
    ``tools`` removes the native tool from the offer, ``permission`` fails closed
    if a denied tool is somehow still invoked. opencode has no PreToolUse hook
    (that is a claude-code-specific mechanism); this config-level dual denial IS
    opencode's equivalent, and it is what forces per-tool-call exec through the
    rfc-exec broker instead of the host.
    """
    return {
        "permission": {tool: "deny" for tool in OPENCODE_DENY_TOOLS},
        "tools": {tool: False for tool in OPENCODE_DENY_TOOLS},
    }


@dataclass(frozen=True)
class DispatchOutcome:
    """One tool call's rendered result (MCP ``content`` text + error flag)."""

    text: str
    is_error: bool


class BrokerDispatcher:
    """Adapt MCP ``tools/call`` arguments onto a :class:`ContainerExecBroker`.

    Pure translation: it marshals each tool's arguments into a
    :class:`SandboxToolCall`, dispatches through the broker, and renders the
    :class:`~rfc.container_exec_broker.SandboxToolResult` as MCP text. Keeping it
    separate from the JSON-RPC layer means the protocol is testable with a fake
    dispatcher and the broker is testable without JSON-RPC.
    """

    def __init__(self, broker: ContainerExecBroker) -> None:
        self._broker = broker

    def dispatch(self, name: str, arguments: Dict[str, Any]) -> DispatchOutcome:
        try:
            call = self._marshal(name, arguments)
        except ValueError as exc:
            return DispatchOutcome(text=str(exc), is_error=True)
        result = self._broker.dispatch(call)
        text = result.stdout
        if result.stderr:
            text = f"{text}\n{result.stderr}" if text else result.stderr
        return DispatchOutcome(text=text, is_error=result.exit_code != 0)

    @staticmethod
    def _marshal(name: str, arguments: Dict[str, Any]) -> SandboxToolCall:
        if name == "bash":
            command = arguments.get("command")
            if not isinstance(command, str) or not command:
                raise ValueError("bash requires a non-empty 'command'")
            return SandboxToolCall(kind="bash", payload=command)
        if name in ("write", "edit"):
            path = arguments.get("path")
            content = arguments.get("content")
            if not isinstance(path, str) or not path:
                raise ValueError(f"{name} requires a non-empty 'path'")
            if not isinstance(content, str):
                raise ValueError(f"{name} requires string 'content'")
            return SandboxToolCall(kind=name, payload=content, path=path)
        raise ValueError(f"Unknown tool {name!r}")


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
    dispatcher: Optional[BrokerDispatcher],
) -> Dict[str, Any]:
    name = params.get("name")
    if not isinstance(name, str) or not name:
        return _error(request_id, INVALID_PARAMS, "tools/call requires a 'name'")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _error(request_id, INVALID_PARAMS, "'arguments' must be an object")

    if dispatcher is None:
        # Protocol is alive but no container is wired (e.g. no Docker daemon).
        return _result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "No sandbox container is available to execute tool "
                            f"calls. Set {CONTAINER_ID_ENV} to a running container."
                        ),
                    }
                ],
                "isError": True,
            },
        )

    outcome = dispatcher.dispatch(name, arguments)
    return _result(
        request_id,
        {
            "content": [{"type": "text", "text": outcome.text}],
            "isError": outcome.is_error,
        },
    )


def handle_message(
    message: Dict[str, Any],
    dispatcher: Optional[BrokerDispatcher] = None,
) -> Optional[Dict[str, Any]]:
    """Handle one JSON-RPC message; return a response, or None for notifications.

    ``dispatcher`` services ``tools/call``; when it is None the protocol still
    works and tool calls come back as an MCP error result rather than crashing.
    """
    request_id = message.get("id")
    method = message.get("method")

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
    dispatcher: Optional[BrokerDispatcher] = None,
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


def _build_dispatcher() -> Optional[BrokerDispatcher]:  # pragma: no cover
    """Wire a real broker from ``RFC_EXEC_CONTAINER_ID`` (needs a Docker daemon).

    Returns None when the container id is unset or Docker is unreachable, so the
    protocol still answers ``tools/list`` and ``tools/call`` returns a clear MCP
    error rather than the server crashing.
    """
    container_id = os.environ.get(CONTAINER_ID_ENV, "").strip()
    if not container_id:
        return None
    metrics_raw = os.environ.get(METRICS_PATH_ENV, "").strip()
    metrics_sink = Path(metrics_raw) if metrics_raw else None
    try:
        from .container_manager import ContainerManager

        broker = ContainerExecBroker(
            ContainerManager(), container_id, metrics_sink=metrics_sink
        )
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[{SERVER_NAME}] container unavailable: {exc}\n")
        return None
    return BrokerDispatcher(broker)


def main() -> None:  # pragma: no cover - process entrypoint
    """Entrypoint: ``python -m rfc.exec_mcp``."""
    serve(sys.stdin, sys.stdout, _build_dispatcher())


if __name__ == "__main__":  # pragma: no cover
    main()
