#!/usr/bin/env bash
# ci/pipeline_report.sh - Generate pipeline testing summary and post to MR
#
# Collects job statuses from the GitLab API, parses JUnit XML artifacts,
# and generates a Markdown summary. Optionally posts it as an MR comment.
#
# Usage:
#   bash ci/pipeline_report.sh              # generate summary only
#   bash ci/pipeline_report.sh --post-mr    # generate and post to MR
#
# Environment:
#   CI_PIPELINE_ID           - Pipeline ID (set by GitLab CI)
#   CI_PROJECT_ID            - GitLab project ID
#   CI_API_V4_URL            - GitLab API base URL
#   CI_MERGE_REQUEST_IID     - MR number (set by GitLab CI)
#   GITLAB_TOKEN             - API token for fetching jobs and posting comments

set -euo pipefail

POST_MR=false
if [ "${1:-}" = "--post-mr" ]; then
    POST_MR=true
fi

echo "=== Pipeline Testing Summary ==="

# Build JUnit XML args from known artifact locations
JUNIT_ARGS=()
if [ -f "results/dashboard/pytest-results.xml" ]; then
    echo "Found dashboard pytest results"
    JUNIT_ARGS+=(--junit-xml results/dashboard/pytest-results.xml)
fi

# Run the summary generator
uv run python scripts/pipeline_summary.py -o metrics "${JUNIT_ARGS[@]}"
echo "Summary generated in metrics/pipeline_summary.md"

# Post to MR if requested and in MR context
if [ "$POST_MR" = true ] && [ -n "${CI_MERGE_REQUEST_IID:-}" ] && [ -n "${GITLAB_TOKEN:-}" ]; then
    echo ""
    echo "=== Posting to MR !${CI_MERGE_REQUEST_IID} ==="

    if curl --fail --request POST \
        --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/merge_requests/${CI_MERGE_REQUEST_IID}/notes" \
        --data-urlencode "body@metrics/pipeline_summary.md"; then
        echo ""
        echo "MR comment posted."
    else
        echo "WARNING: Could not post MR comment."
    fi
elif [ "$POST_MR" = true ]; then
    echo "Skipping MR post: not in MR context or GITLAB_TOKEN not set."
fi

echo "=== Pipeline report complete ==="
