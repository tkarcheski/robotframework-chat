#!/usr/bin/env bash
# Autopilot: poll for git updates, run update+install+run-local-models on change.
#
# Behavior:
#   - On git update detected: make update && make install && make run-local-models
#   - No update: sleep 15 minutes, check again
#   - After 6 hours idle (no git updates): run-local-models anyway, reset timer
#
# Usage:
#   scripts/robot_autopilot.sh             # Run autopilot loop
#   scripts/robot_autopilot.sh --help      # Show this help
#
# Environment:
#   AUTOPILOT_POLL_INTERVAL  -- Seconds between git checks when idle (default: 900 = 15 min)
#   AUTOPILOT_IDLE_TIMEOUT   -- Seconds before forced run when idle (default: 21600 = 6 hrs)
#   LOGFILE                  -- Log file path (default: results/robot_autopilot.log)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
POLL_INTERVAL="${AUTOPILOT_POLL_INTERVAL:-900}"
IDLE_TIMEOUT="${AUTOPILOT_IDLE_TIMEOUT:-21600}"
LOGFILE="${LOGFILE:-${REPO_DIR}/results/robot_autopilot.log}"

usage() {
    sed -n '2,/^[^#]/{ /^#/s/^# \?//p; }' "$0"
}

case "${1:-}" in
    --help|-h)
        usage
        exit 0
        ;;
    "")
        ;; # default: run autopilot
    *)
        echo "Unknown option: $1" >&2
        usage >&2
        exit 1
        ;;
esac

cd "$REPO_DIR"
mkdir -p "$(dirname "$LOGFILE")"

log() {
    echo "[$(date -Iseconds)] $*" | tee -a "$LOGFILE"
}

# Check if remote has new commits. Returns 0 if updates available.
check_for_updates() {
    git fetch --quiet 2>/dev/null || {
        log "WARNING: git fetch failed (network issue?)"
        return 1
    }
    local local_head remote_head
    local_head="$(git rev-parse HEAD)"
    remote_head="$(git rev-parse '@{u}' 2>/dev/null)" || {
        log "WARNING: no upstream tracking branch configured"
        return 1
    }
    [ "$local_head" != "$remote_head" ]
}

run_full_cycle() {
    log "Running: make update"
    make update 2>&1 | tee -a "$LOGFILE"
    log "Running: make run-local-models"
    make run-local-models 2>&1 | tee -a "$LOGFILE"
    log "Full cycle complete."
}

run_local_models_only() {
    log "Idle timeout reached (${IDLE_TIMEOUT}s). Running make run-local-models."
    make run-local-models 2>&1 | tee -a "$LOGFILE"
    log "Idle run complete."
}

# ── Main loop ────────────────────────────────────────────────────────

log "=== Robot Autopilot started ==="
log "Poll interval: ${POLL_INTERVAL}s | Idle timeout: ${IDLE_TIMEOUT}s"

last_run_time="$(date +%s)"

while true; do
    log "Checking for git updates..."

    if check_for_updates; then
        log "Git updates detected."
        run_full_cycle
        last_run_time="$(date +%s)"
    else
        now="$(date +%s)"
        idle_elapsed=$(( now - last_run_time ))
        log "No updates. Idle for ${idle_elapsed}s / ${IDLE_TIMEOUT}s."

        if [ "$idle_elapsed" -ge "$IDLE_TIMEOUT" ]; then
            run_local_models_only
            last_run_time="$(date +%s)"
        else
            log "Sleeping ${POLL_INTERVAL}s..."
            sleep "$POLL_INTERVAL"
        fi
    fi
done
