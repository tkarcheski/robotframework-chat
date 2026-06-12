"""Tests for ``rfc dialog import`` — external transcript ingestion (#355).

Covers the pluggable parser registry, the Claude Code JSONL parser
(against a committed synthetic fixture), the importer round-trip into
HarnessDatabase, and the CLI wiring under the existing ``rfc`` entry
point.
"""

import json
from pathlib import Path

import pytest

from rfc.dialog_import import import_transcript
from rfc.dialog_parsers import (
    SUPPORTED_TOOLS,
    UnknownDialogToolError,
    get_parser,
)
from rfc.dialog_parsers.base import DialogParseError
from rfc.dialog_parsers.claude_code import parse_claude_code
from rfc.harness_cli import main
from rfc.harness_db import HarnessDatabase
from rfc.harness_models import AgenticHarness

FIXTURES = Path(__file__).parent / "fixtures" / "dialog_imports"
CLAUDE_CODE_FIXTURE = FIXTURES / "claude_code_basic.jsonl"


@pytest.fixture()
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'h.db'}"


@pytest.fixture()
def db(db_url):
    return HarnessDatabase(database_url=db_url)


class TestParserRegistry:
    def test_claude_code_parser_is_registered(self):
        assert get_parser("claude-code") is parse_claude_code

    def test_unknown_tool_raises_clear_error(self):
        with pytest.raises(UnknownDialogToolError) as excinfo:
            get_parser("cursor")
        message = str(excinfo.value)
        assert "cursor" in message
        for tool in SUPPORTED_TOOLS:
            assert tool in message

    @pytest.mark.parametrize("tool", ["codex", "opencode"])
    def test_stub_parsers_raise_not_implemented(self, tool, tmp_path):
        parser = get_parser(tool)
        with pytest.raises(NotImplementedError, match="PRs welcome"):
            parser(tmp_path / "whatever.jsonl")


