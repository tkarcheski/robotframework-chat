#!/usr/bin/env bash
# ci/sync_db.sh - Sync CI pipeline test results to database
#
# Fetches output.xml artifacts from recent GitLab CI pipelines
# and imports them into the PostgreSQL/Superset database.
#
# Subcommands:
#   sync            Full sync (default)
#   verify          Verify database contents
#   status          Check GitLab connection
#   list-pipelines  List recent pipelines
#   list-jobs ID    List jobs from a pipeline
#   fetch-artifact  Download a job artifact
#
# Required env vars:
#   GITLAB_API_URL     - GitLab instance URL (or CI_API_V4_URL in CI)
#   GITLAB_PROJECT_ID  - Numeric project ID (or CI_PROJECT_ID in CI)
#
# Optional env vars:
#   GITLAB_TOKEN       - API token with read_api scope
#   DATABASE_URL       - PostgreSQL connection string (default: SQLite)
#   SYNC_LIMIT         - Number of pipelines to sync (default: 5)
#   SYNC_REF           - Branch to filter (default: all)
#
# Usage:
#   bash ci/sync_db.sh              # full sync + verify
#   bash ci/sync_db.sh status       # check connection
#   bash ci/sync_db.sh list-pipelines
#   bash ci/sync_db.sh list-jobs 12345
#   bash ci/sync_db.sh fetch-artifact 67890
#   bash ci/sync_db.sh verify

set -euo pipefail

# Load .env if present (same vars the Makefile exports via -include .env)
ENV_FILE="${ENV_FILE:-.env}"
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +a
fi

# If a subcommand is given, pass it through directly
SUBCMD="${1:-}"

if [ -n "$SUBCMD" ] && [ "$SUBCMD" != "sync" ]; then
    # Direct passthrough to Python CLI
    uv run python scripts/sync_ci_results.py "$@"
    exit $?
fi

# Default: full sync + verify workflow
echo "=== Sync CI Results to Database ==="

# Validate at least one GitLab config source exists
if [ -z "${GITLAB_API_URL:-}" ] && [ -z "${CI_API_V4_URL:-}" ]; then
    echo "ERROR: GITLAB_API_URL or CI_API_V4_URL is not set"
    echo ""
    echo "Set one of these environment variables:"
    echo "  export GITLAB_API_URL=https://gitlab.example.com"
    echo "  (CI_API_V4_URL is set automatically inside GitLab CI)"
    exit 1
fi

if [ -z "${GITLAB_PROJECT_ID:-}" ] && [ -z "${CI_PROJECT_ID:-}" ]; then
    echo "ERROR: GITLAB_PROJECT_ID or CI_PROJECT_ID is not set"
    echo ""
    echo "Set one of these environment variables:"
    echo "  export GITLAB_PROJECT_ID=42"
    echo "  (CI_PROJECT_ID is set automatically inside GitLab CI)"
    exit 1
fi

if [ -z "${DATABASE_URL:-}" ]; then
    echo "WARNING: DATABASE_URL not set, will use SQLite default"
fi

echo "GitLab: ${GITLAB_API_URL:-${CI_API_V4_URL}}"
echo "Project: ${GITLAB_PROJECT_ID:-${CI_PROJECT_ID}}"
echo "Database: ${DATABASE_URL:-sqlite (default)}"
echo ""

# Build arguments
ARGS="sync"
if [ -n "${SYNC_LIMIT:-}" ]; then
    ARGS="$ARGS --limit $SYNC_LIMIT"
fi
if [ -n "${SYNC_REF:-}" ]; then
    ARGS="$ARGS --ref $SYNC_REF"
fi

# Run sync
# shellcheck disable=SC2086
uv run python scripts/sync_ci_results.py $ARGS

echo ""
echo "=== Verifying sync ==="
uv run python scripts/sync_ci_results.py verify

echo ""
echo "=== Sync complete ==="
