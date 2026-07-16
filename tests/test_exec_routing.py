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
from pathlib import Path

from rfc.exec_mcp import (
    CONTAINER_ID_ENV,
    OPENCODE_DENY_TOOLS,
    SERVER_NAME,
    SandboxExecRouting,
    opencode_deny_config,
)
from rfc.harness_adapters import (
    ClaudeCodeAdapter,
    OpenCodeAdapter,
    parse_transcript,
)
from rfc.opencode_config import _DEFAULT_OPENCODE_CONFIG as _LOCAL_CFG_PATH


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

    def test_overlay_denies_native_code_tools(self) -> None:
        # #381 F4/config-level proof (the opencode parallel to #352's claude-code
        # deny-settings assertion): the routing overlay must STRIP opencode's
        # native host-executing code tools, so the model's only path to
        # bash/write/edit is the broker'd rfc-exec tools. Two layers -- the
        # ``tools`` registry disable AND the ``permission`` deny gate (the
        # load-bearing, fail-closed layer verified live against opencode 1.2.9).
        routing = SandboxExecRouting(container_id="cid-oc")
        overlay = OpenCodeAdapter(exec_routing=routing).exec_config_overlay()
        # Every native code tool is denied by opencode's permission engine ...
        for tool in ("bash", "write", "edit", "read", "patch"):
            assert overlay["permission"][tool] == "deny", tool
            # ... AND disabled in the tool registry (defence in depth).
            assert overlay["tools"][tool] is False, tool
        # The MCP server is still registered -- denying NATIVE bash does not gate
        # the namespaced rfc-exec_bash tool (verified live #381).
        assert SERVER_NAME in overlay["mcp"]

    def test_apply_routed_config_writes_deny_at_cwd_tier(self, tmp_path: Path) -> None:
        # #383 SECURITY: the deny MUST land at opencode's HIGHEST precedence tier
        # -- the cwd project config <workspace>/opencode.json -- not only the
        # env-tier OPENCODE_CONFIG (which any ancestor opencode.json outranks,
        # re-enabling native host exec). apply_routed_config writes BOTH; this pins
        # the load-bearing cwd-tier write carries the full deny with every native
        # code tool key explicit (so no omitted key falls through to an ancestor).
        routing = SandboxExecRouting(container_id="cid-oc")
        adapter = OpenCodeAdapter(config_path=_LOCAL_CFG_PATH, exec_routing=routing)
        dest_dir = tmp_path / "run"
        dest_dir.mkdir()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        adapter.apply_routed_config(dest_dir, workspace)

        cwd_cfg = json.loads((workspace / "opencode.json").read_text())
        for tool in ("bash", "write", "edit", "read", "patch"):
            assert cwd_cfg["permission"][tool] == "deny", tool
            assert cwd_cfg["tools"][tool] is False, tool
        assert SERVER_NAME in cwd_cfg["mcp"]
        # The env-tier copy is written too (defence in depth) and exported.
        env_cfg = json.loads((dest_dir / "opencode.routed.json").read_text())
        assert env_cfg["permission"]["bash"] == "deny"
        assert adapter.env_overrides()["OPENCODE_CONFIG"] == str(
            dest_dir / "opencode.routed.json"
        )

    def test_apply_routed_config_scrubs_seed_shipped_config(
        self, tmp_path: Path
    ) -> None:
        # #383: a scenario seed that ships its OWN <workspace>/opencode.json (or
        # .jsonc) sits at the SAME cwd tier as our deny -- a collision. Scrub-then-
        # write: the seed's opencode.json is overwritten and opencode.jsonc removed,
        # so the deny ALWAYS wins and a seed-shipped allow can never survive.
        routing = SandboxExecRouting(container_id="cid-oc")
        adapter = OpenCodeAdapter(config_path=_LOCAL_CFG_PATH, exec_routing=routing)
        dest_dir = tmp_path / "run"
        dest_dir.mkdir()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # Adversarial seed configs at the workspace root, both granting bash.
        (workspace / "opencode.json").write_text(
            json.dumps({"permission": {"bash": "allow"}, "tools": {"bash": True}})
        )
        (workspace / "opencode.jsonc").write_text('{"permission":{"bash":"allow"}}')

        adapter.apply_routed_config(dest_dir, workspace)

        # The seed opencode.json is replaced by our deny ...
        cwd_cfg = json.loads((workspace / "opencode.json").read_text())
        assert cwd_cfg["permission"]["bash"] == "deny"
        assert cwd_cfg["tools"]["bash"] is False
        # ... and the .jsonc variant (same tier) is scrubbed entirely.
        assert not (workspace / "opencode.jsonc").exists()


class TestOpenCodeDenyConfig:
    def test_deny_config_covers_every_deny_tool(self) -> None:
        # opencode_deny_config is the opencode-name parallel to claude-code's
        # deny_settings: it must deny (permission) AND disable (tools) exactly the
        # OPENCODE_DENY_TOOLS set -- no native code tool left un-stripped.
        cfg = opencode_deny_config()
        assert set(cfg["permission"]) == set(OPENCODE_DENY_TOOLS)
        assert set(cfg["tools"]) == set(OPENCODE_DENY_TOOLS)
        assert all(action == "deny" for action in cfg["permission"].values())
        assert all(enabled is False for enabled in cfg["tools"].values())
        # bash/write/edit/read -- the code-exec + coherence surface -- are covered.
        assert {"bash", "write", "edit", "read"} <= set(OPENCODE_DENY_TOOLS)
