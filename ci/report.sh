#!/usr/bin/env bash
# ci/report.sh - Generate repo metrics and post MR comments
#
# Usage:
#   bash ci/report.sh              # generate metrics only
#   bash ci/report.sh --post-mr    # generate and post to MR
#
# Environment:
#   CI_MERGE_REQUEST_IID     - MR number (set by GitLab CI)
#   GITLAB_TOKEN             - API token for posting comments
#   CI_API_V4_URL            - GitLab API base URL
#   CI_PROJECT_ID            - GitLab project ID

set -euo pipefail

POST_MR=false
if [ "${1:-}" = "--post-mr" ]; then
    POST_MR=true
fi

echo "=== Repo Metrics ==="

# Install matplotlib for plotting
uv pip install matplotlib 2>/dev/null || true

uv run python scripts/repo_metrics.py -o metrics
echo "Metrics generated in metrics/"

# Post to MR if requested and in MR context
if [ "$POST_MR" = true ] && [ -n "${CI_MERGE_REQUEST_IID:-}" ] && [ -n "${GITLAB_TOKEN:-}" ]; then
    echo ""
    echo "=== Posting to MR !${CI_MERGE_REQUEST_IID} ==="

    if curl --fail --request POST \
        --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/merge_requests/${CI_MERGE_REQUEST_IID}/notes" \
        --data-urlencode "body@metrics/summary.md"; then
        echo "MR comment posted."
    else
        echo "WARNING: Could not post MR comment."
    fi
elif [ "$POST_MR" = true ]; then
    echo "Skipping MR post: not in MR context or GITLAB_TOKEN not set."
fi

echo "=== Report complete ==="
