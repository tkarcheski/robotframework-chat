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
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql://rfc:changeme@ai1:5433/rfc"
        )
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

    def test_raises_when_no_database_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        kw = SupersetKeywords()
        with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
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
        MockDB.assert_called_once_with(
            database_url="postgresql://rfc:x@host:5433/rfc"
        )


class TestPushHostInfo:
    """Test the Push Host Info keyword."""

    @patch("rfc.superset_keywords.collect_host_info")
    @patch("rfc.superset_keywords.TestDatabase")
    def test_pushes_host_info(
        self,
        MockDB: MagicMock,
        mock_collect: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://rfc:x@host:5433/rfc")
        mock_collect.return_value = {
            "hostname": "mini1",
            "os_name": "Darwin",
            "os_version": "24.0.0",
            "cpu_arch": "arm64",
            "cpu_count": 8,
            "total_ram_gb": 16.0,
            "gpu_info": "Apple M2",
        }
        mock_db = MagicMock()
        MockDB.return_value = mock_db

        kw = SupersetKeywords()
        result = kw.push_host_info()

        assert result["hostname"] == "mini1"
        mock_db.add_or_update_host.assert_called_once()
        host_arg = mock_db.add_or_update_host.call_args[0][0]
        assert host_arg.hostname == "mini1"
        assert host_arg.cpu_count == 8
        assert host_arg.gpu_info == "Apple M2"


class TestGetAllHosts:
    """Test the Get All Hosts keyword."""

    @patch("rfc.superset_keywords.TestDatabase")
    def test_returns_hosts(
        self, MockDB: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://rfc:x@host:5433/rfc")
        mock_db = MagicMock()
        mock_db.get_hosts.return_value = [
            {"hostname": "ai1", "last_seen": "2026-03-14"},
            {"hostname": "mini1", "last_seen": "2026-03-14"},
        ]
        MockDB.return_value = mock_db

        kw = SupersetKeywords()
        hosts = kw.get_all_hosts()
        assert len(hosts) == 2
        assert hosts[0]["hostname"] == "ai1"


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
            "models": 10,
            "pipeline_results": 5,
            "robot_dry_run_results": 2,
            "keyword_results": 1000,
            "ollama_metrics": 50,
            "host_info": 3,
        }.get(t, 0)
        MockDB.return_value = mock_db

        kw = SupersetKeywords()
        counts = kw.get_table_row_counts()
        assert counts["test_runs"] == 100
        assert counts["host_info"] == 3
        assert len(counts) == 8

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
        assert "SQLite" in version

    def test_get_table_row_count_sqlite(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        from rfc.test_database import TestDatabase

        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[arg-type]
        count = db.get_table_row_count("test_runs")
        assert count == 0

    def test_get_table_row_count_rejects_bad_name(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        from rfc.test_database import TestDatabase

        db = TestDatabase(db_path=str(tmp_path / "test.db"))  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="Invalid table name"):
            db.get_table_row_count("DROP TABLE test_runs;--")
