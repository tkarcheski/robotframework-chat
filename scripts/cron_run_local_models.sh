#!/usr/bin/env bash
# Hourly cron job: pull latest code and run test suites against local models.
#
# Usage:
#   scripts/cron_run_local_models.sh             # Run git pull + make run-local-models
#   scripts/cron_run_local_models.sh --install    # Add hourly cron entry
#   scripts/cron_run_local_models.sh --uninstall  # Remove cron entry
#   scripts/cron_run_local_models.sh --help       # Show this help
#
# Override log location:
#   LOGFILE=/tmp/cron.log scripts/cron_run_local_models.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_PATH="${REPO_DIR}/scripts/cron_run_local_models.sh"
CRON_ENTRY="0 * * * * ${SCRIPT_PATH}"
LOGFILE="${LOGFILE:-${REPO_DIR}/results/cron_run_local_models.log}"

usage() {
    sed -n '2,/^[^#]/{ /^#/s/^# \?//p; }' "$0"
}

install_cron() {
    if crontab -l 2>/dev/null | grep -qF "$SCRIPT_PATH"; then
        echo "Cron entry already exists:"
        crontab -l | grep -F "$SCRIPT_PATH"
        return 0
    fi
    (crontab -l 2>/dev/null || true; echo "$CRON_ENTRY") | crontab -
    echo "Installed hourly cron entry:"
    echo "  $CRON_ENTRY"
}

uninstall_cron() {
    if ! crontab -l 2>/dev/null | grep -qF "$SCRIPT_PATH"; then
        echo "No cron entry found for this script."
        return 0
    fi
    crontab -l | grep -vF "$SCRIPT_PATH" | crontab -
    echo "Removed cron entry."
}

case "${1:-}" in
    --help|-h)
        usage
        exit 0
        ;;
    --install)
        install_cron
        exit 0
        ;;
    --uninstall)
        uninstall_cron
        exit 0
        ;;
    "")
        ;; # default: run the job
    *)
        echo "Unknown option: $1" >&2
        usage >&2
        exit 1
        ;;
esac

cd "$REPO_DIR"
mkdir -p "$(dirname "$LOGFILE")"

{
    echo "=== $(date -Iseconds) ==="
    echo "Pulling latest changes..."
    git pull
    echo "Running local models..."
    make run-local-models
    echo "=== done $(date -Iseconds) ==="
} >> "$LOGFILE" 2>&1
