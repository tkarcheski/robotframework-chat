"""Tests for check_rfc_index.py — RFC numbering guard (issue #40).

The guard turns the reservation convention in modules/rfcs/README.md from an
advisory prompt rule into a mechanical check ("prompts request, checks enforce"
— GIT.md). It fails a PR when:

  1. two RFC *files* claim the same RFC number (a collision),
  2. an RFC file's number is missing from the index table, or
  3. the index table itself lists the same number twice.

These tests exercise the pure logic (rfc_number_from_filename, parse_*,
evaluate) with no filesystem or git dependency, plus a small end-to-end pass
over a temp modules/rfcs/ tree.

Run:  python -m pytest modules/ops/scripts/test_check_rfc_index.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

from check_rfc_index import (
    IndexEntry,
    RfcFile,
    evaluate,
    parse_index_numbers,
    rfc_files_in,
    rfc_number_from_filename,
    scan_rfc_dir,
)


# --- filename parsing ------------------------------------------------------


class TestRfcNumberFromFilename:
    def test_extracts_zero_padded_number(self) -> None:
        assert rfc_number_from_filename("RFC-003-nv-cache-storage.md") == 3

    def test_extracts_three_digit_number(self) -> None:
        assert rfc_number_from_filename("RFC-042-something.md") == 42

    def test_ignores_non_rfc_files(self) -> None:
        assert rfc_number_from_filename("README.md") is None
        assert rfc_number_from_filename("module.toml") is None
        assert rfc_number_from_filename(".gitkeep") is None

    def test_requires_title_slug_after_number(self) -> None:
        # A bare "RFC-003.md" with no descriptive slug is not the convention.
        assert rfc_number_from_filename("RFC-003.md") is None

    def test_case_insensitive_prefix(self) -> None:
        assert rfc_number_from_filename("rfc-007-lower.md") == 7


# --- index table parsing ---------------------------------------------------


class TestParseIndexNumbers:
    def test_parses_pipe_table_rows(self) -> None:
        text = (
            "| # | Title | Status |\n"
            "|---|---|---|\n"
            "| RFC-001 | Monorepo | Draft |\n"
            "| RFC-002 | API | Draft |\n"
        )
        assert parse_index_numbers(text) == [
            IndexEntry(number=1, raw="RFC-001"),
            IndexEntry(number=2, raw="RFC-002"),
        ]

    def test_accepts_bare_number_cell(self) -> None:
        text = "| # | Title |\n|---|---|\n| 5 | Five |\n"
        assert parse_index_numbers(text) == [IndexEntry(number=5, raw="5")]

    def test_skips_separator_and_header_rows(self) -> None:
        text = "| # | Title |\n|---|---|\n| RFC-001 | One |\n"
        nums = [e.number for e in parse_index_numbers(text)]
        assert nums == [1]

    def test_ignores_prose_mentions_outside_table(self) -> None:
        # An "RFC-009" referenced in a sentence must not count as an entry.
        text = (
            "Reserving RFC-009 is done by editing this file.\n\n"
            "| # | Title |\n|---|---|\n| RFC-001 | One |\n"
        )
        assert [e.number for e in parse_index_numbers(text)] == [1]


# --- core evaluation -------------------------------------------------------


def _files(*nums: int) -> list[RfcFile]:
    return [RfcFile(number=n, filename=f"RFC-{n:03d}-x.md") for n in nums]


def _index(*nums: int) -> list[IndexEntry]:
    return [IndexEntry(number=n, raw=f"RFC-{n:03d}") for n in nums]


class TestEvaluate:
    def test_clean_state_passes(self) -> None:
        assert evaluate(_files(1, 2, 3), _index(1, 2, 3)) == []

    def test_duplicate_file_number_fails(self) -> None:
        files = [
            RfcFile(number=6, filename="RFC-006-a.md"),
            RfcFile(number=6, filename="RFC-006-b.md"),
        ]
        violations = evaluate(files, _index(6))
        assert len(violations) == 1
        assert "006" in violations[0]
        assert "RFC-006-a.md" in violations[0] and "RFC-006-b.md" in violations[0]
        assert "duplicate" in violations[0].lower()

    def test_file_missing_from_index_fails(self) -> None:
        violations = evaluate(_files(1, 2), _index(1))
        assert len(violations) == 1
        assert "RFC-002-x.md" in violations[0]
        assert "index" in violations[0].lower()

    def test_duplicate_index_entry_fails(self) -> None:
        violations = evaluate(_files(1), _index(1, 1))
        assert len(violations) == 1
        assert "001" in violations[0]
        assert "index" in violations[0].lower()

    def test_index_entry_without_file_is_allowed(self) -> None:
        # A reserved-but-not-yet-written number (e.g. RFC-005 on a side branch)
        # legitimately appears in the index with no file on this branch.
        assert evaluate(_files(1), _index(1, 5)) == []

    def test_reports_every_independent_problem(self) -> None:
        files = [
            RfcFile(number=2, filename="RFC-002-a.md"),
            RfcFile(number=2, filename="RFC-002-b.md"),  # duplicate
            RfcFile(number=3, filename="RFC-003-x.md"),  # missing from index
        ]
        violations = evaluate(files, _index(2))
        assert len(violations) == 2


# --- filesystem layer ------------------------------------------------------


class TestScanRfcDir:
    def test_scan_reads_files_and_index(self, tmp_path: Path) -> None:
        rfcs = tmp_path / "rfcs"
        rfcs.mkdir()
        (rfcs / "RFC-001-one.md").write_text("# RFC-001\n")
        (rfcs / "RFC-002-two.md").write_text("# RFC-002\n")
        (rfcs / "README.md").write_text(
            "| # | Title |\n|---|---|\n| RFC-001 | One |\n| RFC-002 | Two |\n"
        )
        files, index = scan_rfc_dir(rfcs)
        assert sorted(f.number for f in files) == [1, 2]
        assert sorted(e.number for e in index) == [1, 2]
        assert evaluate(files, index) == []

    def test_scan_detects_duplicate_end_to_end(self, tmp_path: Path) -> None:
        rfcs = tmp_path / "rfcs"
        rfcs.mkdir()
        (rfcs / "RFC-006-first.md").write_text("# RFC-006\n")
        (rfcs / "RFC-006-second.md").write_text("# RFC-006\n")
        (rfcs / "README.md").write_text("| # |\n|---|\n| RFC-006 |\n")
        files, index = scan_rfc_dir(rfcs)
        violations = evaluate(files, index)
        assert len(violations) == 1
        assert "duplicate" in violations[0].lower()

    def test_missing_index_file_is_a_violation(self, tmp_path: Path) -> None:
        rfcs = tmp_path / "rfcs"
        rfcs.mkdir()
        (rfcs / "RFC-001-one.md").write_text("# RFC-001\n")
        files, index = scan_rfc_dir(rfcs)
        assert index == []
        violations = evaluate(files, index)
        # The one file is now "missing from the index" since the index is empty.
        assert len(violations) == 1
        assert "index" in violations[0].lower()

    def test_rfc_files_in_ignores_non_rfc(self, tmp_path: Path) -> None:
        rfcs = tmp_path / "rfcs"
        rfcs.mkdir()
        (rfcs / "RFC-001-one.md").write_text("x")
        (rfcs / "module.toml").write_text("x")
        (rfcs / ".gitkeep").write_text("")
        (rfcs / "README.md").write_text("x")
        names = sorted(f.filename for f in rfc_files_in(rfcs))
        assert names == ["RFC-001-one.md"]


# --- the repo's own RFCs must satisfy the guard ----------------------------


class TestLiveRepoState:
    """The real modules/rfcs/ tree on this branch must pass its own guard."""

    def test_repo_rfcs_pass(self) -> None:
        repo_rfcs = Path(__file__).resolve().parents[3] / "modules" / "rfcs"
        if not repo_rfcs.is_dir():
            pytest.skip("modules/rfcs not present in this checkout")
        files, index = scan_rfc_dir(repo_rfcs)
        assert evaluate(files, index) == [], (
            "the live modules/rfcs/ tree fails its own RFC-index guard"
        )
