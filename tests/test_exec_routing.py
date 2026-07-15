"""Adapter-side wiring for container-routed code execution (#235).

Covers the two load-bearing claims of the design note's item 2/3:
  * ``parse_transcript`` keys the container-routed ``mcp__rfc-exec__bash`` tool
    exactly like native ``Bash`` -- else every remoted command drops out of the
    AgentRun and the trajectory looks empty.
  * the claude-code adapter, when routing is armed, DENIES the native code tools
    via ``--settings`` and registers the rfc-exec MCP server via ``--mcp-config``
    (config-level assertion, no live CLI needed); with routing off the argv is
    the host-native invocation, unchanged.
"""

from __future__ import annotations

import json

from rfc.exec_mcp import CONTAINER_ID_ENV, SERVER_NAME, SandboxExecRouting
from rfc.harness_adapters import (
    ClaudeCodeAdapter,
    OpenCodeAdapter,
    parse_transcript,
)


def _assistant_bash(tool_name: str, tool_id: str, command: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": tool_name,
                        "input": {"command": command},
                    }
                ]
            },
        }
    )


def _user_result(tool_id: str, text: str, is_error: bool = False) -> str:
    return json.dumps(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": [{"type": "text", "text": text}],
                        "is_error": is_error,
                    }
                ]
            },
        }
    )


class TestParseTranscriptMcpBash:
    def test_mcp_rfc_exec_bash_becomes_agent_command(self) -> None:
        transcript = (
            _assistant_bash("mcp__rfc-exec__bash", "tu1", "sed -i 's/a+b/a-b/' calc.py")
            + "\n"
            + _user_result("tu1", "done")
            + "\n"
        )
        commands, questions = parse_transcript(transcript)
        assert len(commands) == 1
        assert commands[0].argv == ("bash", "-lc", "sed -i 's/a+b/a-b/' calc.py")
        assert commands[0].returncode == 0
        assert commands[0].stdout_tail == "done"
        assert questions == ()

    def test_native_bash_still_parsed(self) -> None:
        transcript = (
            _assistant_bash("Bash", "tu2", "pytest -q")
            + "\n"
            + _user_result("tu2", "ok")
            + "\n"
        )
        commands, _ = parse_transcript(transcript)
        assert len(commands) == 1
        assert commands[0].argv == ("bash", "-lc", "pytest -q")

    def test_mcp_bash_error_result_sets_returncode(self) -> None:
        transcript = (
            _assistant_bash("mcp__rfc-exec__bash", "tu3", "false")
            + "\n"
            + _user_result("tu3", "boom", is_error=True)
            + "\n"
        )
        commands, _ = parse_transcript(transcript)
        assert commands[0].returncode == 1


class TestClaudeCodeAdapterRouting:
    def test_host_native_argv_unchanged_without_routing(self) -> None:
        adapter = ClaudeCodeAdapter()
        argv = adapter.build_argv("fix the bug", __import__("pathlib").Path("/ws"))
        assert argv == [
            "claude",
            "-p",
            "fix the bug",
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        assert "--settings" not in argv
        assert "--mcp-config" not in argv

    def test_routing_denies_native_tools_and_registers_mcp(self) -> None:
        from pathlib import Path

        routing = SandboxExecRouting(container_id="cid-xyz", metrics_path="/tmp/o")
        adapter = ClaudeCodeAdapter(exec_routing=routing)
        argv = adapter.build_argv("fix the bug", Path("/ws"))

        # --settings carries a deny-rule that strips native Bash (and the other
        # host code tools) -- the config-level proof that native code exec is off.
        settings_json = argv[argv.index("--settings") + 1]
        deny = json.loads(settings_json)["permissions"]["deny"]
        assert "Bash" in deny
        assert {"Bash", "Write", "Edit", "Read"} <= set(deny)

        # --mcp-config registers the rfc-exec stdio server bound to the container.
        mcp_json = argv[argv.index("--mcp-config") + 1]
        server = json.loads(mcp_json)["mcpServers"][SERVER_NAME]
        assert server["type"] == "stdio"
        assert server["env"][CONTAINER_ID_ENV] == "cid-xyz"


class TestOpenCodeAdapterRouting:
    def test_overlay_empty_without_routing(self) -> None:
        assert OpenCodeAdapter().exec_config_overlay() == {}

    def test_overlay_points_mcp_at_rfc_exec(self) -> None:
        routing = SandboxExecRouting(container_id="cid-oc")
        overlay = OpenCodeAdapter(exec_routing=routing).exec_config_overlay()
        server = overlay["mcp"][SERVER_NAME]
        assert server["type"] == "local"
        assert server["environment"][CONTAINER_ID_ENV] == "cid-oc"
