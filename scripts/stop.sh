#!/usr/bin/env bash
# Stop the Docker Compose stack.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Stopping containers..."
docker compose down

echo "Stack stopped."
