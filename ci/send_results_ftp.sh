#!/usr/bin/env bash
# ci/send_results_ftp.sh - Send Robot Framework results via FTP/FTPS/SFTP
#
# Uploads output.xml, log.html, and report.html to a remote server
# using the protocol specified by FTP_RESULTS_PROTOCOL (default: ftps).
#
# Required env vars:
#   FTP_RESULTS_SERVER   - Target hostname or IP
#   FTP_RESULTS_USER     - Username for authentication
#   FTP_RESULTS_PASSWORD - Password for authentication
#
# Optional env vars:
#   FTP_RESULTS_PATH     - Remote directory (default: /)
#   FTP_RESULTS_PORT     - Port (default: 21 for FTP/FTPS, 22 for SFTP)
#   FTP_RESULTS_PROTOCOL - Protocol: ftp, ftps, sftp (default: ftps)
#   RESULTS_DIR          - Local results directory (default: results/)
#
# Usage:
#   bash ci/send_results_ftp.sh
#   RESULTS_DIR=results/math bash ci/send_results_ftp.sh

set -euo pipefail

# Source .env if present
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

for var in FTP_RESULTS_SERVER FTP_RESULTS_USER FTP_RESULTS_PASSWORD; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: $var is not set"
        echo "Hint: copy .env.example to .env and fill in the FTP_RESULTS_* variables"
        exit 1
    fi
done

RESULTS_DIR="${RESULTS_DIR:-results/}"

if [ ! -d "$RESULTS_DIR" ]; then
    echo "ERROR: Results directory not found: $RESULTS_DIR"
    echo "Run tests first (e.g. make robot) to generate results."
    exit 1
fi

uv run python -m rfc.ftp_sender "$RESULTS_DIR"
