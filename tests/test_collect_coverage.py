"""Tests for scripts/collect_coverage.py — parse pytest-cov JSON and insert to DB."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from scripts.collect_coverage import parse_coverage_json, insert_coverage_rows


@pytest.fixture()
def coverage_db(tmp_path: Path) -> str:
    """SQLite database with coverage_reports table."""
    db_path = tmp_path / "cov.db"
    uri = f"sqlite:///{db_path}"
    engine = create_engine(uri)
    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE coverage_reports (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                git_commit TEXT NOT NULL DEFAULT '',
                git_branch TEXT NOT NULL DEFAULT '',
                hostname TEXT NOT NULL DEFAULT '',
                rfc_version TEXT NOT NULL DEFAULT '',
                total_statements INTEGER NOT NULL DEFAULT 0,
                total_missed INTEGER NOT NULL DEFAULT 0,
                total_covered INTEGER NOT NULL DEFAULT 0,
                coverage_pct REAL NOT NULL DEFAULT 0.0,
                module_name TEXT NOT NULL DEFAULT '',
                module_statements INTEGER NOT NULL DEFAULT 0,
                module_missed INTEGER NOT NULL DEFAULT 0,
                module_covered INTEGER NOT NULL DEFAULT 0,
                module_coverage_pct REAL NOT NULL DEFAULT 0.0
            )
        """)
        )
    engine.dispose()
    return uri


@pytest.fixture()
def sample_coverage_json(tmp_path: Path) -> Path:
    """Create a sample coverage.json file."""
    data = {
        "meta": {
            "version": "7.0",
            "timestamp": "2026-03-18T12:00:00",
            "branch_coverage": False,
            "show_contexts": False,
        },
        "files": {
            "src/rfc/ollama.py": {
                "executed_lines": [1, 2, 3, 4, 5, 10, 20, 30, 40, 50],
                "summary": {
                    "covered_lines": 10,
                    "num_statements": 15,
                    "percent_covered": 66.667,
                    "missing_lines": 5,
                    "excluded_lines": 0,
                },
                "missing_lines": [6, 7, 8, 9, 11],
                "excluded_lines": [],
            },
            "src/rfc/keywords.py": {
                "executed_lines": [1, 2, 3],
                "summary": {
                    "covered_lines": 3,
                    "num_statements": 5,
                    "percent_covered": 60.0,
                    "missing_lines": 2,
                    "excluded_lines": 0,
                },
                "missing_lines": [4, 5],
                "excluded_lines": [],
            },
        },
        "totals": {
            "covered_lines": 13,
            "num_statements": 20,
            "percent_covered": 65.0,
            "missing_lines": 7,
            "excluded_lines": 0,
        },
    }
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(data))
    return path


class TestParseCoverageJson:
    """Tests for parse_coverage_json."""

    def test_returns_summary_and_modules(self, sample_coverage_json: Path) -> None:
        """parse_coverage_json returns summary dict and module list."""
        summary, modules = parse_coverage_json(sample_coverage_json)
        assert isinstance(summary, dict)
        assert isinstance(modules, list)

    def test_summary_has_coverage_fields(self, sample_coverage_json: Path) -> None:
        """Summary contains total_statements, total_covered, coverage_pct."""
        summary, _ = parse_coverage_json(sample_coverage_json)
        assert summary["total_statements"] == 20
        assert summary["total_covered"] == 13
        assert summary["total_missed"] == 7
        assert abs(summary["coverage_pct"] - 65.0) < 0.1

    def test_modules_list_has_entries(self, sample_coverage_json: Path) -> None:
        """Modules list has one entry per file."""
        _, modules = parse_coverage_json(sample_coverage_json)
        assert len(modules) == 2
        names = {m["module_name"] for m in modules}
        assert "src/rfc/ollama.py" in names
        assert "src/rfc/keywords.py" in names

    def test_module_entry_has_coverage_fields(
        self, sample_coverage_json: Path
    ) -> None:
        """Each module entry has statement counts and coverage percent."""
        _, modules = parse_coverage_json(sample_coverage_json)
        for m in modules:
            assert "module_statements" in m
            assert "module_covered" in m
            assert "module_missed" in m
            assert "module_coverage_pct" in m

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            parse_coverage_json(tmp_path / "nonexistent.json")


class TestInsertCoverageRows:
    """Tests for insert_coverage_rows."""

    def test_inserts_summary_row(
        self, coverage_db: str, sample_coverage_json: Path
    ) -> None:
        """Inserts a summary row with module_name=''."""
        summary, modules = parse_coverage_json(sample_coverage_json)
        insert_coverage_rows(
            database_url=coverage_db,
            summary=summary,
            modules=modules,
            git_commit="abc123",
            git_branch="main",
            hostname="test-host",
            rfc_version="1.3.2",
        )
        engine = create_engine(coverage_db)
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM coverage_reports WHERE module_name = ''")
            )
            rows = result.fetchall()
        engine.dispose()
        assert len(rows) == 1
        # Check summary values
        row = rows[0]
        assert row._mapping["total_statements"] == 20
        assert row._mapping["coverage_pct"] == pytest.approx(65.0, abs=0.1)

    def test_inserts_module_rows(
        self, coverage_db: str, sample_coverage_json: Path
    ) -> None:
        """Inserts one row per module."""
        summary, modules = parse_coverage_json(sample_coverage_json)
        insert_coverage_rows(
            database_url=coverage_db,
            summary=summary,
            modules=modules,
            git_commit="abc123",
            git_branch="main",
            hostname="test-host",
            rfc_version="1.3.2",
        )
        engine = create_engine(coverage_db)
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM coverage_reports WHERE module_name != ''")
            )
            rows = result.fetchall()
        engine.dispose()
        assert len(rows) == 2

    def test_git_metadata_stored(
        self, coverage_db: str, sample_coverage_json: Path
    ) -> None:
        """Git commit and branch are stored in every row."""
        summary, modules = parse_coverage_json(sample_coverage_json)
        insert_coverage_rows(
            database_url=coverage_db,
            summary=summary,
            modules=modules,
            git_commit="deadbeef",
            git_branch="feature/x",
            hostname="my-host",
            rfc_version="1.3.2",
        )
        engine = create_engine(coverage_db)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT * FROM coverage_reports"))
            rows = result.fetchall()
        engine.dispose()
        for row in rows:
            assert row._mapping["git_commit"] == "deadbeef"
            assert row._mapping["git_branch"] == "feature/x"
            assert row._mapping["hostname"] == "my-host"
