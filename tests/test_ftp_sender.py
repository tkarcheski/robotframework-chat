"""Tests for the multi-protocol results sender (FTP/FTPS/SFTP).

Covers TransferConfig construction from env vars, protocol selection,
file filtering, remote directory creation, and error handling.
"""

import ftplib
import os
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.rfc.ftp_sender import (
    TransferConfig,
    _ensure_remote_dir,
    config_from_env,
    upload_results,
)


# ── TransferConfig ───────────────────────────────────────────────────


class TestTransferConfig:
    def test_defaults(self) -> None:
        cfg = TransferConfig(host="ftp.example.com", user="u", password="p")
        assert cfg.host == "ftp.example.com"
        assert cfg.port is None  # resolved via effective_port
        assert cfg.effective_port == 21
        assert cfg.protocol == "ftps"
        assert cfg.passive_mode is True
        assert cfg.remote_path == "/"

    def test_sftp_default_port(self) -> None:
        cfg = TransferConfig(
            host="sftp.example.com", user="u", password="p", protocol="sftp"
        )
        assert cfg.effective_port == 22

    def test_ftp_default_port(self) -> None:
        cfg = TransferConfig(
            host="ftp.example.com", user="u", password="p", protocol="ftp"
        )
        assert cfg.effective_port == 21

    def test_explicit_port_overrides(self) -> None:
        cfg = TransferConfig(
            host="x", user="u", password="p", protocol="sftp", port=2222
        )
        assert cfg.effective_port == 2222


class TestConfigFromEnv:
    def test_builds_config_from_env_vars(self) -> None:
        env = {
            "FTP_RESULTS_SERVER": "ftp.test.com",
            "FTP_RESULTS_USER": "admin",
            "FTP_RESULTS_PASSWORD": "secret",
            "FTP_RESULTS_PATH": "/uploads",
            "FTP_RESULTS_PORT": "990",
            "FTP_RESULTS_PROTOCOL": "ftps",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = config_from_env()
        assert cfg.host == "ftp.test.com"
        assert cfg.user == "admin"
        assert cfg.password == "secret"
        assert cfg.remote_path == "/uploads"
        assert cfg.port == 990
        assert cfg.protocol == "ftps"

    def test_missing_server_raises(self) -> None:
        env = {"FTP_RESULTS_USER": "u", "FTP_RESULTS_PASSWORD": "p"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="FTP_RESULTS_SERVER"):
                config_from_env()

    def test_missing_user_raises(self) -> None:
        env = {"FTP_RESULTS_SERVER": "host", "FTP_RESULTS_PASSWORD": "p"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="FTP_RESULTS_USER"):
                config_from_env()

    def test_missing_password_raises(self) -> None:
        env = {"FTP_RESULTS_SERVER": "host", "FTP_RESULTS_USER": "u"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="FTP_RESULTS_PASSWORD"):
                config_from_env()

    def test_defaults_when_optional_missing(self) -> None:
        env = {
            "FTP_RESULTS_SERVER": "host",
            "FTP_RESULTS_USER": "u",
            "FTP_RESULTS_PASSWORD": "p",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = config_from_env()
        assert cfg.effective_port == 21
        assert cfg.protocol == "ftps"
        assert cfg.remote_path == "/"

    def test_invalid_protocol_raises(self) -> None:
        env = {
            "FTP_RESULTS_SERVER": "host",
            "FTP_RESULTS_USER": "u",
            "FTP_RESULTS_PASSWORD": "p",
            "FTP_RESULTS_PROTOCOL": "http",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="protocol"):
                config_from_env()


# ── Upload Logic ─────────────────────────────────────────────────────


class TestUploadResults:
    def _make_results_dir(self, tmp_path: Path) -> Path:
        """Create a fake results directory with test files."""
        results = tmp_path / "results" / "math"
        results.mkdir(parents=True)
        (results / "output.xml").write_text("<robot/>")
        (results / "log.html").write_text("<html/>")
        (results / "report.html").write_text("<html/>")
        (results / "ollama_timestamps.json").write_text("{}")  # should be skipped
        (results / "chat.log").write_text("log")  # should be skipped
        return tmp_path / "results"

    @patch("src.rfc.ftp_sender._upload_ftps")
    def test_ftps_is_default(self, mock_upload: MagicMock, tmp_path: Path) -> None:
        results_dir = self._make_results_dir(tmp_path)
        cfg = TransferConfig(host="h", user="u", password="p", protocol="ftps")
        upload_results(cfg, str(results_dir))
        mock_upload.assert_called_once()

    @patch("src.rfc.ftp_sender._upload_ftp")
    def test_plain_ftp_warns(self, mock_upload: MagicMock, tmp_path: Path) -> None:
        results_dir = self._make_results_dir(tmp_path)
        cfg = TransferConfig(host="h", user="u", password="p", protocol="ftp")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            upload_results(cfg, str(results_dir))
            ftp_warnings = [x for x in w if "unencrypted" in str(x.message).lower()]
            assert len(ftp_warnings) >= 1

    @patch("src.rfc.ftp_sender._upload_sftp")
    def test_sftp_protocol(self, mock_upload: MagicMock, tmp_path: Path) -> None:
        results_dir = self._make_results_dir(tmp_path)
        cfg = TransferConfig(host="h", user="u", password="p", protocol="sftp")
        upload_results(cfg, str(results_dir))
        mock_upload.assert_called_once()

    @patch("src.rfc.ftp_sender._upload_ftps")
    def test_filters_result_files_only(
        self, mock_upload: MagicMock, tmp_path: Path
    ) -> None:
        results_dir = self._make_results_dir(tmp_path)
        cfg = TransferConfig(host="h", user="u", password="p")
        # Make mock return the files it receives
        mock_upload.side_effect = lambda cfg, files, local_dir: files
        uploaded = upload_results(cfg, str(results_dir))
        # Should only upload output.xml, log.html, report.html
        filenames = [os.path.basename(f) for f in uploaded]
        assert sorted(filenames) == ["log.html", "output.xml", "report.html"]
        assert "ollama_timestamps.json" not in filenames
        assert "chat.log" not in filenames

    @patch("src.rfc.ftp_sender._upload_ftps")
    def test_empty_results_dir(self, mock_upload: MagicMock, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        cfg = TransferConfig(host="h", user="u", password="p")
        uploaded = upload_results(cfg, str(empty_dir))
        assert uploaded == []
        mock_upload.assert_not_called()

    def test_nonexistent_dir_raises(self) -> None:
        cfg = TransferConfig(host="h", user="u", password="p")
        with pytest.raises(FileNotFoundError):
            upload_results(cfg, "/nonexistent/path")


# ── Remote Directory Creation ────────────────────────────────────────


class TestEnsureRemoteDir:
    def test_creates_nested_dirs(self) -> None:
        ftp = MagicMock()
        ftp.pwd.return_value = "/"
        _ensure_remote_dir(ftp, "/results/math/2025")
        # Should attempt to cwd into each segment
        assert ftp.mkd.call_count >= 1 or ftp.cwd.call_count >= 1

    def test_handles_existing_dirs(self) -> None:
        ftp = MagicMock()
        ftp.pwd.return_value = "/"
        # mkd raises error for existing dir
        ftp.mkd.side_effect = ftplib.error_perm("550 Directory exists")
        # Should not raise — just continues
        _ensure_remote_dir(ftp, "/existing/path")