class TestClaudeCodeParser:
    def test_parses_fixture_turns(self):
        parsed = parse_claude_code(CLAUDE_CODE_FIXTURE)
        roles = [t.role for t in parsed.turns]
        assert roles == ["user", "assistant", "tool", "assistant"]
        assert [t.turn_number for t in parsed.turns] == [1, 2, 3, 4]
        assert parsed.turns[0].content == "Add a hello function to utils.py"
        assert parsed.turns[0].timestamp == "2026-06-12T05:40:03.559Z"

    def test_assistant_turn_extracts_text_tools_and_usage(self):
        parsed = parse_claude_code(CLAUDE_CODE_FIXTURE)
        turn = parsed.turns[1]
        assert turn.content == "I'll add the function now."
        calls = json.loads(turn.tool_calls_json)
        assert calls[0]["name"] == "Write"
        assert calls[0]["input"]["file_path"] == "utils.py"
        assert turn.prompt_tokens == 8224
        assert turn.completion_tokens == 722

    def test_tool_result_turn(self):
        parsed = parse_claude_code(CLAUDE_CODE_FIXTURE)
        turn = parsed.turns[2]
        assert turn.role == "tool"
        results = json.loads(turn.tool_results_json)
        assert results[0]["tool_use_id"] == "toolu_01"

    def test_sidechain_lines_are_skipped(self):
        parsed = parse_claude_code(CLAUDE_CODE_FIXTURE)
        assert all("sidechain" not in t.content for t in parsed.turns)

    def test_metadata_fingerprinted_from_header(self):
        parsed = parse_claude_code(CLAUDE_CODE_FIXTURE)
        assert parsed.tool_version == "2.1.175"
        assert parsed.model_id == "claude-fable-5"
        assert parsed.started_at == "2026-06-12T05:40:03.559Z"
        assert parsed.ended_at == "2026-06-12T05:40:21.500Z"
        metadata = json.loads(parsed.metadata_json)
        assert metadata["session_id"] == "sess-abc123"
        assert metadata["cwd"] == "/home/dev/project"
        assert metadata["git_branch"] == "main"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(DialogParseError, match="no such transcript"):
            parse_claude_code(tmp_path / "nope.jsonl")

    def test_empty_transcript_raises(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text('{"type":"mode","mode":"normal"}\n')
        with pytest.raises(DialogParseError, match="no dialog turns"):
            parse_claude_code(path)


class TestImportRoundTrip:
    def test_round_trip(self, db, db_url):
        recording_id = import_transcript(
            CLAUDE_CODE_FIXTURE, "claude-code", database_url=db_url
        )
        rec = db.get_recording(recording_id)
        assert rec is not None
        assert rec.source_type == "imported"
        assert rec.tool_name == "claude-code"
        assert rec.tool_version == "2.1.175"
        assert rec.model_id == "claude-fable-5"
        assert rec.session_id == ""
        assert rec.started_at == "2026-06-12T05:40:03.559Z"
        assert rec.ended_at == "2026-06-12T05:40:21.500Z"
        turns = db.get_turns(recording_id)
        assert [t.turn_number for t in turns] == [1, 2, 3, 4]
        assert [t.role for t in turns] == ["user", "assistant", "tool", "assistant"]
        assert all(t.recording_id == recording_id for t in turns)

    def test_cli_flags_fall_back_when_header_lacks_metadata(self, db, db_url, tmp_path):
        path = tmp_path / "bare.jsonl"
        path.write_text(
            json.dumps(
                {
                    "type": "user",
                    "message": {"role": "user", "content": "hi"},
                    "timestamp": "2026-06-12T00:00:00.000Z",
                }
            )
            + "\n"
        )
        recording_id = import_transcript(
            path,
            "claude-code",
            model="llama3:latest",
            tool_version="9.9.9",
            database_url=db_url,
        )
        rec = db.get_recording(recording_id)
        assert rec.model_id == "llama3:latest"
        assert rec.tool_version == "9.9.9"

    def test_session_id_attaches_recording(self, db, db_url):
        db.save_harness(
            AgenticHarness(
                session_id="sess-1",
                tool_name="claude-code",
                started_at="2026-06-12T00:00:00Z",
            )
        )
        recording_id = import_transcript(
            CLAUDE_CODE_FIXTURE, "claude-code", session_id="sess-1", database_url=db_url
        )
        assert db.get_recording(recording_id).session_id == "sess-1"

    def test_unknown_tool_raises(self, db_url):
        with pytest.raises(UnknownDialogToolError):
            import_transcript(CLAUDE_CODE_FIXTURE, "cursor", database_url=db_url)


class TestCli:
    def test_dialog_import_happy_path(self, db, db_url, capsys):
        rc = main(
            [
                "dialog",
                "import",
                str(CLAUDE_CODE_FIXTURE),
                "--tool",
                "claude-code",
                "--database-url",
                db_url,
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "imported" in out
        assert db.get_table_row_count("dialog_recordings") == 1
        assert db.get_table_row_count("dialog_turns") == 4

    def test_missing_database_is_hard_failure(self, capsys, monkeypatch):
        monkeypatch.delenv("DIALOG_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        rc = main(
            ["dialog", "import", str(CLAUDE_CODE_FIXTURE), "--tool", "claude-code"]
        )
        assert rc == 2
        assert "database" in capsys.readouterr().err.lower()

    def test_stub_tool_reports_not_implemented(self, db_url, capsys):
        rc = main(
            [
                "dialog",
                "import",
                str(CLAUDE_CODE_FIXTURE),
                "--tool",
                "codex",
                "--database-url",
                db_url,
            ]
        )
        assert rc == 1
        assert "PRs welcome" in capsys.readouterr().err

    def test_bad_path_reports_parse_error(self, db_url, capsys, tmp_path):
        rc = main(
            [
                "dialog",
                "import",
                str(tmp_path / "missing.jsonl"),
                "--tool",
                "claude-code",
                "--database-url",
                db_url,
            ]
        )
        assert rc == 1
        assert "no such transcript" in capsys.readouterr().err
