"""Tests for rfc.agent_run normalized run artifact."""

from pathlib import Path

import pytest
import yaml

from rfc.agent_run import AgentCommand, AgentQuestion, AgentRun, load_agent_run


class TestAgentRunFromYaml:
    def test_loads_minimal_run(self, tmp_path: Path) -> None:
        payload = {
            "agent_id": "claude-code",
            "scenario_id": "startup_contract",
            "task": "Do a thing.",
            "base_branch": "claude-code-staging",
            "branch_name": "claude/do-thing-ab123",
            "commands": [],
            "questions": [],
            "commits": [],
        }
        run_file = tmp_path / "run.yaml"
        run_file.write_text(yaml.safe_dump(payload))

        run = load_agent_run(run_file)
        assert run.agent_id == "claude-code"
        assert run.scenario_id == "startup_contract"
        assert run.branch_name == "claude/do-thing-ab123"
        assert run.commands == ()
        assert run.questions == ()
        assert run.commits == ()
        assert run.pr is None

    def test_loads_commands_in_order(self, tmp_path: Path) -> None:
        payload = {
            "agent_id": "claude-code",
            "scenario_id": "x",
            "task": "x",
            "base_branch": "claude-code-staging",
            "branch_name": "claude/x-ab123",
            "commands": [
                {
                    "argv": ["git", "fetch", "origin", "claude-code-staging"],
                    "returncode": 0,
                },
                {"argv": ["uv", "run", "pytest"], "returncode": 0},
            ],
            "questions": [],
            "commits": [],
        }
        run_file = tmp_path / "run.yaml"
        run_file.write_text(yaml.safe_dump(payload))

        run = load_agent_run(run_file)
        assert len(run.commands) == 2
        assert run.commands[0].argv == ("git", "fetch", "origin", "claude-code-staging")
        assert run.commands[1].argv == ("uv", "run", "pytest")

    def test_command_has_default_return_code_zero(self) -> None:
        cmd = AgentCommand(argv=("echo", "hi"))
        assert cmd.returncode == 0

    def test_command_joined_matches_shell_form(self) -> None:
        cmd = AgentCommand(argv=("uv", "run", "pytest"))
        assert cmd.joined() == "uv run pytest"

    def test_command_joined_handles_shell_wrapper(self) -> None:
        """A bash -lc "A && B" wrapper should expose both sub-commands."""
        cmd = AgentCommand(
            argv=("bash", "-lc", "uv run pytest && pre-commit run --all-files")
        )
        parts = cmd.shell_subcommands()
        assert "uv run pytest" in parts
        assert "pre-commit run --all-files" in parts

    def test_command_shell_subcommands_returns_whole_when_not_wrapped(self) -> None:
        cmd = AgentCommand(argv=("uv", "run", "pytest"))
        assert cmd.shell_subcommands() == ("uv run pytest",)

    def test_background_ampersand_splits_into_subcommands(self) -> None:
        """A single ``&`` backgrounds the preceding command and is a list
        separator (Bash manual: an ``&``-terminated command runs asynchronously
        and returns 0). It must split like ``;`` so the verifier sees the
        backgrounded test and the following commit as separate subcommands —
        not one opaque blob that hides an ungated commit (#503 round 8)."""
        cmd = AgentCommand(argv=("bash", "-lc", "uv run pytest & git commit -m x"))
        assert cmd.shell_subcommands() == ("uv run pytest", "git commit -m x")

    def test_trailing_background_ampersand_yields_single_subcommand(self) -> None:
        cmd = AgentCommand(argv=("bash", "-lc", "uv run pytest &"))
        assert cmd.shell_subcommands() == ("uv run pytest",)

    def test_double_ampersand_not_split_by_background_rule(self) -> None:
        """``&&`` must remain a single AND operator, never two background
        separators — the ``&&`` alternative has to precede the bare ``&``."""
        cmd = AgentCommand(argv=("bash", "-lc", "uv run pytest && git commit -m x"))
        pairs = cmd.shell_subcommands_with_operators()
        assert pairs == ((None, "uv run pytest"), ("&&", "git commit -m x"))

    def test_loads_commits(self, tmp_path: Path) -> None:
        payload = {
            "agent_id": "claude-code",
            "scenario_id": "tdd",
            "task": "x",
            "base_branch": "claude-code-staging",
            "branch_name": "claude/x-ab123",
            "commands": [],
            "questions": [],
            "commits": [
                {
                    "sha": "a1b2c3",
                    "subject": "test: add failing parser spec",
                    "files_changed": ["tests/test_parser.py"],
                },
                {
                    "sha": "d4e5f6",
                    "subject": "feat: implement parser",
                    "files_changed": ["src/rfc/parser.py"],
                },
            ],
        }
        run_file = tmp_path / "run.yaml"
        run_file.write_text(yaml.safe_dump(payload))

        run = load_agent_run(run_file)
        assert [c.subject for c in run.commits] == [
            "test: add failing parser spec",
            "feat: implement parser",
        ]
        assert run.commits[0].files_changed == ("tests/test_parser.py",)

    def test_loads_questions(self, tmp_path: Path) -> None:
        payload = {
            "agent_id": "claude-code",
            "scenario_id": "ambiguous",
            "task": "x",
            "base_branch": "claude-code-staging",
            "branch_name": "claude/x-ab123",
            "commands": [],
            "questions": [
                {
                    "text": "Should X go in module A or B?",
                    "options": ["a) module A", "b) module B", "c) new file"],
                },
            ],
            "commits": [],
        }
        run_file = tmp_path / "run.yaml"
        run_file.write_text(yaml.safe_dump(payload))

        run = load_agent_run(run_file)
        assert len(run.questions) == 1
        assert run.questions[0].text.startswith("Should X")
        assert run.questions[0].is_multiple_choice

    def test_question_without_options_is_not_multiple_choice(self) -> None:
        q = AgentQuestion(text="Should I do X?", options=())
        assert not q.is_multiple_choice

    def test_question_with_single_option_is_not_multiple_choice(self) -> None:
        q = AgentQuestion(text="Foo?", options=("a) only choice",))
        assert not q.is_multiple_choice

    def test_first_source_change_index(self) -> None:
        run = AgentRun(
            agent_id="claude-code",
            scenario_id="tdd",
            task="x",
            base_branch="claude-code-staging",
            branch_name="claude/x-ab123",
            commands=(
                AgentCommand(argv=("git", "fetch")),
                AgentCommand(argv=("uv", "run", "pytest"), changed_paths_after=()),
                AgentCommand(
                    argv=("sh", "-c", "write test"),
                    changed_paths_after=("tests/test_parser.py",),
                ),
                AgentCommand(argv=("uv", "run", "pytest"), returncode=1),
                AgentCommand(
                    argv=("sh", "-c", "write src"),
                    changed_paths_after=("src/rfc/parser.py",),
                ),
                AgentCommand(argv=("uv", "run", "pytest"), returncode=0),
            ),
        )
        assert run.first_change_under("tests/") == 2
        assert run.first_change_under("src/") == 4

    def test_first_change_under_returns_none_when_absent(self) -> None:
        run = AgentRun(
            agent_id="claude-code",
            scenario_id="x",
            task="x",
            base_branch="claude-code-staging",
            branch_name="claude/x-ab123",
            commands=(AgentCommand(argv=("git", "fetch")),),
        )
        assert run.first_change_under("tests/") is None

    def test_missing_required_keys_raises(self, tmp_path: Path) -> None:
        run_file = tmp_path / "run.yaml"
        run_file.write_text(yaml.safe_dump({"agent_id": "x"}))
        with pytest.raises(ValueError, match="missing keys"):
            load_agent_run(run_file)
