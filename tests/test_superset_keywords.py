"""Tests for rfc.superset_keywords.SupersetKeywords."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rfc.superset_keywords import SupersetKeywords


class TestGetDatabaseUrl:
    """Test the Get Database URL keyword."""

    def test_returns_not_set_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        kw = SupersetKeywords()
        assert kw.get_database_url() == "NOT SET"

    def test_masks_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://rfc:changeme@ai1:5433/rfc")
        kw = SupersetKeywords()
        result = kw.get_database_url()
        assert "changeme" not in result
        assert "****" in result
        assert "ai1:5433/rfc" in result

    def test_no_password_in_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "sqlite:///data/test.db")
        kw = SupersetKeywords()
        result = kw.get_database_url()
        assert result == "sqlite:///data/test.db"


class TestConnectToDatabase:
    """Test the Connect To Database keyword."""

    def test_raises_when_no_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        kw = SupersetKeywords()
        from rfc.exceptions import MissingEnvironmentError

        with pytest.raises(MissingEnvironmentError, match="DATABASE_URL is not set"):
            kw.connect_to_database()

    @patch("rfc.superset_keywords.TestDatabase")
    def test_returns_version(
        self, MockDB: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://rfc:x@host:5433/rfc")
        mock_db = MagicMock()
        mock_db.get_version.return_value = "PostgreSQL 16.12"
        MockDB.return_value = mock_db

        kw = SupersetKeywords()
        result = kw.connect_to_database()
        assert result == "PostgreSQL 16.12"
        MockDB.assert_called_once_with(database_url="postgresql://rfc:x@host:5433/rfc")


class TestGetTableRowCounts:
    """Test the Get Table Row Counts keyword."""

    @patch("rfc.superset_keywords.TestDatabase")
    def test_returns_counts(
        self, MockDB: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://rfc:x@host:5433/rfc")
        mock_db = MagicMock()
        mock_db.get_table_row_count.side_effect = lambda t: {
            "test_runs": 100,
            "test_results": 500,
        }.get(t, 0)
        MockDB.return_value = mock_db

        kw = SupersetKeywords()
        counts = kw.get_table_row_counts()
        assert counts["test_runs"] == 100
        assert counts["test_results"] == 500
        assert len(counts) == 2

    @patch("rfc.superset_keywords.TestDatabase")
    def test_handles_query_failure(
        self, MockDB: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://rfc:x@host:5433/rfc")
        mock_db = MagicMock()
        mock_db.get_table_row_count.side_effect = Exception("table missing")
        MockDB.return_value = mock_db

        kw = SupersetKeywords()
        counts = kw.get_table_row_counts()
        # All should be -1 on failure
        assert all(v == -1 for v in counts.values())


class TestGetVersionAndRowCount:
    """Test the new TestDatabase methods via SQLite."""

    def test_get_version_sqlite(self, tmp_path: pytest.TempPathFactory) -> None:
        from rfc.test_database import TestDatabase

        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[arg-type]
        version = db.get_version()
        # SQLite version is a string like "3.x.y"
        assert version

    def test_get_table_row_count_sqlite(self, tmp_path: pytest.TempPathFactory) -> None:
        from rfc.test_database import TestDatabase

        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[arg-type]
        count = db.get_table_row_count("test_runs")
        assert count == 0
