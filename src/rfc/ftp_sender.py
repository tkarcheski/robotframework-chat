"""Multi-protocol results sender (FTP/FTPS/SFTP).

Uploads Robot Framework result files (output.xml, log.html, report.html)
to a remote server. Supports three transfer protocols:

- **ftps** (default): FTP over TLS via stdlib ``ftplib.FTP_TLS``
- **ftp**: Plain FTP (unencrypted — warns loudly)
- **sftp**: SSH-based file transfer via ``paramiko``

Configuration is read from ``FTP_RESULTS_*`` environment variables.

Usage::

    uv run python -m rfc.ftp_sender
    # or via Makefile:
    make send-results-ftp
"""

from __future__ import annotations

import ftplib
import logging
import os
import warnings
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Files to upload — matches the rsync filter in ci/send_results.sh
RESULT_FILE_PATTERNS = {"output.xml", "log.html", "report.html"}

VALID_PROTOCOLS = {"ftp", "ftps", "sftp"}


@dataclass
class TransferConfig:
    """Configuration for a file transfer connection."""

    host: str
    user: str
    password: str
    remote_path: str = "/"
    port: Optional[int] = None
    protocol: str = "ftps"
    passive_mode: bool = True

    @property
    def effective_port(self) -> int:
        """Return the port to use, defaulting based on protocol."""
        if self.port is not None:
            return self.port
        return 22 if self.protocol == "sftp" else 21


def config_from_env() -> TransferConfig:
    """Build a TransferConfig from ``FTP_RESULTS_*`` environment variables.

    Required:
        FTP_RESULTS_SERVER, FTP_RESULTS_USER, FTP_RESULTS_PASSWORD

    Optional:
        FTP_RESULTS_PATH (default: /), FTP_RESULTS_PORT (default: 21),
        FTP_RESULTS_PROTOCOL (default: ftps)

    Raises:
        ValueError: If required env vars are missing or protocol is invalid.
    """
    required = {
        "FTP_RESULTS_SERVER": os.environ.get("FTP_RESULTS_SERVER", ""),
        "FTP_RESULTS_USER": os.environ.get("FTP_RESULTS_USER", ""),
        "FTP_RESULTS_PASSWORD": os.environ.get("FTP_RESULTS_PASSWORD", ""),
    }
    for name, value in required.items():
        if not value:
            raise ValueError(f"{name} is required. Set it in .env or export it.")

    protocol = os.environ.get("FTP_RESULTS_PROTOCOL", "ftps").lower()
    if protocol not in VALID_PROTOCOLS:
        raise ValueError(
            f"Invalid protocol '{protocol}'. Must be one of: {', '.join(sorted(VALID_PROTOCOLS))}"
        )

    port_str = os.environ.get("FTP_RESULTS_PORT", "")
    port: Optional[int] = int(port_str) if port_str else None

    return TransferConfig(
        host=required["FTP_RESULTS_SERVER"],
        user=required["FTP_RESULTS_USER"],
        password=required["FTP_RESULTS_PASSWORD"],
        remote_path=os.environ.get("FTP_RESULTS_PATH", "/"),
        port=port,
        protocol=protocol,
    )


def _find_result_files(local_dir: str) -> list[str]:
    """Recursively find result files (output.xml, log.html, report.html)."""
    result_files: list[str] = []
    for root, _dirs, files in os.walk(local_dir):
        for fname in files:
            if fname in RESULT_FILE_PATTERNS:
                result_files.append(os.path.join(root, fname))
    return sorted(result_files)


def _ensure_remote_dir(ftp: ftplib.FTP, path: str) -> None:
    """Create remote directory tree, ignoring 'already exists' errors."""
    original = ftp.pwd()
    segments = [s for s in path.split("/") if s]
    try:
        ftp.cwd("/")
    except ftplib.error_perm:
        pass
    for segment in segments:
        try:
            ftp.cwd(segment)
        except ftplib.error_perm:
            try:
                ftp.mkd(segment)
            except ftplib.error_perm:
                pass  # directory may already exist
            ftp.cwd(segment)
    try:
        ftp.cwd(original)
    except ftplib.error_perm:
        pass


def _upload_ftp(config: TransferConfig, files: list[str], local_dir: str) -> list[str]:
    """Upload files via plain FTP (unencrypted)."""
    uploaded: list[str] = []
    ftp = ftplib.FTP()
    try:
        ftp.connect(config.host, config.effective_port)
        ftp.login(config.user, config.password)
        if config.passive_mode:
            ftp.set_pasv(True)
        _upload_files_ftp(ftp, config, files, local_dir, uploaded)
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()
    return uploaded


