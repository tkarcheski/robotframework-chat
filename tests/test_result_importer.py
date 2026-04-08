"""Tests for the result importer with dedup and output.xml blob storage.

Covers SHA-256 deduplication, core import flow, OSError handling, and
the CLI entry point (main).
"""

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.rfc.result_importer import (
    ImportResult,
    compute_file_hash,
    import_results,
    main,
)


MINIMAL_OUTPUT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.0" generated="2025-06-15T10:00:00.000000">
  <suite name="Math Tests" id="s1">
    <metadata>
      <item name="Model">llama3</item>
      <item name="Commit_SHA">abc123</item>
      <item name="Branch">main</item>
      <item name="Timestamp">2025-06-15T10:00:00</item>
    </metadata>
    <test name="IQ 100 Basic Addition" id="s1-t1">
      <doc>What is 2 + 2?</doc>
      <tags><tag>score:1</tag></tags>
      <kw name="Ask LLM" library="rfc.keywords">
        <msg>Answer: 4</msg>
        <status status="PASS" start="2025-06-15T10:00:01.000000" end="2025-06-15T10:00:02.000000"/>
      </kw>
      <status status="PASS" start="2025-06-15T10:00:01.000000" end="2025-06-15T10:00:03.000000"/>
    </test>
    <status status="PASS" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:05.000000"/>
  </suite>
  <statistics>
    <total><stat pass="1" fail="0" skip="0">All Tests</stat></total>
  </statistics>
</robot>
"""


class TestComputeFileHash:
    def test_returns_sha256(self, tmp_path: Path) -> None:
        f = tmp_path / "test.xml"
        f.write_text("hello")
        expected = hashlib.sha256(b"hello").hexdigest()
        assert compute_file_hash(str(f)) == expected

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.xml"
        f2 = tmp_path / "b.xml"
        f1.write_text("alpha")
        f2.write_text("beta")
        assert compute_file_hash(str(f1)) != compute_file_hash(str(f2))


class TestImportResults:
    def _write_xml(self, tmp_path: Path) -> Path:
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(MINIMAL_OUTPUT_XML)
        return xml_file

    def _mock_db(self) -> MagicMock:
        db = MagicMock()
        db.db_path = ":memory:"
        db.add_test_run.return_value = 42
        return db

    def test_imports_and_returns_result(self, tmp_path: Path) -> None:
        xml_file = self._write_xml(tmp_path)
        db = self._mock_db()
        result = import_results(str(xml_file), db)
        assert isinstance(result, ImportResult)
        assert result.run_id == 42
        assert result.file_hash is not None
        assert result.skipped is False

    def test_dedup_skips_duplicate(self, tmp_path: Path) -> None:
        xml_file = self._write_xml(tmp_path)
        db = self._mock_db()
        result1 = import_results(str(xml_file), db)
        result2 = import_results(
            str(xml_file), db, check_dedup=True, _existing_hash=result1.file_hash
        )
        assert result2.skipped is True

    def test_source_tracking(self, tmp_path: Path) -> None:
        xml_file = self._write_xml(tmp_path)
        db = self._mock_db()
        result = import_results(str(xml_file), db, source="ci")
        assert result.source == "ci"

    def test_oserror_on_xml_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lines 95-96: OSError when reading XML for compression."""
        xml_file = self._write_xml(tmp_path)
        db = self._mock_db()

        import builtins

        _real_open = builtins.open
        call_count = 0

        def open_second_rb_fails(path: object, *a: object, **kw: object) -> object:
            nonlocal call_count
            mode = a[0] if a else kw.get("mode", "r")
            if str(path) == str(xml_file) and mode == "rb":
                call_count += 1
                if call_count == 2:
                    # First rb call is for hash, second for gzip
                    raise OSError("permission denied")
            return _real_open(path, *a, **kw)  # type: ignore[call-overload]

        monkeypatch.setattr("builtins.open", open_second_rb_fails)
        result = import_results(str(xml_file), db)
        assert result.run_id == 42


# ── CLI main() ───────────────────────────────────────────────────────


class TestResultImporterMain:
    def test_main_single_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(MINIMAL_OUTPUT_XML)

        mock_db = MagicMock()
        mock_db.db_path = ":memory:"
        mock_db.add_test_run.return_value = 1

        monkeypatch.setattr("sys.argv", ["result_importer", str(xml_file)])
        monkeypatch.setattr("src.rfc.result_importer.TestDatabase", lambda: mock_db)

        main()
        captured = capsys.readouterr()
        assert "Imported" in captured.out

    def test_main_recursive_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        sub = tmp_path / "math"
        sub.mkdir()
        (sub / "output.xml").write_text(MINIMAL_OUTPUT_XML)
        sub2 = tmp_path / "docker"
        sub2.mkdir()
        (sub2 / "output.xml").write_text(MINIMAL_OUTPUT_XML)

        mock_db = MagicMock()
        mock_db.db_path = ":memory:"
        mock_db.add_test_run.return_value = 1

        monkeypatch.setattr(
            "sys.argv", ["result_importer", str(tmp_path), "--recursive"]
        )
        monkeypatch.setattr("src.rfc.result_importer.TestDatabase", lambda: mock_db)

        main()
        captured = capsys.readouterr()
        assert "Imported 2" in captured.out

    def test_main_dir_without_recursive(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "output.xml").write_text(MINIMAL_OUTPUT_XML)

        mock_db = MagicMock()
        mock_db.db_path = ":memory:"
        mock_db.add_test_run.return_value = 1

        monkeypatch.setattr("sys.argv", ["result_importer", str(tmp_path)])
        monkeypatch.setattr("src.rfc.result_importer.TestDatabase", lambda: mock_db)

        main()
        captured = capsys.readouterr()
        assert "Imported 1" in captured.out

    def test_main_no_files_found(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        monkeypatch.setattr("sys.argv", ["result_importer", str(empty_dir)])
        monkeypatch.setattr("src.rfc.result_importer.TestDatabase", lambda: MagicMock())

        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "No output.xml" in captured.out

    def test_main_import_error_handled(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(MINIMAL_OUTPUT_XML)

        mock_db = MagicMock()
        mock_db.db_path = ":memory:"
        mock_db.add_test_run.side_effect = Exception("DB error")

        monkeypatch.setattr("sys.argv", ["result_importer", str(xml_file)])
        monkeypatch.setattr("src.rfc.result_importer.TestDatabase", lambda: mock_db)

        main()
        captured = capsys.readouterr()
        assert "Failed to import" in captured.out

    def test_main_dedup_skips_duplicate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Lines 186-187: CLI prints 'Skipped (duplicate)' when import_results returns skipped."""
        xml_file = tmp_path / "output.xml"
        xml_file.write_text(MINIMAL_OUTPUT_XML)

        mock_db = MagicMock()
        mock_db.db_path = ":memory:"

        # Make import_results return a skipped result
        skipped_result = ImportResult(
            run_id=0,
            file_hash="abc",
            file_path=str(xml_file),
            skipped=True,
            source="local",
        )
        monkeypatch.setattr(
            "src.rfc.result_importer.import_results",
            lambda *a, **kw: skipped_result,
        )
        monkeypatch.setattr("sys.argv", ["result_importer", str(xml_file), "--dedup"])
        monkeypatch.setattr("src.rfc.result_importer.TestDatabase", lambda: mock_db)

        main()
        captured = capsys.readouterr()
        assert "Skipped (duplicate)" in captured.out
        assert "skipped 1" in captured.out
