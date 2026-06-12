"""Tests for LiveClaudeCodeRunner: drive the Claude Code CLI through a scenario.

The runner shells out to ``claude -p`` against an isolated git worktree and
parses the stream-json transcript into an :class:`AgentRun`. The default
subprocess invoker is the production path; every test here injects a stub
invoker so no real process is spawned.

A single end-to-end test that runs the real ``claude`` CLI lives at the
bottom of the file behind the ``RFC_LIVE_AGENTS=1`` env gate so CI stays
hermetic. Unset the variable to skip it.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from rfc.agent_config import AgentConfig
from rfc.live_agent_runner import (
    ClaudeProcessResult,
    LiveClaudeCodeRunner,
    make_branch_name,
    parse_transcript,
    redact,
)


def _config(**overrides: Any) -> AgentConfig:
    base: dict[str, Any] = {
        "id": "claude-code",
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


def _write_task(tmp_path: Path, scenario_id: str, **fields: Any) -> Path:
    scenario_dir = tmp_path / scenario_id
    scenario_dir.mkdir(parents=True, exist_ok=True)
    task = {
        "scenario_id": scenario_id,
        "task": "Rename DEFAULT_LIMIT to MAX_LIMIT in src/rfc/example.py.",
        "base_branch": "claude-code-staging",
    }
    task.update(fields)
    (scenario_dir / "task.yaml").write_text(yaml.safe_dump(task))
    return scenario_dir / "task.yaml"


@dataclass
class StubInvoker:
    """Test double that returns canned ClaudeProcessResults per command match."""

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


def _stream_json(events: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def _bash_tool_use(tool_id: str, command: str) -> dict[str, Any]:
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


def _tool_result(tool_id: str, text: str, is_error: bool = False) -> dict[str, Any]:
    return {
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


def _assistant_text(text: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }


class TestMakeBranchName:
    def test_starts_with_claude_prefix(self) -> None:
        assert make_branch_name("Rename helper").startswith("claude/")

    def test_strips_punctuation_and_lowercases(self) -> None:
        name = make_branch_name("Rename DEFAULT_LIMIT, please!")
        body = name.removeprefix("claude/")
        # The slug part should be lowercase and dash-separated; followed by -<5 chars>.
        slug, _, suffix = body.rpartition("-")
        assert slug.replace("-", "").islower() or slug == ""
        assert len(suffix) == 5

    def test_suffix_is_five_chars(self) -> None:
        name = make_branch_name("anything")
        suffix = name.rsplit("-", 1)[-1]
        assert len(suffix) == 5


class TestRedact:
    def test_replaces_anthropic_key(self) -> None:
        text = "key=sk-ant-abcdefghij1234567890XYZ trailing"
        out = redact(text)
        assert "sk-ant-" not in out
        assert "[REDACTED]" in out

    def test_replaces_aws_access_key(self) -> None:
        out = redact("AKIAABCDEFGHIJKLMNOP appears here")
        assert "AKIAABCDEFGHIJKLMNOP" not in out

    def test_replaces_github_pat(self) -> None:
        out = redact("token: ghp_" + "a" * 36)
        assert "ghp_" not in out

    def test_replaces_explicit_extra_secret(self) -> None:
        out = redact("hello supersecret123 world", extra_secrets=("supersecret123",))
        assert "supersecret123" not in out
        assert "hello" in out
        assert "world" in out

    def test_empty_string_returns_empty(self) -> None:
        assert redact("") == ""

    def test_ignores_empty_extra_secret(self) -> None:
        out = redact("plain text", extra_secrets=("",))
        assert out == "plain text"


class TestParseTranscript:
    def test_extracts_single_bash_command_with_result(self) -> None:
        events = [
            _bash_tool_use("t1", "uv run pytest"),
            _tool_result("t1", "5 passed in 0.1s"),
        ]
        commands, questions = parse_transcript(_stream_json(events))
        assert len(commands) == 1
        assert commands[0].argv == ("bash", "-lc", "uv run pytest")
        assert commands[0].returncode == 0
        assert "5 passed" in commands[0].stdout_tail
        assert questions == ()

    def test_non_zero_returncode_for_tool_error(self) -> None:
        events = [
            _bash_tool_use("t1", "pytest"),
            _tool_result("t1", "FAILED", is_error=True),
        ]
        commands, _ = parse_transcript(_stream_json(events))
        assert commands[0].returncode == 1

    def test_orders_commands_by_assistant_emission(self) -> None:
        events = [
            _bash_tool_use("t1", "git fetch"),
            _tool_result("t1", "ok"),
            _bash_tool_use("t2", "git checkout -b foo"),
            _tool_result("t2", "ok"),
        ]
        commands, _ = parse_transcript(_stream_json(events))
        assert [c.argv[-1] for c in commands] == ["git fetch", "git checkout -b foo"]

    def test_ignores_non_bash_tool_uses(self) -> None:
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "r1",
                            "name": "Read",
                            "input": {"file_path": "foo.py"},
                        }
                    ]
                },
            },
            _bash_tool_use("t1", "ls"),
            _tool_result("t1", "foo.py"),
        ]
        commands, _ = parse_transcript(_stream_json(events))
        assert len(commands) == 1
        assert commands[0].argv[-1] == "ls"

    def test_extracts_clarifying_question_with_options(self) -> None:
        text = (
            "I have a few questions before I proceed.\n"
            "\n"
            "Which rename strategy do you prefer?\n"
            "  - Inline (rename and update call sites)\n"
            "  - Codemod (write a one-off script)\n"
            "\n"
            "Thanks!"
        )
        events = [_assistant_text(text)]
        _, questions = parse_transcript(_stream_json(events))
        assert len(questions) == 1
        assert questions[0].text.endswith("?")
        assert any("Inline" in o for o in questions[0].options)
        assert any("Codemod" in o for o in questions[0].options)

    def test_skips_non_json_lines(self) -> None:
        stdout = "not json\n" + _stream_json([_bash_tool_use("t1", "ls")])
        commands, _ = parse_transcript(stdout)
        # tool_use without paired result is dropped
        assert commands == ()

    def test_redacts_extra_secrets_in_stdout_tail(self) -> None:
        events = [
            _bash_tool_use("t1", "cat .env"),
            _tool_result("t1", "API_KEY=hunter2-supersecret"),
        ]
        commands, _ = parse_transcript(
            _stream_json(events), extra_secrets=("hunter2-supersecret",)
        )
        assert "hunter2" not in commands[0].stdout_tail
        assert "[REDACTED]" in commands[0].stdout_tail

    def test_empty_transcript_returns_empty_tuples(self) -> None:
        commands, questions = parse_transcript("")
        assert commands == ()
        assert questions == ()


class TestLiveClaudeCodeRunner:
    def test_requires_runner_live(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="live"):
            LiveClaudeCodeRunner(
                config=_config(runner="fake"),
                scenarios_root=tmp_path,
            )

    def test_list_scenarios_uses_task_yaml(self, tmp_path: Path) -> None:
        _write_task(tmp_path, "alpha")
        _write_task(tmp_path, "bravo")
        runner = LiveClaudeCodeRunner(
            config=_config(),
            scenarios_root=tmp_path,
            invoker=StubInvoker(),
        )
        assert runner.list_scenarios() == ["alpha", "bravo"]

    def test_run_returns_agentrun_with_runner_known_fields(
        self, tmp_path: Path
    ) -> None:
        scenarios_root = tmp_path / "scenarios"
        _write_task(scenarios_root, "rename_helper", task="Rename helper.")
        invoker = StubInvoker(
            canned={
                "claude -p": ClaudeProcessResult(
                    returncode=0,
                    stdout=_stream_json(
                        [
                            _bash_tool_use("t1", "uv run pytest"),
                            _tool_result("t1", "5 passed"),
                        ]
                    ),
                    stderr="",
                ),
            }
        )
        runner = LiveClaudeCodeRunner(
            config=_config(),
            scenarios_root=scenarios_root,
            invoker=invoker,
            workspace_root=tmp_path / "ws",
            repo_root=tmp_path / "repo",
        )
        run = runner.run("rename_helper")
        assert run.agent_id == "claude-code"
        assert run.scenario_id == "rename_helper"
        assert run.task == "Rename helper."
        assert run.base_branch == "claude-code-staging"
        assert run.branch_name.startswith("claude/")
        assert len(run.commands) == 1
        assert run.pr is None  # MCP PR-body capture deferred (Issue #288 decision 5c)

    def test_run_creates_worktree_from_base_branch(self, tmp_path: Path) -> None:
        scenarios_root = tmp_path / "scenarios"
        _write_task(scenarios_root, "alpha")
        invoker = StubInvoker()
        runner = LiveClaudeCodeRunner(
            config=_config(),
            scenarios_root=scenarios_root,
            invoker=invoker,
            workspace_root=tmp_path / "ws",
            repo_root=tmp_path / "repo",
        )
        runner.run("alpha")
        worktree_calls = [c for c in invoker.calls if c[0][:2] == ("git", "worktree")]
        assert any("claude-code-staging" in " ".join(c[0]) for c in worktree_calls), (
            "expected git worktree add to reference origin/claude-code-staging"
        )

    def test_run_invokes_claude_with_task_in_workspace(self, tmp_path: Path) -> None:
        scenarios_root = tmp_path / "scenarios"
        _write_task(scenarios_root, "alpha", task="Add a foo function.")
        invoker = StubInvoker()
        runner = LiveClaudeCodeRunner(
            config=_config(),
            scenarios_root=scenarios_root,
            invoker=invoker,
            workspace_root=tmp_path / "ws",
            repo_root=tmp_path / "repo",
        )
        runner.run("alpha")
        claude_calls = [c for c in invoker.calls if c[0][0].endswith("claude")]
        assert claude_calls, "expected at least one claude invocation"
        argv, cwd, _, timeout = claude_calls[0]
        assert "-p" in argv
        assert "Add a foo function." in argv
        assert "stream-json" in " ".join(argv)
        assert str(cwd).endswith("alpha")
        assert timeout == 600

    def test_run_attaches_final_changed_paths_to_last_command(
        self, tmp_path: Path
    ) -> None:
        scenarios_root = tmp_path / "scenarios"
        _write_task(scenarios_root, "alpha")
        invoker = StubInvoker(
            canned={
                "claude -p": ClaudeProcessResult(
                    returncode=0,
                    stdout=_stream_json(
                        [
                            _bash_tool_use("t1", "uv run pytest"),
                            _tool_result("t1", "ok"),
                        ]
                    ),
                    stderr="",
                ),
                "status --porcelain": ClaudeProcessResult(
                    returncode=0,
                    stdout=" M src/rfc/example.py\n?? tests/new.py\n",
                    stderr="",
                ),
            }
        )
        runner = LiveClaudeCodeRunner(
            config=_config(),
            scenarios_root=scenarios_root,
            invoker=invoker,
            workspace_root=tmp_path / "ws",
            repo_root=tmp_path / "repo",
        )
        run = runner.run("alpha")
        assert "src/rfc/example.py" in run.commands[-1].changed_paths_after
        assert "tests/new.py" in run.commands[-1].changed_paths_after

    def test_run_collects_commits_from_git_log(self, tmp_path: Path) -> None:
        scenarios_root = tmp_path / "scenarios"
        _write_task(scenarios_root, "alpha")
        log_out = "aaa111\x1ftest: add failing test\x1fcovers happy path\x1e\nbbb222\x1ffeat: implement helper\x1f\x1e\n"
        invoker = StubInvoker(
            canned={
                "git log": ClaudeProcessResult(
                    returncode=0,
                    stdout=log_out,
                    stderr="",
                ),
                "git show": ClaudeProcessResult(
                    returncode=0,
                    stdout="src/rfc/example.py\n",
                    stderr="",
                ),
            }
        )
        runner = LiveClaudeCodeRunner(
            config=_config(),
            scenarios_root=scenarios_root,
            invoker=invoker,
            workspace_root=tmp_path / "ws",
            repo_root=tmp_path / "repo",
        )
        run = runner.run("alpha")
        subjects = [c.subject for c in run.commits]
        assert "test: add failing test" in subjects
        assert "feat: implement helper" in subjects

    def test_run_redacts_env_secrets_from_command_tails(self, tmp_path: Path) -> None:
        scenarios_root = tmp_path / "scenarios"
        _write_task(scenarios_root, "alpha")
        env_file = tmp_path / ".env"
        env_file.write_text("API_KEY=hunter2-very-secret\nOTHER=plain\n")
        invoker = StubInvoker(
            canned={
                "claude -p": ClaudeProcessResult(
                    returncode=0,
                    stdout=_stream_json(
                        [
                            _bash_tool_use("t1", "env"),
                            _tool_result(
                                "t1", "API_KEY=hunter2-very-secret\nPATH=/bin"
                            ),
                        ]
                    ),
                    stderr="",
                ),
            }
        )
        runner = LiveClaudeCodeRunner(
            config=_config(),
            scenarios_root=scenarios_root,
            invoker=invoker,
            workspace_root=tmp_path / "ws",
            repo_root=tmp_path / "repo",
            env_file=env_file,
        )
        run = runner.run("alpha")
        assert "hunter2" not in run.commands[0].stdout_tail
        assert "[REDACTED]" in run.commands[0].stdout_tail

    def test_unknown_scenario_raises_keyerror(self, tmp_path: Path) -> None:
        scenarios_root = tmp_path / "scenarios"
        scenarios_root.mkdir()
        runner = LiveClaudeCodeRunner(
            config=_config(),
            scenarios_root=scenarios_root,
            invoker=StubInvoker(),
        )
        with pytest.raises(KeyError, match="alpha"):
            runner.run("alpha")

    def test_factory_dispatch_returns_live_runner(self, tmp_path: Path) -> None:
        from rfc.agent_runner import create_agent_runner

        runner = create_agent_runner(_config(), scenarios_root=tmp_path)
        assert isinstance(runner, LiveClaudeCodeRunner)


@pytest.mark.skipif(
    os.getenv("RFC_LIVE_AGENTS") != "1",
    reason="RFC_LIVE_AGENTS=1 not set; skipping real Claude Code CLI test",
)
class TestLiveClaudeCodeRunnerEnd2End:
    """Real `claude -p` against a trivial scenario. Gated by RFC_LIVE_AGENTS=1.

    Only runs when the operator explicitly opts in. The Claude Code CLI must
    be on PATH and authenticated. This test will hit the real API and
    spend (small) credits -- intentional, since this is the only way to
    catch breakage in the production subprocess path.
    """

    def test_real_claude_cli_against_echo_scenario(self, tmp_path: Path) -> None:
        if shutil.which("claude") is None:
            pytest.skip("claude CLI not on PATH")
        scenarios_root = tmp_path / "scenarios"
        _write_task(
            scenarios_root,
            "smoke",
            task="Print the string 'hello-rfc' and exit. Do not change any files.",
        )
        runner = LiveClaudeCodeRunner(
            config=_config(timeout_seconds=120),
            scenarios_root=scenarios_root,
            workspace_root=tmp_path / "ws",
        )
        run = runner.run("smoke")
        assert run.agent_id == "claude-code"
        assert run.scenario_id == "smoke"
        assert run.branch_name.startswith("claude/")
