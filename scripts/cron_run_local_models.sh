#!/usr/bin/env bash
# Hourly cron job: make update, sync models, and run test suites.
#
# Usage:
#   scripts/cron_run_local_models.sh             # Run make update + sync models + make run-local-models
#   scripts/cron_run_local_models.sh --install    # Add hourly cron entry
#   scripts/cron_run_local_models.sh --uninstall  # Remove cron entry
#   scripts/cron_run_local_models.sh --sync-models # Only check/pull missing master models
#   scripts/cron_run_local_models.sh --help       # Show this help
#
# Override log location:
#   LOGFILE=/tmp/cron.log scripts/cron_run_local_models.sh
#
# Environment:
#   OLLAMA_ENDPOINT  -- Ollama API base URL (default: http://localhost:11434)
#   LOGFILE          -- Log file path (default: results/cron_run_local_models.log)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_PATH="${REPO_DIR}/scripts/cron_run_local_models.sh"
CRON_ENTRY="0 * * * * ${SCRIPT_PATH}"
LOGFILE="${LOGFILE:-${REPO_DIR}/results/cron_run_local_models.log}"
OLLAMA_ENDPOINT="${OLLAMA_ENDPOINT:-http://localhost:11434}"
CONFIG_FILE="${REPO_DIR}/config/test_suites.yaml"

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

# Parse master_models from config/test_suites.yaml without requiring Python/yq.
# Reads lines between "master_models:" and the next section, extracting quoted values.
parse_master_models() {
    sed -n '/^master_models:/,/^[^ #]/{
        /^  - /{ s/^  - ["'\'']\{0,1\}//; s/["'\'']\{0,1\}$//; p; }
    }' "$CONFIG_FILE"
}

# Query locally installed models from the Ollama API.
get_local_models() {
    local response
    response=$(curl -sf --max-time 10 "${OLLAMA_ENDPOINT}/api/tags" 2>/dev/null) || {
        echo "WARNING: Cannot reach Ollama at ${OLLAMA_ENDPOINT}" >&2
        return 1
    }
    # Extract model names — works with basic grep (no jq dependency).
    echo "$response" | grep -oP '"name"\s*:\s*"\K[^"]+' | sort -u
}

# Compare master_models against locally installed models and pull any missing.
sync_models() {
    echo "Checking master models against local Ollama instance..."

    local master_models local_models missing=()
    master_models=$(parse_master_models)
    local_models=$(get_local_models) || return 0  # skip sync if Ollama unreachable

    while IFS= read -r model; do
        [ -z "$model" ] && continue
        # Check exact match and also base-name match (e.g. "llama3" matches "llama3:latest")
        if ! echo "$local_models" | grep -qxF "$model" &&
           ! echo "$local_models" | grep -qxF "${model%:*}:latest"; then
            missing+=("$model")
        fi
    done <<< "$master_models"

    if [ ${#missing[@]} -eq 0 ]; then
        echo "All ${#missing[@]:-0} master models are present locally."
        return 0
    fi

    echo "Missing ${#missing[@]} model(s): ${missing[*]}"
    for model in "${missing[@]}"; do
        echo "Pulling ${model}..."
        ollama pull "$model" || echo "WARNING: Failed to pull ${model}"
    done
    echo "Model sync complete."
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
    --sync-models)
        sync_models
        exit 0
        ;;
    "")
        ;; # default: run the full job
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
    echo "Updating repository..."
    make update
    echo "Syncing master models..."
    sync_models
    echo "Running local models..."
    make run-local-models
    echo "=== done $(date -Iseconds) ==="
} >> "$LOGFILE" 2>&1
