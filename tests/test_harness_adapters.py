"""Tests for rfc.harness_adapters — the multi-harness CLI seam (Issue #172).

Every parser test feeds a recorded transcript to the adapter, so the suite is
deterministic and CI-safe (no real CLI, no network). The opencode
acceptance test drives a full LiveClaudeCodeRunner with a stub invoker and then
grades the resulting AgentRun with the existing agent_verifiers — proving an
opencode run normalizes to the same contract the Claude Code path does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from rfc.agent_config import AgentConfig
from rfc.agent_contract import AgentContract
from rfc.agent_run import AgentRun
from rfc.agent_verifiers import (
    assert_all_commits_match_convention,
    assert_branch_matches_contract,
    assert_commands_appear_in_order,
    assert_no_commit_while_tests_red,
)
from rfc.harness_adapters import (
    ADAPTERS,
    ClaudeCodeAdapter,
    ClaudeProcessResult,
    CodexAdapter,
    HarnessAdapter,
    OpenCodeAdapter,
    _probe_binary,
    get_adapter,
    make_branch_name,
    parse_codex_events,
    parse_opencode_events,
)
from rfc.harness_cli import TOOLS
from rfc.live_agent_runner import LiveClaudeCodeRunner

# ---------------------------------------------------------------------------
# Shared helpers.
# ---------------------------------------------------------------------------


def _config(**overrides: Any) -> AgentConfig:
    base: dict[str, Any] = {
        "id": "opencode",
        "runner": "live",
        "model": "",
        "endpoint": "",
        "timeout_seconds": 600,
        "temperature": 0.0,
        "capabilities": (),
        "env_vars": (),
    }
    base.update(overrides)
    return AgentConfig(**base)


@dataclass
class StubInvoker:
    """Return canned ClaudeProcessResults per command-substring match."""

    canned: dict[str, ClaudeProcessResult] = field(default_factory=dict)
    default: ClaudeProcessResult = field(
        default_factory=lambda: ClaudeProcessResult(returncode=0, stdout="", stderr="")
    )
    calls: list[tuple[tuple[str, ...], Path, dict[str, str], int]] = field(
        default_factory=list
    )

    def __call__(
        self,
        argv: tuple[str, ...],
        cwd: Path,
        env: dict[str, str],
        timeout: int,
    ) -> ClaudeProcessResult:
        self.calls.append((argv, cwd, dict(env), timeout))
        joined = " ".join(argv)
        for needle, result in self.canned.items():
            if needle in joined:
                return result
        return self.default


def _oc_stream(events: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def _oc_bash(
    call_id: str, command: str, output: str, *, status: str = "completed"
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "status": status,
        "input": {"command": command, "description": "run"},
        "time": {"start": 1, "end": 2},
    }
    if status == "error":
        state["error"] = output
    else:
        state["output"] = output
    return {
        "type": "tool_use",
        "part": {"type": "tool", "tool": "bash", "callID": call_id, "state": state},
    }


def _oc_text(text: str) -> dict[str, Any]:
    return {"type": "text", "part": {"type": "text", "text": text}}


def _codex_stream(events: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


# ---------------------------------------------------------------------------
# Protocol conformance + registry.
# ---------------------------------------------------------------------------


class TestProtocolAndRegistry:
    @pytest.mark.parametrize(
        "adapter",
        [ClaudeCodeAdapter(), OpenCodeAdapter(), CodexAdapter()],
    )
    def test_adapters_satisfy_protocol(self, adapter: HarnessAdapter) -> None:
        assert isinstance(adapter, HarnessAdapter)

    def test_registry_matches_tool_taxonomy(self) -> None:
        assert set(ADAPTERS) == set(TOOLS)

    def test_get_adapter_builds_each(self) -> None:
        assert isinstance(get_adapter("claude-code"), ClaudeCodeAdapter)
        assert isinstance(get_adapter("opencode"), OpenCodeAdapter)
        assert isinstance(get_adapter("codex"), CodexAdapter)

    def test_get_adapter_unknown_raises(self) -> None:
        with pytest.raises(KeyError, match="gemini"):
            get_adapter("gemini")

    def test_branch_prefixes_are_distinct(self) -> None:
        prefixes = {a().branch_prefix for a in ADAPTERS.values()}
        assert prefixes == {"claude", "opencode", "codex"}


class TestMakeBranchName:
    def test_default_prefix_is_claude(self) -> None:
        assert make_branch_name("Rename helper").startswith("claude/")

    def test_prefix_override(self) -> None:
        assert make_branch_name("Rename helper", prefix="opencode").startswith(
            "opencode/"
        )

    def test_suffix_is_five_chars(self) -> None:
        assert len(make_branch_name("x", prefix="codex").rsplit("-", 1)[-1]) == 5


# ---------------------------------------------------------------------------
# Probe gating.
# ---------------------------------------------------------------------------


class TestProbe:
    def test_probe_binary_true_for_present_binary(self) -> None:
        # python3 answers `--version` with exit 0 on every CI runner.
        assert _probe_binary("python3") is True

    def test_probe_binary_false_for_absent_binary(self) -> None:
        assert _probe_binary("rfc-no-such-binary-xyz") is False

    def test_codex_probe_false_when_absent(self) -> None:
        assert CodexAdapter(codex_bin="rfc-no-such-binary-xyz").probe() is False

    def test_claude_probe_true_with_present_stand_in(self) -> None:
        assert ClaudeCodeAdapter(claude_bin="python3").probe() is True


# ---------------------------------------------------------------------------
# ClaudeCodeAdapter.
# ---------------------------------------------------------------------------


class TestClaudeCodeAdapter:
    def test_build_argv_shape(self) -> None:
        argv = ClaudeCodeAdapter().build_argv("Do a thing.", Path("/ws"))
        assert argv[0] == "claude"
        assert "-p" in argv
        assert "Do a thing." in argv
        assert "stream-json" in " ".join(argv)

    def test_parse_output_delegates_to_transcript(self) -> None:
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Bash",
                            "input": {"command": "uv run pytest"},
                        }
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t1",
                            "content": [{"type": "text", "text": "5 passed"}],
                            "is_error": False,
                        }
                    ]
                },
            },
        ]
        raw = "\n".join(json.dumps(e) for e in events) + "\n"
        commands, questions = ClaudeCodeAdapter().parse_output(raw)
        assert len(commands) == 1
        assert commands[0].argv == ("bash", "-lc", "uv run pytest")
        assert questions == ()

    def test_env_overrides_empty(self) -> None:
        assert ClaudeCodeAdapter().env_overrides() == {}


# ---------------------------------------------------------------------------
# OpenCodeAdapter.
# ---------------------------------------------------------------------------


class TestOpenCodeAdapter:
    def test_build_argv_uses_json_format(self) -> None:
        argv = OpenCodeAdapter().build_argv("Add a foo.", Path("/ws"))
        assert argv[:4] == ["opencode", "run", "--format", "json"]
        assert argv[-1] == "Add a foo."

    def test_build_argv_includes_model_when_set(self) -> None:
        argv = OpenCodeAdapter(model="ollama/qwen3-coder:30b").build_argv(
            "t", Path("/ws")
        )
        assert "--model" in argv
        assert "ollama/qwen3-coder:30b" in argv

    def test_env_overrides_exports_config_path(self, tmp_path: Path) -> None:
        cfg = tmp_path / "opencode.json"
        cfg.write_text("{}")
        assert OpenCodeAdapter(config_path=cfg).env_overrides() == {
            "OPENCODE_CONFIG": str(cfg)
        }

    def test_env_overrides_empty_without_config(self) -> None:
        assert OpenCodeAdapter().env_overrides() == {}

    def test_parse_completed_bash_command(self) -> None:
        raw = _oc_stream([_oc_bash("c1", "uv run pytest", "5 passed in 0.1s")])
        commands, questions = parse_opencode_events(raw)
        assert len(commands) == 1
        assert commands[0].argv == ("bash", "-lc", "uv run pytest")
        assert commands[0].returncode == 0
        assert "5 passed" in commands[0].stdout_tail
        assert questions == ()

    def test_parse_error_bash_command_is_nonzero(self) -> None:
        raw = _oc_stream([_oc_bash("c1", "pytest", "boom", status="error")])
        commands, _ = parse_opencode_events(raw)
        assert commands[0].returncode == 1
        assert "boom" in commands[0].stdout_tail

    def test_parse_skips_non_terminal_state(self) -> None:
        raw = _oc_stream([_oc_bash("c1", "sleep 1", "", status="running")])
        commands, _ = parse_opencode_events(raw)
        assert commands == ()

    def test_parse_orders_multiple_commands(self) -> None:
        raw = _oc_stream(
            [
                _oc_bash("c1", "git fetch", "ok"),
                _oc_bash("c2", "git checkout -b foo", "ok"),
            ]
        )
        commands, _ = parse_opencode_events(raw)
        assert [c.argv[-1] for c in commands] == ["git fetch", "git checkout -b foo"]

    def test_parse_extracts_clarifying_question(self) -> None:
        text = (
            "Before I start:\n\nWhich rename strategy do you prefer?\n"
            "  - Inline\n  - Codemod\n"
        )
        raw = _oc_stream([_oc_text(text)])
        _, questions = parse_opencode_events(raw)
        assert len(questions) == 1
        assert questions[0].text.endswith("?")
        assert any("Inline" in o for o in questions[0].options)

    def test_parse_ignores_non_bash_tool(self) -> None:
        event = {
            "type": "tool_use",
            "part": {
                "type": "tool",
                "tool": "read",
                "state": {"status": "completed", "input": {"filePath": "x"}},
            },
        }
        commands, _ = parse_opencode_events(_oc_stream([event]))
        assert commands == ()

    def test_parse_redacts_extra_secrets(self) -> None:
        raw = _oc_stream([_oc_bash("c1", "env", "API_KEY=hunter2-supersecret")])
        commands, _ = parse_opencode_events(raw, extra_secrets=("hunter2-supersecret",))
        assert "hunter2" not in commands[0].stdout_tail
        assert "[REDACTED]" in commands[0].stdout_tail

    def test_parse_skips_non_json_lines(self) -> None:
        raw = "not json\n" + _oc_stream([_oc_bash("c1", "ls", "x")])
        commands, _ = parse_opencode_events(raw)
        assert len(commands) == 1

    def test_parse_empty_returns_empty(self) -> None:
        assert parse_opencode_events("") == ((), ())


# ---------------------------------------------------------------------------
# CodexAdapter (parser tested; live path probe-gated / pending conformance).
# ---------------------------------------------------------------------------


class TestCodexAdapter:
    def test_build_argv_uses_exec_json(self) -> None:
        argv = CodexAdapter().build_argv("Fix the bug.", Path("/ws"))
        assert argv == ["codex", "exec", "--json", "Fix the bug."]

    def test_parse_exec_command_pair(self) -> None:
        raw = _codex_stream(
            [
                {"id": "0", "msg": {"type": "task_started"}},
                {
                    "id": "1",
                    "msg": {
                        "type": "exec_command_begin",
                        "call_id": "c1",
                        "command": ["bash", "-lc", "uv run pytest"],
                    },
                },
                {
                    "id": "2",
                    "msg": {
                        "type": "exec_command_end",
                        "call_id": "c1",
                        "stdout": "5 passed",
                        "stderr": "",
                        "exit_code": 0,
                    },
                },
            ]
        )
        commands, questions = parse_codex_events(raw)
        assert len(commands) == 1
        assert commands[0].argv == ("bash", "-lc", "uv run pytest")
        assert commands[0].returncode == 0
        assert "5 passed" in commands[0].stdout_tail
        assert questions == ()

    def test_parse_nonzero_exit_code(self) -> None:
        raw = _codex_stream(
            [
                {
                    "msg": {
                        "type": "exec_command_begin",
                        "call_id": "c1",
                        "command": ["bash", "-lc", "pytest"],
                    }
                },
                {
                    "msg": {
                        "type": "exec_command_end",
                        "call_id": "c1",
                        "stdout": "",
                        "stderr": "1 failed",
                        "exit_code": 1,
                    }
                },
            ]
        )
        commands, _ = parse_codex_events(raw)
        assert commands[0].returncode == 1
        assert "1 failed" in commands[0].stderr_tail

    def test_parse_agent_message_question(self) -> None:
        raw = _codex_stream(
            [
                {
                    "msg": {
                        "type": "agent_message",
                        "message": "Which approach?\n- A\n- B\n",
                    }
                }
            ]
        )
        _, questions = parse_codex_events(raw)
        assert len(questions) == 1
        assert questions[0].is_multiple_choice

    def test_parse_tolerates_flat_object(self) -> None:
        # Some codex builds emit a flat event without the "msg" envelope.
        raw = _codex_stream(
            [
                {
                    "type": "exec_command_begin",
                    "call_id": "c1",
                    "command": ["ls"],
                },
                {
                    "type": "exec_command_end",
                    "call_id": "c1",
                    "stdout": "file",
                    "exit_code": 0,
                },
            ]
        )
        commands, _ = parse_codex_events(raw)
        assert commands[0].argv == ("ls",)

    def test_parse_redacts_secrets(self) -> None:
        raw = _codex_stream(
            [
                {
                    "msg": {
                        "type": "exec_command_begin",
                        "call_id": "c1",
                        "command": ["bash", "-lc", "env"],
                    }
                },
                {
                    "msg": {
                        "type": "exec_command_end",
                        "call_id": "c1",
                        "stdout": "TOKEN=topsecret42",
                        "exit_code": 0,
                    }
                },
            ]
        )
        commands, _ = parse_codex_events(raw, extra_secrets=("topsecret42",))
        assert "topsecret42" not in commands[0].stdout_tail

    def test_parse_empty_returns_empty(self) -> None:
        assert parse_codex_events("") == ((), ())


# ---------------------------------------------------------------------------
# Acceptance: an opencode run normalizes to AgentRun and passes the verifiers.
# ---------------------------------------------------------------------------


def _opencode_contract() -> AgentContract:
    return AgentContract(
        agent_id="opencode",
        base_branch="main",
        branch_regex=r"^opencode/[a-z0-9-]+-[0-9a-f]{5}$",
        startup_checks=(),
        pr_template_path="",
        pr_required_sections=(),
        commit_types=("feat", "fix", "test", "docs", "refactor", "chore"),
        commit_subject_regex=r"^(feat|fix|test|docs|refactor|chore)(\(.+\))?: .+",
        min_clarifying_questions=0,
        max_clarifying_questions=5,
    )


def _write_task(root: Path, scenario_id: str) -> None:
    scenario_dir = root / scenario_id
    scenario_dir.mkdir(parents=True, exist_ok=True)
    (scenario_dir / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "scenario_id": scenario_id,
                "task": "Add a greet helper to src/rfc/example.py.",
                "base_branch": "main",
            }
        )
    )


class TestOpenCodeRunNormalizesToAgentRun:
    def test_opencode_run_passes_existing_verifiers(self, tmp_path: Path) -> None:
        scenarios_root = tmp_path / "scenarios"
        _write_task(scenarios_root, "greet")

        transcript = _oc_stream(
            [
                _oc_bash("c1", "uv run pytest", "5 passed in 0.2s"),
                _oc_bash("c2", 'git commit -m "feat: add greet helper"', "1 file"),
            ]
        )
        invoker = StubInvoker(
            canned={
                "opencode run": ClaudeProcessResult(
                    returncode=0, stdout=transcript, stderr=""
                ),
                "git log": ClaudeProcessResult(
                    returncode=0,
                    stdout="aaa111\x1ffeat: add greet helper\x1fbody\x1e\n",
                    stderr="",
                ),
                "git show": ClaudeProcessResult(
                    returncode=0, stdout="src/rfc/example.py\n", stderr=""
                ),
                "status --porcelain": ClaudeProcessResult(
                    returncode=0, stdout=" M src/rfc/example.py\n", stderr=""
                ),
            }
        )
        runner = LiveClaudeCodeRunner(
            config=_config(id="opencode"),
            scenarios_root=scenarios_root,
            invoker=invoker,
            workspace_root=tmp_path / "ws",
            repo_root=tmp_path / "repo",
            adapter=OpenCodeAdapter(),
        )

        run = runner.run("greet")

        # It really is a normalized AgentRun from the opencode transcript.
        assert isinstance(run, AgentRun)
        assert run.agent_id == "opencode"
        assert run.branch_name.startswith("opencode/")
        assert [c.argv[-1] for c in run.commands] == [
            "uv run pytest",
            'git commit -m "feat: add greet helper"',
        ]

        # And it passes the same tier:1 verifiers the Claude Code path does.
        contract = _opencode_contract()
        assert_branch_matches_contract(run, contract)
        assert_commands_appear_in_order(run, ["uv run pytest", "git commit"])
        assert_no_commit_while_tests_red(run)
        assert_all_commits_match_convention(run, contract)

    def test_opencode_invocation_gets_config_env(self, tmp_path: Path) -> None:
        scenarios_root = tmp_path / "scenarios"
        _write_task(scenarios_root, "greet")
        cfg = tmp_path / "opencode.json"
        cfg.write_text("{}")
        invoker = StubInvoker()
        runner = LiveClaudeCodeRunner(
            config=_config(id="opencode"),
            scenarios_root=scenarios_root,
            invoker=invoker,
            workspace_root=tmp_path / "ws",
            repo_root=tmp_path / "repo",
            adapter=OpenCodeAdapter(config_path=cfg),
        )
        runner.run("greet")
        oc_calls = [c for c in invoker.calls if "opencode" in c[0][0]]
        assert oc_calls, "expected an opencode invocation"
        _, _, env, _ = oc_calls[0]
        assert env == {"OPENCODE_CONFIG": str(cfg)}
