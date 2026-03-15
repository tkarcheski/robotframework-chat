"""Tests for scripts/sanitize_superset_db.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers – provide a mock sqlalchemy before importing the module
# ---------------------------------------------------------------------------
@pytest.fixture()
def sanitize() -> ModuleType:
    """Import the sanitize module with sqlalchemy mocked."""
    # Ensure sqlalchemy is available (mocked) during import and execution.
    mock_sa = MagicMock()
    with patch.dict(sys.modules, {"sqlalchemy": mock_sa}):
        scripts_dir = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_dir))
        spec = importlib.util.spec_from_file_location(
            "sanitize_superset_db", scripts_dir / "sanitize_superset_db.py"
        )
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# _get_database_url
# ---------------------------------------------------------------------------


class TestGetDatabaseUrl:
    """Tests for _get_database_url."""

    def test_returns_env_var(
        self, sanitize: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return DATABASE_URL from environment."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://rfc:pw@localhost:5433/rfc")
        result = sanitize._get_database_url()
        assert result == "postgresql://rfc:pw@localhost:5433/rfc"

    def test_returns_none_when_unset(
        self, sanitize: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return None when DATABASE_URL is not set and no .env."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with patch.object(Path, "exists", return_value=False):
            result = sanitize._get_database_url()
        assert result is None


# ---------------------------------------------------------------------------
# _get_row_counts
# ---------------------------------------------------------------------------


class TestGetRowCounts:
    """Tests for _get_row_counts."""

    def test_returns_counts(self, sanitize: ModuleType) -> None:
        """Should return row counts for each table."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 42

        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result

        mock_sa = MagicMock()
        mock_sa.create_engine.return_value = mock_engine
        with patch.dict(sys.modules, {"sqlalchemy": mock_sa}):
            counts = sanitize._get_row_counts("postgresql://x")

        assert counts["test_results"] == 42
        assert counts["test_runs"] == 42

    def test_returns_negative_on_error(self, sanitize: ModuleType) -> None:
        """Should return -1 for tables that error."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()

        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.side_effect = Exception("table missing")

        mock_sa = MagicMock()
        mock_sa.create_engine.return_value = mock_engine
        with patch.dict(sys.modules, {"sqlalchemy": mock_sa}):
            counts = sanitize._get_row_counts("postgresql://x")

        assert counts["test_results"] == -1
        assert counts["test_runs"] == -1


# ---------------------------------------------------------------------------
# _truncate_tables
# ---------------------------------------------------------------------------


class TestTruncateTables:
    """Tests for _truncate_tables."""

    def test_executes_truncate(self, sanitize: ModuleType) -> None:
        """Should execute TRUNCATE CASCADE on both tables."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()

        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        mock_sa = MagicMock()
        mock_sa.create_engine.return_value = mock_engine
        with patch.dict(sys.modules, {"sqlalchemy": mock_sa}):
            sanitize._truncate_tables("postgresql://x")

        # Verify TRUNCATE was called via text().
        mock_sa.text.assert_called_once()
        sql_arg = str(mock_sa.text.call_args[0][0])
        assert "TRUNCATE" in sql_arg
        assert "test_results" in sql_arg
        assert "test_runs" in sql_arg
        assert "CASCADE" in sql_arg
        mock_conn.execute.assert_called_once()


# ---------------------------------------------------------------------------
# main — integration tests
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for the main() entry point."""

    def test_exits_without_database_url(
        self, sanitize: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should exit with code 1 when DATABASE_URL is not set."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(sanitize, "_get_database_url", lambda: None)
        with pytest.raises(SystemExit, match="1"):
            sanitize.main()

    def test_exits_when_already_empty(
        self,
        sanitize: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should exit cleanly when all tables are empty."""
        monkeypatch.setattr(sanitize, "_get_database_url", lambda: "postgresql://x")
        monkeypatch.setattr(
            sanitize,
            "_get_row_counts",
            lambda url: {"test_results": 0, "test_runs": 0},
        )

        with pytest.raises(SystemExit, match="0"):
            sanitize.main()

        captured = capsys.readouterr()
        assert "already empty" in captured.out

    def test_aborts_on_no_confirmation(
        self,
        sanitize: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should abort when user answers 'n' to confirmation."""
        monkeypatch.setattr(sanitize, "_get_database_url", lambda: "postgresql://x")
        monkeypatch.setattr(
            sanitize,
            "_get_row_counts",
            lambda url: {"test_results": 100, "test_runs": 10},
        )

        with patch("builtins.input", return_value="n"):
            with pytest.raises(SystemExit, match="1"):
                sanitize.main()

    def test_proceeds_with_yes_flag(
        self,
        sanitize: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should skip confirmation with --yes flag."""
        monkeypatch.setattr(sanitize, "_get_database_url", lambda: "postgresql://x")
        monkeypatch.setattr(
            sanitize,
            "_get_row_counts",
            lambda url: {"test_results": 0, "test_runs": 0},
        )

        # Simulate --yes in sys.argv.
        monkeypatch.setattr("sys.argv", ["sanitize_superset_db.py", "--yes"])

        with pytest.raises(SystemExit, match="0"):
            sanitize.main()

    def test_aborts_on_eof(
        self,
        sanitize: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should abort gracefully on EOFError (piped input)."""
        monkeypatch.setattr(sanitize, "_get_database_url", lambda: "postgresql://x")
        monkeypatch.setattr(
            sanitize,
            "_get_row_counts",
            lambda url: {"test_results": 5, "test_runs": 1},
        )

        with patch("builtins.input", side_effect=EOFError):
            with pytest.raises(SystemExit, match="1"):
                sanitize.main()
