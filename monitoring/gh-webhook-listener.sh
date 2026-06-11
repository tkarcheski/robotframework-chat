#!/usr/bin/env bash
# Layer 3 launcher: forward GitHub webhook events for robotframework-chat to the
# local handler. Requires `gh` (authenticated) and the `gh webhook` extension.
#
# Usage:
#   ./monitoring/gh-webhook-listener.sh
#   MONITOR_AUTO_ACT=1 ./monitoring/gh-webhook-listener.sh   # let claude act
#
# It starts the Python handler in the background, then runs `gh webhook forward`
# in the foreground (Ctrl-C stops both).

set -euo pipefail

REPO="${MONITOR_GH_REPO:-tkarcheski/robotframework-chat}"
PORT="${MONITOR_PORT:-8765}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure the gh webhook extension is present.
if ! gh extension list 2>/dev/null | grep -q 'cli/gh-webhook'; then
  echo "Installing gh webhook extension..."
  gh extension install cli/gh-webhook
fi

# Start the local handler.
MONITOR_PORT="$PORT" python3 "$HERE/webhook_handler.py" &
HANDLER_PID=$!
trap 'kill "$HANDLER_PID" 2>/dev/null || true' EXIT

echo "Forwarding $REPO webhooks -> http://127.0.0.1:$PORT"
exec gh webhook forward \
  --repo="$REPO" \
  --events='issues,pull_request,issue_comment' \
  --url="http://127.0.0.1:$PORT"
