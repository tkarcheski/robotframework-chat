#!/usr/bin/env bash
# ci/send_results.sh - Send Robot Framework results to a remote server
#
# Syncs the local results directory to a remote host via rsync over SSH.
# Only transfers output.xml, log.html, and report.html files.
#
# Required env vars:
#   RESULTS_SERVER       - Target hostname or IP
#   RESULTS_SERVER_USER  - SSH user on the remote host
#   RESULTS_SERVER_PATH  - Remote directory to receive results
#
# Optional env vars:
#   RESULTS_SERVER_PORT  - SSH port (default: 22)
#   RESULTS_DIR          - Local results directory (default: results/)
#
# Usage:
#   bash ci/send_results.sh
#   RESULTS_DIR=results/math bash ci/send_results.sh

set -euo pipefail

echo "=== Send Results to Remote Server ==="

for var in RESULTS_SERVER RESULTS_SERVER_USER RESULTS_SERVER_PATH; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: $var is not set"
        echo "Hint: copy .env.remote.example to .env and fill in the RESULTS_SERVER_* variables"
        exit 1
    fi
done

RESULTS_DIR="${RESULTS_DIR:-results/}"
RESULTS_SERVER_PORT="${RESULTS_SERVER_PORT:-22}"

if [ ! -d "$RESULTS_DIR" ]; then
    echo "ERROR: Results directory not found: $RESULTS_DIR"
    echo "Run tests first (e.g. make robot) to generate results."
    exit 1
fi

# Count result files before sending
file_count=$(find "$RESULTS_DIR" -name "output.xml" -o -name "log.html" -o -name "report.html" | wc -l)
if [ "$file_count" -eq 0 ]; then
    echo "WARNING: No result files (output.xml, log.html, report.html) found in $RESULTS_DIR"
    exit 0
fi

TARGET="${RESULTS_SERVER_USER}@${RESULTS_SERVER}:${RESULTS_SERVER_PATH}"

echo "Source:      $RESULTS_DIR"
echo "Destination: $TARGET"
echo "SSH port:    $RESULTS_SERVER_PORT"
echo "Files:       $file_count result file(s)"
echo ""

rsync -avz --progress \
    -e "ssh -p ${RESULTS_SERVER_PORT}" \
    --include='*/' \
    --include='output.xml' \
    --include='log.html' \
    --include='report.html' \
    --exclude='*' \
    "$RESULTS_DIR" "$TARGET"

echo ""
echo "=== Results sent successfully ==="