def _upload_ftps(config: TransferConfig, files: list[str], local_dir: str) -> list[str]:
    """Upload files via FTPS (FTP over TLS)."""
    uploaded: list[str] = []
    ftp = ftplib.FTP_TLS()
    try:
        ftp.connect(config.host, config.effective_port)
        ftp.login(config.user, config.password)
        ftp.prot_p()  # switch to secure data connection
        if config.passive_mode:
            ftp.set_pasv(True)
        _upload_files_ftp(ftp, config, files, local_dir, uploaded)
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()
    return uploaded


def _upload_files_ftp(
    ftp: ftplib.FTP,
    config: TransferConfig,
    files: list[str],
    local_dir: str,
    uploaded: list[str],
) -> None:
    """Upload files using an established FTP connection."""
    for filepath in files:
        rel_path = os.path.relpath(filepath, local_dir)
        remote_dir = os.path.join(
            config.remote_path, os.path.dirname(rel_path)
        ).replace("\\", "/")
        remote_file = os.path.join(config.remote_path, rel_path).replace("\\", "/")

        _ensure_remote_dir(ftp, remote_dir)
        ftp.cwd(remote_dir)

        logger.info("Uploading %s -> %s", filepath, remote_file)
        with open(filepath, "rb") as f:
            ftp.storbinary(f"STOR {os.path.basename(filepath)}", f)
        uploaded.append(filepath)
        logger.info("  OK: %s", remote_file)


def _upload_sftp(config: TransferConfig, files: list[str], local_dir: str) -> list[str]:
    """Upload files via SFTP (SSH-based file transfer)."""
    try:
        import paramiko  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "paramiko is required for SFTP uploads. "
            "Install it with: uv sync --extra dev"
        ) from None

    uploaded: list[str] = []
    transport = paramiko.Transport((config.host, config.effective_port))
    try:
        transport.connect(username=config.user, password=config.password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        if sftp is None:
            raise ConnectionError("Failed to create SFTP client")

        for filepath in files:
            rel_path = os.path.relpath(filepath, local_dir)
            remote_file = os.path.join(config.remote_path, rel_path).replace("\\", "/")
            remote_dir = os.path.dirname(remote_file)

            # Create remote directories
            _sftp_mkdirs(sftp, remote_dir)

            logger.info("Uploading %s -> %s", filepath, remote_file)
            sftp.put(filepath, remote_file)
            uploaded.append(filepath)
            logger.info("  OK: %s", remote_file)

        sftp.close()
    finally:
        transport.close()
    return uploaded


def _sftp_mkdirs(sftp: "paramiko.SFTPClient", path: str) -> None:  # type: ignore[name-defined]  # noqa: F821
    """Create remote directories recursively via SFTP."""
    segments = path.split("/")
    current = ""
    for segment in segments:
        if not segment:
            current = "/"
            continue
        current = f"{current}/{segment}" if current != "/" else f"/{segment}"
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)


def upload_results(
    config: TransferConfig,
    local_dir: str,
    patterns: Optional[set[str]] = None,
) -> list[str]:
    """Upload result files from local_dir to remote server.

    Args:
        config: Transfer configuration (host, credentials, protocol).
        local_dir: Local directory containing result files.
        patterns: File names to upload (default: output.xml, log.html, report.html).

    Returns:
        List of uploaded local file paths.

    Raises:
        FileNotFoundError: If local_dir does not exist.
    """
    if not os.path.isdir(local_dir):
        raise FileNotFoundError(f"Results directory not found: {local_dir}")

    files = _find_result_files(local_dir)
    if not files:
        logger.warning("No result files found in %s", local_dir)
        return []

    logger.info(
        "Uploading %d file(s) via %s to %s:%d%s",
        len(files),
        config.protocol.upper(),
        config.host,
        config.effective_port,
        config.remote_path,
    )

    if config.protocol == "ftp":
        warnings.warn(
            "Plain FTP is UNENCRYPTED. Credentials and data are sent in cleartext. "
            "Use ftps or sftp instead (set FTP_RESULTS_PROTOCOL=ftps).",
            UserWarning,
            stacklevel=2,
        )
        return _upload_ftp(config, files, local_dir)
    elif config.protocol == "sftp":
        return _upload_sftp(config, files, local_dir)
    else:  # ftps (default)
        return _upload_ftps(config, files, local_dir)


def main() -> None:
    """CLI entry point — reads config from env vars and uploads results."""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Upload Robot Framework results via FTP/FTPS/SFTP"
    )
    parser.add_argument(
        "results_dir",
        nargs="?",
        default="results/",
        help="Local results directory (default: results/)",
    )
    args = parser.parse_args()

    config = config_from_env()

    print(f"=== Send Results via {config.protocol.upper()} ===")
    print(f"Server:   {config.host}:{config.effective_port}")
    print(f"Path:     {config.remote_path}")
    print(f"Source:   {args.results_dir}")
    print()

    uploaded = upload_results(config, args.results_dir)

    print()
    if uploaded:
        print(f"=== {len(uploaded)} file(s) uploaded successfully ===")
    else:
        print("=== No files to upload ===")


if __name__ == "__main__":
    main()
