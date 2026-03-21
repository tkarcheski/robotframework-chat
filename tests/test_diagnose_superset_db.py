"""Tests for scripts/diagnose_superset_db.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers – import the module under test
# ---------------------------------------------------------------------------
@pytest.fixture()
def diag():
    """Import the diagnostic module."""
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "diagnose_superset_db", scripts_dir / "diagnose_superset_db.py"
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# check_port_mapping
# ---------------------------------------------------------------------------


class TestCheckPortMapping:
    """Tests for the check_port_mapping function."""

    def test_port_reachable(
        self, diag: object, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When port is reachable, should print OK."""
        with patch("socket.create_connection") as mock_conn:
            mock_sock = MagicMock()
            mock_conn.return_value = mock_sock
            diag.check_port_mapping()  # type: ignore[attr-defined]

        captured = capsys.readouterr()
        assert "OK" in captured.out
        assert "accepting connections" in captured.out
        mock_sock.close.assert_called()

    def test_port_unreachable_shows_fail(
        self, diag: object, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When port is unreachable, should print FAIL with guidance."""
        with patch(
            "socket.create_connection",
            side_effect=ConnectionRefusedError("refused"),
        ):
            diag.check_port_mapping()  # type: ignore[attr-defined]

        captured = capsys.readouterr()
        assert "FAIL" in captured.out
        assert "NOT reachable" in captured.out

    def test_respects_postgres_port_env(
        self,
        diag: object,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should read POSTGRES_PORT from environment."""
        monkeypatch.setenv("POSTGRES_PORT", "5555")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with patch(
            "socket.create_connection",
            side_effect=ConnectionRefusedError("refused"),
        ):
            diag.check_port_mapping()  # type: ignore[attr-defined]

        captured = capsys.readouterr()
        assert "5555" in captured.out

    def test_uses_host_from_database_url(
        self,
        diag: object,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When DATABASE_URL points to a remote host, check_port_mapping
        should probe that host, not localhost."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://rfc:changeme@ai1:5433/rfc")
        monkeypatch.delenv("POSTGRES_PORT", raising=False)
        with patch("socket.create_connection") as mock_conn:
            mock_sock = MagicMock()
            mock_conn.return_value = mock_sock
            diag.check_port_mapping()  # type: ignore[attr-defined]

        # Verify the first call connected to ai1:5433, not localhost.
        # (The second call checks Superset on localhost:8088.)
        first_call_args = mock_conn.call_args_list[0][0]
        assert first_call_args[0] == ("ai1", 5433), (
            f"Expected connection to ('ai1', 5433) but got {first_call_args[0]}. "
            "check_port_mapping must parse host/port from DATABASE_URL."
        )

    def test_uses_database_host_env(
        self,
        diag: object,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When DATABASE_HOST is set but DATABASE_URL is not, use DATABASE_HOST."""
        monkeypatch.setenv("DATABASE_HOST", "myserver")
        monkeypatch.setenv("POSTGRES_PORT", "5433")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with patch("socket.create_connection") as mock_conn:
            mock_sock = MagicMock()
            mock_conn.return_value = mock_sock
            diag.check_port_mapping()  # type: ignore[attr-defined]

        first_call_args = mock_conn.call_args_list[0][0]
        assert first_call_args[0] == ("myserver", 5433)


# ---------------------------------------------------------------------------
# check_env — password default warning
# ---------------------------------------------------------------------------


class TestCheckEnvPasswordWarning:
    """The POSTGRES_PASSWORD warning must reflect the actual defaults."""

    def test_no_password_warning_is_accurate(
        self,
        diag: object,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When POSTGRES_PASSWORD is unset, the warning must not claim a mismatch
        that doesn't exist. Both docker-compose and superset_config now default
        to 'changeme'."""
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        diag.check_env()  # type: ignore[attr-defined]

        captured = capsys.readouterr()
        assert "defaults to 'rfc'" not in captured.out, (
            "Stale warning: superset_config.py no longer defaults to 'rfc'. "
            "Both docker-compose and superset_config default to 'changeme'."
        )


# ---------------------------------------------------------------------------
# check_docker
# ---------------------------------------------------------------------------


class TestCheckDocker:
    """Tests for the check_docker function."""

    def test_docker_not_found(
        self, diag: object, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When docker binary is missing, should warn (not crash)."""
        with patch(
            "subprocess.run",
            side_effect=FileNotFoundError("docker not found"),
        ):
            diag.check_docker()  # type: ignore[attr-defined]

        captured = capsys.readouterr()
        assert "WARN" in captured.out

    def test_no_services_running(
        self, diag: object, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When docker compose ps returns empty, should warn."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            diag.check_docker()  # type: ignore[attr-defined]

        captured = capsys.readouterr()
        assert "WARN" in captured.out

    def test_services_running(
        self, diag: object, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When docker compose ps returns running services, should show OK."""
        import json

        svc = {"Service": "postgres", "State": "running"}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(svc)
        with patch("subprocess.run", return_value=mock_result):
            diag.check_docker()  # type: ignore[attr-defined]

        captured = capsys.readouterr()
        assert "OK" in captured.out
        assert "postgres" in captured.out
