"""Tests for rfc.harness_adapters — the multi-harness CLI seam (Issue #172).

Every parser test feeds a recorded transcript to the adapter, so the suite is
deterministic and CI-safe (no real CLI, no network). The opencode
acceptance test drives a full LiveClaudeCodeRunner with a stub invoker and then
grades the resulting AgentRun with the existing agent_verifiers — proving an
opencode run normalizes to the same contract the Claude Code path does.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from rfc.agent_config import AgentConfig
from rfc.agent_contract import AgentContract
from rfc.agent_run import AgentCommand, AgentRun
from rfc.agent_verifiers import (
    VerificationFailure,
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
    parse_transcript,
)
from rfc.harness_cli import TOOLS
from rfc.live_agent_runner import LiveClaudeCodeRunner
from rfc.opencode_config import ComparabilityError, VerifiedLocalModel

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
    call_id: str,
    command: str,
    output: str,
    *,
    status: str = "completed",
    exit_code: int | str | None = None,
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
    if exit_code is not None:
        # opencode 1.2.9 records the real shell exit in state.metadata.exit even
        # when status == "completed" (#390 live capture).
        state["metadata"] = {
            "output": output,
            "exit": exit_code,
            "description": "run",
            "truncated": False,
        }
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
# #402: claude-code parse_transcript must derive returncode from a VERIFIED
# exit, never a fabricated one. The host-native Bash leg's only exit signal is
# the boolean ``is_error``; the prior ``bool(block.get("is_error", False))``
# silently mapped an ABSENT is_error to returncode 0 (green) -- the same
# unverified-assumption bypass as #390. These tests pin faithfulness: an
# is_error=True bash result is RED, and a bash result with NO is_error is NOT
# silently mapped to 0. Every transcript is hand-serialized stream-json (no CLI,
# no network) so the guard is deterministic and CI-safe.
# ---------------------------------------------------------------------------


def _cc_stream(events: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def _cc_bash(tool_id: str, command: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": "Bash",
                    "input": {"command": command},
                }
            ]
        },
    }


def _cc_result(tool_id: str, text: str, **result_fields: Any) -> dict[str, Any]:
    """A claude-code ``tool_result`` user event.

    ``result_fields`` are spliced into the tool_result block verbatim, so a test
    can set ``is_error=True`` / ``is_error=False``, pass ``is_error=None``, or
    OMIT ``is_error`` entirely (the #402 unverified case) to exercise each
    branch of :func:`_claude_bash_returncode`.
    """
    result_block: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_id,
        "content": [{"type": "text", "text": text}],
    }
    result_block.update(result_fields)
    return {"type": "user", "message": {"content": [result_block]}}


class TestClaudeCodeReturncodeVerifierBypass402:
    def _run(self, commands: tuple[AgentCommand, ...]) -> AgentRun:
        return AgentRun(
            agent_id="claude-code",
            scenario_id="s1",
            task="t",
            base_branch="main",
            branch_name="claude/x-abcde",
            commands=commands,
        )

    def test_is_error_true_records_red(self) -> None:
        raw = _cc_stream(
            [
                _cc_bash("t1", "uv run pytest"),
                _cc_result("t1", "1 failed", is_error=True),
            ]
        )
        commands, _ = parse_transcript(raw)
        assert commands[0].returncode == 1

    def test_is_error_false_stays_green(self) -> None:
        raw = _cc_stream(
            [
                _cc_bash("t1", "uv run pytest"),
                _cc_result("t1", "5 passed", is_error=False),
            ]
        )
        commands, _ = parse_transcript(raw)
        assert commands[0].returncode == 0

    def test_absent_is_error_is_not_silently_green(self) -> None:
        # THE #402 defect: a bash tool_result with NO ``is_error`` key. The prior
        # ``.get("is_error", False)`` fabricated returncode 0 (green) from an exit
        # signal the harness never captured; a deliberately failing command
        # (``exit 3``) must record NONZERO, not be silently mapped to 0.
        raw = _cc_stream(
            [
                _cc_bash("t1", "sh -c 'echo boom; exit 3'"),
                _cc_result("t1", "boom"),
            ]
        )
        commands, _ = parse_transcript(raw)
        assert commands[0].returncode != 0

    def test_null_is_error_is_not_silently_green(self) -> None:
        # A present-but-null ``is_error`` is not a verified success either.
        raw = _cc_stream([_cc_bash("t1", "false"), _cc_result("t1", "", is_error=None)])
        commands, _ = parse_transcript(raw)
        assert commands[0].returncode != 0

    def test_nonzero_test_then_commit_is_flagged_red(self) -> None:
        # The corrupting sequence: pytest fails (is_error=True), then a commit.
        # The verifier spine must fire now that the failed test is recorded red.
        raw = _cc_stream(
            [
                _cc_bash("t1", "uv run pytest"),
                _cc_result("t1", "1 failed", is_error=True),
                _cc_bash("t2", "git commit -m wip"),
                _cc_result("t2", "", is_error=False),
            ]
        )
        commands, _ = parse_transcript(raw)
        assert [c.returncode for c in commands] == [1, 0]
        with pytest.raises(VerificationFailure):
            assert_no_commit_while_tests_red(self._run(commands))

    def test_absent_signal_test_then_commit_is_flagged_red(self) -> None:
        # Same sequence, but the failing test's ``is_error`` is ABSENT. Pre-#402
        # the test recorded green and the commit slipped past the gate; now the
        # unverified test is red and the verifier fires -- the end-to-end proof
        # the bypass is closed on the spine, not just at the parser boundary.
        raw = _cc_stream(
            [
                _cc_bash("t1", "uv run pytest"),
                _cc_result("t1", "boom"),  # no is_error -> unverified -> red
                _cc_bash("t2", "git commit -m wip"),
                _cc_result("t2", "", is_error=False),
            ]
        )
        commands, _ = parse_transcript(raw)
        assert commands[0].returncode != 0
        with pytest.raises(VerificationFailure):
            assert_no_commit_while_tests_red(self._run(commands))

    def test_green_test_then_commit_passes(self) -> None:
        # Inverse: a genuinely green test (is_error=False) then a commit is
        # allowed -- the fix does not over-fire on real successes.
        raw = _cc_stream(
            [
                _cc_bash("t1", "uv run pytest"),
                _cc_result("t1", "5 passed", is_error=False),
                _cc_bash("t2", "git commit -m done"),
                _cc_result("t2", "", is_error=False),
            ]
        )
        commands, _ = parse_transcript(raw)
        assert_no_commit_while_tests_red(self._run(commands))  # no raise


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

    # -- #390: a completed-but-nonzero command must be recorded RED. ----------

    def test_completed_with_nonzero_metadata_exit_is_recorded_red(self) -> None:
        # Meeseeks' LIVE capture from opencode 1.2.9: `sh -c 'echo boom; exit 3'`
        # runs to completion (status == "completed") with the real shell exit in
        # state.metadata.exit. The parser must NOT map this to returncode 0.
        captured_event = {
            "part": {
                "type": "tool",
                "tool": "bash",
                "state": {
                    "status": "completed",
                    "input": {
                        "command": "sh -c 'echo boom; exit 3'",
                        "description": "probe exit code",
                    },
                    "output": "boom\n",
                    "metadata": {
                        "output": "boom\n",
                        "exit": 3,
                        "description": "probe exit code",
                        "truncated": False,
                    },
                    "time": {"start": 1784125695262, "end": 1784125695350},
                },
            }
        }
        raw = json.dumps(captured_event) + "\n"
        commands, _ = parse_opencode_events(raw)
        assert len(commands) == 1
        assert commands[0].argv == ("bash", "-lc", "sh -c 'echo boom; exit 3'")
        assert commands[0].returncode == 3  # was 0 before #390
        assert "boom" in commands[0].stdout_tail

    def test_completed_without_metadata_defaults_to_zero(self) -> None:
        # A completed event with no metadata.exit keeps the status-derived
        # default (0) — no regression for metadata-less / older events.
        raw = _oc_stream([_oc_bash("c1", "uv run pytest", "5 passed")])
        commands, _ = parse_opencode_events(raw)
        assert commands[0].returncode == 0

    def test_completed_with_zero_metadata_exit_stays_green(self) -> None:
        raw = _oc_stream([_oc_bash("c1", "uv run pytest", "5 passed", exit_code=0)])
        commands, _ = parse_opencode_events(raw)
        assert commands[0].returncode == 0

    def test_error_status_honors_metadata_exit_when_present(self) -> None:
        raw = _oc_stream(
            [_oc_bash("c1", "pytest", "boom", status="error", exit_code=2)]
        )
        commands, _ = parse_opencode_events(raw)
        assert commands[0].returncode == 2

    def test_error_status_without_metadata_defaults_to_one(self) -> None:
        raw = _oc_stream([_oc_bash("c1", "pytest", "boom", status="error")])
        commands, _ = parse_opencode_events(raw)
        assert commands[0].returncode == 1

    def test_stringified_metadata_exit_is_honored_not_swallowed(self) -> None:
        # A numeric-string exit must not silently normalize to green (#390).
        raw = _oc_stream([_oc_bash("c1", "pytest", "1 failed", exit_code="4")])
        commands, _ = parse_opencode_events(raw)
        assert commands[0].returncode == 4

    def test_bool_metadata_exit_is_treated_as_absent(self) -> None:
        # A JSON bool is an int subclass; it is never a real exit code, so the
        # status default (0 for completed) applies rather than coercing to 0/1.
        raw = _oc_stream([_oc_bash("c1", "true", "", exit_code=True)])  # type: ignore[arg-type]
        commands, _ = parse_opencode_events(raw)
        assert commands[0].returncode == 0


# ---------------------------------------------------------------------------
# #390 verifier bypass: a nonzero-exit test recorded green would let
# assert_no_commit_while_tests_red approve a commit made after red tests. Drive
# the parser -> AgentRun -> verifier spine end to end.
# ---------------------------------------------------------------------------


class TestOpenCodeReturncodeVerifierBypass390:
    def _run(self, commands: tuple[AgentCommand, ...]) -> AgentRun:
        return AgentRun(
            agent_id="opencode",
            scenario_id="s1",
            task="t",
            base_branch="main",
            branch_name="opencode/x-abcde",
            commands=commands,
        )

    def test_nonzero_pytest_then_commit_is_flagged_red(self) -> None:
        # Two separate commands, exactly the corrupting sequence from #390:
        # pytest completes NONZERO, then a commit is made. The verifier must
        # fire now that the completed-nonzero test is recorded red.
        raw = _oc_stream(
            [
                _oc_bash("c1", "uv run pytest", "1 failed", exit_code=1),
                _oc_bash("c2", "git commit -m wip", "", exit_code=0),
            ]
        )
        commands, _ = parse_opencode_events(raw)
        assert [c.returncode for c in commands] == [1, 0]
        with pytest.raises(VerificationFailure):
            assert_no_commit_while_tests_red(self._run(commands))

    def test_green_pytest_then_commit_passes(self) -> None:
        # The inverse: a genuinely green test followed by a commit is allowed —
        # the fix does not over-fire on real successes.
        raw = _oc_stream(
            [
                _oc_bash("c1", "uv run pytest", "5 passed", exit_code=0),
                _oc_bash("c2", "git commit -m done", "", exit_code=0),
            ]
        )
        commands, _ = parse_opencode_events(raw)
        assert_no_commit_while_tests_red(self._run(commands))  # no raise


# ---------------------------------------------------------------------------
# #390 live leg (a): drive the REAL opencode 1.2.9 CLI + local ollama and
# confirm the parser reads the true shell exit from a completed-but-nonzero
# command. Probe-gated: SKIPS (never fails) when the CLI / model is down or the
# small model does not comply under load. The deterministic guarantee lives in
# the fixture + verifier tests above; this leg proves the fix against real
# opencode output when the box can run it.
# ---------------------------------------------------------------------------

_CORE_ROOT = Path(__file__).resolve().parents[1]
_OPENCODE_CONFIG = _CORE_ROOT / "opencode.json"


def _ollama_up() -> bool:
    try:
        with urllib.request.urlopen(
            "http://localhost:11434/api/tags", timeout=3
        ) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _opencode_live_available() -> bool:
    # Opt-out escape hatch: driving the real 3b model can take minutes, so a box
    # that has opencode+ollama but does not want the per-run tax can export
    # RFC_SKIP_LIVE_OPENCODE=1 and the leg skips (the deterministic fixture +
    # verifier coverage still runs).
    if os.environ.get("RFC_SKIP_LIVE_OPENCODE"):
        return False
    return (
        shutil.which("opencode") is not None
        and _OPENCODE_CONFIG.is_file()
        and _ollama_up()
    )


def _raw_has_completed_nonzero_bash(raw: str) -> bool:
    """True if the raw stream carries a completed bash part with exit != 0.

    Independent of :func:`parse_opencode_events` so the live test can decide
    whether the model actually ran a failing command (assert) or never did
    (skip), without trusting the code under test to make that call.
    """
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = event.get("part") if isinstance(event, dict) else None
        if not isinstance(part, dict) or part.get("tool") != "bash":
            continue
        state = part.get("state")
        if not isinstance(state, dict) or state.get("status") != "completed":
            continue
        meta = state.get("metadata")
        if isinstance(meta, dict) and meta.get("exit") not in (0, None):
            return True
    return False


class TestLiveOpenCodeReturncode390:
    def test_live_completed_nonzero_bash_parses_nonzero(self, tmp_path: Path) -> None:
        if not _opencode_live_available():
            pytest.skip("opencode CLI + local ollama model not available")
        adapter = OpenCodeAdapter(config_path=_OPENCODE_CONFIG)
        task = (
            "Use the bash tool to run exactly this one shell command and then "
            "stop without doing anything else: sh -c 'echo boom; exit 3'"
        )
        argv = adapter.build_argv(task, tmp_path)
        env = os.environ.copy()
        env.update(adapter.env_overrides())
        # Bounded so a slow model skips (never fails) without a runaway tax;
        # override with RFC_LIVE_OPENCODE_TIMEOUT for a faster/idle box.
        timeout = int(os.environ.get("RFC_LIVE_OPENCODE_TIMEOUT", "180"))
        try:
            proc = subprocess.run(
                argv,
                cwd=str(tmp_path),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            pytest.skip(f"live opencode run unavailable under load: {exc!r}")
        raw = proc.stdout or ""
        if not _raw_has_completed_nonzero_bash(raw):
            pytest.skip(
                "opencode/model did not emit a completed nonzero-exit bash "
                "command (small model noncompliant under load)"
            )
        commands, _ = parse_opencode_events(raw)
        nonzero = [c for c in commands if c.returncode != 0]
        assert nonzero, (
            "parser recorded a real completed nonzero-exit command as green "
            "— the #390 defect"
        )
        probe = [c for c in commands if "exit 3" in c.argv[-1]]
        if probe:
            assert probe[0].returncode == 3


# ---------------------------------------------------------------------------
# OpenCodeAdapter comparability gate (#278): the adapter is the durable home of
# the selected-model-resolves-local check.
# ---------------------------------------------------------------------------


def _local_cfg_file(tmp_path: Path) -> Path:
    cfg = tmp_path / "opencode.json"
    cfg.write_text(
        json.dumps(
            {
                "model": "ollama/my-model",
                "provider": {
                    "ollama": {
                        "options": {"baseURL": "http://localhost:11434/v1"},
                        "models": {"my-model": {}},
                    }
                },
            }
        )
    )
    return cfg


def _remote_cfg_file(tmp_path: Path) -> Path:
    cfg = tmp_path / "opencode.json"
    cfg.write_text(json.dumps({"model": "openai/gpt-4o"}))
    return cfg


class TestOpenCodeAdapterComparability:
    def test_verify_local_model_returns_token_for_local_default(
        self, tmp_path: Path
    ) -> None:
        adapter = OpenCodeAdapter(config_path=_local_cfg_file(tmp_path))
        token = adapter.verify_local_model()
        assert isinstance(token, VerifiedLocalModel)
        assert token.model_id == "ollama/my-model"

    def test_verify_local_model_resolves_override_against_config(
        self, tmp_path: Path
    ) -> None:
        # A --model override must itself resolve local; a declared-local one passes
        # and the token attests the OVERRIDE, not the config default.
        adapter = OpenCodeAdapter(
            config_path=_local_cfg_file(tmp_path), model="ollama/my-model"
        )
        assert adapter.verify_local_model().model_id == "ollama/my-model"

    def test_verify_local_model_rejects_remote_override(self, tmp_path: Path) -> None:
        adapter = OpenCodeAdapter(
            config_path=_local_cfg_file(tmp_path), model="openai/gpt-4o"
        )
        with pytest.raises(ComparabilityError, match="not declared"):
            adapter.verify_local_model()

    def test_verify_local_model_rejects_remote_config(self, tmp_path: Path) -> None:
        adapter = OpenCodeAdapter(config_path=_remote_cfg_file(tmp_path))
        with pytest.raises(ComparabilityError, match="not declared"):
            adapter.verify_local_model()

    def test_require_local_comparability_gates_env_overrides(
        self, tmp_path: Path
    ) -> None:
        # Armed: any consumer materializing the env for a run gets the gate for
        # free -- a remote config fails closed BEFORE the CLI is launched (#278).
        armed = OpenCodeAdapter(
            config_path=_remote_cfg_file(tmp_path), require_local_comparability=True
        )
        with pytest.raises(ComparabilityError, match="not declared"):
            armed.env_overrides()
        # A local config passes the gate and still exports OPENCODE_CONFIG.
        local = _local_cfg_file(tmp_path)
        ok = OpenCodeAdapter(config_path=local, require_local_comparability=True)
        assert ok.env_overrides() == {"OPENCODE_CONFIG": str(local)}

    def test_env_overrides_unarmed_does_not_gate(self, tmp_path: Path) -> None:
        # Default (off): the general live-runner path over an arbitrary config is
        # unchanged -- a non-local config is NOT gated at env materialization.
        cfg = _remote_cfg_file(tmp_path)
        adapter = OpenCodeAdapter(config_path=cfg)
        assert adapter.env_overrides() == {"OPENCODE_CONFIG": str(cfg)}


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

    # -- #387: current codex exec --json item.completed / command_execution. --
    # FIXTURE-BASED (probe: codex CLI absent here, so no live leg). Shapes follow
    # the documented codex exec --json thread-item schema; see parse_codex_events
    # ASSUMPTION note + issue #387 for the live-conformance follow-up.

    def test_parse_item_completed_command_execution(self) -> None:
        raw = _codex_stream(
            [
                {"type": "thread.started", "thread_id": "t1"},
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_0",
                        "type": "command_execution",
                        "command": "bash -lc 'uv run pytest'",
                        "aggregated_output": "5 passed in 0.1s",
                        "exit_code": 0,
                        "status": "completed",
                    },
                },
            ]
        )
        commands, questions = parse_codex_events(raw)
        assert len(commands) == 1
        assert commands[0].argv == ("bash", "-lc", "bash -lc 'uv run pytest'")
        assert commands[0].returncode == 0
        assert "5 passed" in commands[0].stdout_tail
        assert questions == ()

    def test_parse_item_completed_nonzero_exit_is_red(self) -> None:
        raw = _codex_stream(
            [
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_1",
                        "type": "command_execution",
                        "command": "bash -lc 'uv run pytest'",
                        "aggregated_output": "1 failed, 4 passed",
                        "exit_code": 1,
                        "status": "failed",
                    },
                }
            ]
        )
        commands, _ = parse_codex_events(raw)
        assert commands[0].returncode == 1
        assert "1 failed" in commands[0].stdout_tail

    def test_parse_item_completed_command_as_argv_list(self) -> None:
        # Defensive: some builds may carry command as an argv array.
        raw = _codex_stream(
            [
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": ["ls", "-la"],
                        "aggregated_output": "file",
                        "exit_code": 0,
                    },
                }
            ]
        )
        commands, _ = parse_codex_events(raw)
        assert commands[0].argv == ("ls", "-la")

    def test_parse_item_completed_redacts_secrets(self) -> None:
        raw = _codex_stream(
            [
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "env",
                        "aggregated_output": "TOKEN=topsecret42",
                        "exit_code": 0,
                    },
                }
            ]
        )
        commands, _ = parse_codex_events(raw, extra_secrets=("topsecret42",))
        assert "topsecret42" not in commands[0].stdout_tail

    def test_parse_item_completed_agent_message_question(self) -> None:
        raw = _codex_stream(
            [
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": "Which approach?\n- A\n- B\n",
                    },
                }
            ]
        )
        _, questions = parse_codex_events(raw)
        assert len(questions) == 1
        assert questions[0].is_multiple_choice

    def test_parse_item_completed_non_command_item_is_skipped(self) -> None:
        # A non-command, non-message item (e.g. reasoning) yields nothing.
        raw = _codex_stream(
            [{"type": "item.completed", "item": {"type": "reasoning", "text": "..."}}]
        )
        assert parse_codex_events(raw) == ((), ())

    def test_item_completed_nonzero_test_then_commit_is_flagged_red(self) -> None:
        # #387 + verifier spine: a failed test followed by a commit must fire
        # assert_no_commit_while_tests_red once codex results carry the real
        # exit code (previously the whole run parsed to an empty transcript).
        raw = _codex_stream(
            [
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "uv run pytest",
                        "aggregated_output": "1 failed",
                        "exit_code": 1,
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "git commit -m wip",
                        "aggregated_output": "",
                        "exit_code": 0,
                    },
                },
            ]
        )
        commands, _ = parse_codex_events(raw)
        assert [c.returncode for c in commands] == [1, 0]
        run = AgentRun(
            agent_id="codex",
            scenario_id="s1",
            task="t",
            base_branch="main",
            branch_name="codex/x-abcde",
            commands=commands,
        )
        with pytest.raises(VerificationFailure):
            assert_no_commit_while_tests_red(run)


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
