#!/usr/bin/env bash
# Start the Docker Compose stack safely.
# Tears down any existing containers first to avoid stale state,
# then starts everything in detached mode.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Stopping existing containers..."
docker compose down

echo "Starting containers..."
docker compose up -d

echo "Stack is up. Use 'docker compose ps' to check status."
