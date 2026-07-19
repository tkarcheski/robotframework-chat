"""Adversarial coverage for rfc.harness_adapters (test-design, Issue #172).

These tests attack the untrusted-subprocess-output surface the engineering
suite (test_harness_adapters.py) does not yet exercise:

  * The codex path *through the real probe + real subprocess seam* -- a throwaway
    ``codex`` shim on PATH lets ``CodexAdapter.probe()`` return True and drives
    its canned ``exec --json`` stream through the actual ``_default_invoker``,
    not a stub.
  * Parser robustness: malformed / non-dict parts, missing fields the CLIs may
    omit, unpaired codex begin/end events, interleaved call pairing, and
    ``_tail`` truncation of oversized output.
  * ``exit_code`` coercion in the codex parser (#200): a non-int / unparseable
    shape biases toward failure rather than being silently recorded green.

All deterministic and CI-safe; the one subprocess test shells out only to a
shim written into ``tmp_path``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from rfc.harness_adapters import (
    _TAIL_LIMIT,
    CodexAdapter,
    _default_invoker,
    parse_codex_events,
    parse_opencode_events,
)

# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


# Sentinel distinguishing "exit_code key absent" from "exit_code is None".
_MISSING = object()


def _stream(events: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def _oc_bash(
    call_id: str, command: Any, *, status: str = "completed", **state_extra: Any
) -> dict[str, Any]:
    state: dict[str, Any] = {"status": status, "input": {"command": command}}
    state.update(state_extra)
    return {
        "type": "tool_use",
        "part": {"type": "tool", "tool": "bash", "callID": call_id, "state": state},
    }


# ---------------------------------------------------------------------------
# Probe-gating honesty: codex through the real probe + real subprocess seam.
# ---------------------------------------------------------------------------


def _write_fake_codex(directory: Path) -> Path:
    """A minimal ``codex`` shim: answers ``--version`` and emits an exec stream."""
    shim = directory / "codex"
    begin = json.dumps(
        {
            "msg": {
                "type": "exec_command_begin",
                "call_id": "c1",
                "command": ["bash", "-lc", "uv run pytest"],
            }
        }
    )
    end = json.dumps(
        {
            "msg": {
                "type": "exec_command_end",
                "call_id": "c1",
                "stdout": "3 passed",
                "stderr": "",
                "exit_code": 0,
            }
        }
    )
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "--version" ]; then echo "codex 0.0.0-fake"; exit 0; fi\n'
        'if [ "$1" = "exec" ]; then\n'
        f"  printf '%s\\n' '{begin}'\n"
        f"  printf '%s\\n' '{end}'\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    shim.chmod(0o755)
    return shim


class TestCodexProbeGatingHonesty:
    def test_probe_true_for_explicit_shim_path(self, tmp_path: Path) -> None:
        shim = _write_fake_codex(tmp_path)
        assert CodexAdapter(codex_bin=str(shim)).probe() is True

    def test_probe_true_when_shim_resolved_via_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_fake_codex(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
        # Default codex_bin='codex' must now resolve to the shim on PATH.
        assert CodexAdapter().probe() is True

    def test_end_to_end_through_default_invoker(self, tmp_path: Path) -> None:
        """Run the shim as a REAL subprocess via the production invoker, parse it.

        Exercises build_argv -> _default_invoker (real subprocess) ->
        parse_output on genuine process stdout -- the codex path the absent CLI
        normally blocks.
        """
        shim = _write_fake_codex(tmp_path)
        adapter = CodexAdapter(codex_bin=str(shim))
        assert adapter.probe() is True
        argv = tuple(adapter.build_argv("run the tests", tmp_path))
        result = _default_invoker(argv, tmp_path, adapter.env_overrides(), 30)
        assert result.returncode == 0
        commands, questions = adapter.parse_output(result.stdout)
        assert len(commands) == 1
        assert commands[0].argv == ("bash", "-lc", "uv run pytest")
        assert commands[0].returncode == 0
        assert "3 passed" in commands[0].stdout_tail
        assert questions == ()


# ---------------------------------------------------------------------------
# opencode parser robustness.
# ---------------------------------------------------------------------------


class TestOpenCodeParserRobustness:
    def test_non_dict_part_is_skipped(self) -> None:
        raw = _stream([{"type": "tool_use", "part": "oops-a-string"}])
        assert parse_opencode_events(raw) == ((), ())

    def test_missing_part_key_is_skipped(self) -> None:
        raw = _stream([{"type": "tool_use", "timestamp": 1}])
        assert parse_opencode_events(raw) == ((), ())

    def test_command_none_is_skipped(self) -> None:
        raw = _stream([_oc_bash("c1", None)])
        assert parse_opencode_events(raw) == ((), ())

    def test_command_non_string_is_skipped(self) -> None:
        raw = _stream([_oc_bash("c1", ["not", "a", "string"])])
        assert parse_opencode_events(raw) == ((), ())

    def test_completed_without_output_field_yields_empty_tail(self) -> None:
        # A completed bash part with no 'output' key must still be one command.
        raw = _stream([_oc_bash("c1", "true", status="completed")])
        commands, _ = parse_opencode_events(raw)
        assert len(commands) == 1
        assert commands[0].returncode == 0
        assert commands[0].stdout_tail == ""

    def test_truncated_json_line_is_skipped_not_fatal(self) -> None:
        good = _stream([_oc_bash("c1", "ls", output="ok")])
        raw = good + '{"type": "tool_use", "part": {"type": "too'  # truncated
        commands, _ = parse_opencode_events(raw)
        assert len(commands) == 1

    def test_oversized_output_is_tail_truncated(self) -> None:
        big = "x" * (_TAIL_LIMIT + 500)
        raw = _stream([_oc_bash("c1", "cat big", output=big)])
        commands, _ = parse_opencode_events(raw)
        assert len(commands[0].stdout_tail) == _TAIL_LIMIT
        assert commands[0].stdout_tail == big[-_TAIL_LIMIT:]


# ---------------------------------------------------------------------------
# codex parser robustness.
# ---------------------------------------------------------------------------


class TestCodexParserRobustness:
    def test_end_without_begin_is_skipped(self) -> None:
        raw = _stream(
            [
                {
                    "msg": {
                        "type": "exec_command_end",
                        "call_id": "orphan",
                        "stdout": "hi",
                        "exit_code": 0,
                    }
                }
            ]
        )
        assert parse_codex_events(raw) == ((), ())

    def test_interleaved_calls_pair_by_call_id(self) -> None:
        raw = _stream(
            [
                {
                    "msg": {
                        "type": "exec_command_begin",
                        "call_id": "a",
                        "command": ["bash", "-lc", "first"],
                    }
                },
                {
                    "msg": {
                        "type": "exec_command_begin",
                        "call_id": "b",
                        "command": ["bash", "-lc", "second"],
                    }
                },
                {
                    "msg": {
                        "type": "exec_command_end",
                        "call_id": "b",
                        "stdout": "2",
                        "exit_code": 0,
                    }
                },
                {
                    "msg": {
                        "type": "exec_command_end",
                        "call_id": "a",
                        "stdout": "1",
                        "exit_code": 0,
                    }
                },
            ]
        )
        commands, _ = parse_codex_events(raw)
        # Completion order drives emission order; pairing is by call_id.
        assert [c.argv[-1] for c in commands] == ["second", "first"]
        assert [c.stdout_tail for c in commands] == ["2", "1"]

    def test_oversized_stdout_and_stderr_are_tail_truncated(self) -> None:
        big = "y" * (_TAIL_LIMIT + 123)
        raw = _stream(
            [
                {
                    "msg": {
                        "type": "exec_command_begin",
                        "call_id": "c1",
                        "command": ["bash", "-lc", "noisy"],
                    }
                },
                {
                    "msg": {
                        "type": "exec_command_end",
                        "call_id": "c1",
                        "stdout": big,
                        "stderr": big,
                        "exit_code": 0,
                    }
                },
            ]
        )
        commands, _ = parse_codex_events(raw)
        assert len(commands[0].stdout_tail) == _TAIL_LIMIT
        assert len(commands[0].stderr_tail) == _TAIL_LIMIT

    def test_empty_command_array_begin_is_ignored(self) -> None:
        # An empty command array yields no pending entry, so its end is a no-op.
        raw = _stream(
            [
                {"msg": {"type": "exec_command_begin", "call_id": "c1", "command": []}},
                {
                    "msg": {
                        "type": "exec_command_end",
                        "call_id": "c1",
                        "stdout": "x",
                        "exit_code": 0,
                    }
                },
            ]
        )
        assert parse_codex_events(raw) == ((), ())

    @staticmethod
    def _end_event(exit_code: object) -> str:
        """A codex begin/end pair for one ``pytest`` command with ``exit_code``."""
        end: dict[str, Any] = {
            "type": "exec_command_end",
            "call_id": "c1",
            "stdout": "",
            "stderr": "1 failed",
        }
        # Omit the key entirely for the sentinel; otherwise carry the value.
        if exit_code is not _MISSING:
            end["exit_code"] = exit_code
        return _stream(
            [
                {
                    "msg": {
                        "type": "exec_command_begin",
                        "call_id": "c1",
                        "command": ["bash", "-lc", "pytest"],
                    }
                },
                {"msg": end},
            ]
        )

    def test_string_exit_code_is_coerced_not_silently_green(self) -> None:
        """#200: a stringified nonzero exit is RED, not silently green.

        Inverts the former ``..._KNOWN_RISK`` characterization: a failed codex
        command whose ``exit_code`` arrives as ``"1"`` must record a non-zero
        ``returncode`` so ``assert_no_commit_while_tests_red`` still fires. The
        safety-critical direction is green-when-red, so this asserts the fix.
        """
        commands, _ = parse_codex_events(self._end_event("1"))
        assert commands[0].returncode == 1

    def test_string_zero_exit_code_stays_green(self) -> None:
        # A genuine, parseable "0" is a real success and must stay green.
        commands, _ = parse_codex_events(self._end_event("0"))
        assert commands[0].returncode == 0

    def test_bool_exit_code_biases_to_failure(self) -> None:
        # bool is an int subclass; False must NOT normalize to 0 (green).
        for value in (True, False):
            commands, _ = parse_codex_events(self._end_event(value))
            assert commands[0].returncode == 1

    def test_nonnumeric_string_exit_code_biases_to_failure(self) -> None:
        commands, _ = parse_codex_events(self._end_event("boom"))
        assert commands[0].returncode == 1

    def test_null_exit_code_biases_to_failure(self) -> None:
        # codex-cli 0.144.5 emits exit_code=null on a non-terminal item; if a
        # terminal event ever carries null (e.g. a killed command), record RED.
        commands, _ = parse_codex_events(self._end_event(None))
        assert commands[0].returncode == 1

    def test_missing_exit_code_biases_to_failure(self) -> None:
        commands, _ = parse_codex_events(self._end_event(_MISSING))
        assert commands[0].returncode == 1

    def test_item_completed_string_exit_code_is_coerced_not_green(self) -> None:
        # Same coercion on the current (#200 live-confirmed) item.completed path.
        raw = _stream(
            [
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "uv run pytest",
                        "aggregated_output": "1 failed",
                        "exit_code": "1",
                    },
                }
            ]
        )
        commands, _ = parse_codex_events(raw)
        assert commands[0].returncode == 1

    def test_item_completed_live_nonzero_int_exit_is_red(self) -> None:
        # Exact shape captured live from codex-cli 0.144.5 (#200): a failed
        # command_execution carries an int exit_code and status "failed".
        raw = _stream(
            [
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_1",
                        "type": "command_execution",
                        "command": "/bin/bash -c \"sh -c 'echo boom; exit 3'\"",
                        "aggregated_output": "boom\n",
                        "exit_code": 3,
                        "status": "failed",
                    },
                }
            ]
        )
        commands, _ = parse_codex_events(raw)
        assert commands[0].returncode == 3
