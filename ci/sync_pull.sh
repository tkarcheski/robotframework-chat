#!/usr/bin/env bash
# ci/sync_pull.sh - Pull GitHub repo and push to GitLab
#
# Required env vars:
#   GITHUB_USER   - GitHub username
#   GITHUB_TOKEN  - GitHub personal access token
#   GITLAB_TOKEN  - GitLab personal access token (write_repository scope)
#
# Optional env vars:
#   GITHUB_REPO   - GitHub repo name (default: robotframework-chat)
#   GITLAB_URL    - GitLab repo URL (default: gitlab.com/space-nomads/robotframework-chat.git)
#
# Usage: bash ci/sync_pull.sh

set -euo pipefail

echo "=== Sync: GitHub → GitLab ==="

# Validate required variables
for var in GITHUB_USER GITHUB_TOKEN GITLAB_TOKEN; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: $var is not set"
        exit 1
    fi
done

GITHUB_REPO="${GITHUB_REPO:-robotframework-chat}"
GITLAB_URL="${GITLAB_URL:-gitlab.com/space-nomads/robotframework-chat.git}"

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

echo "Cloning mirror from GitHub..."
git clone --mirror "https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${GITHUB_REPO}.git" "$WORKDIR/repo.git"

cd "$WORKDIR/repo.git"
git remote add gitlab "https://oauth2:${GITLAB_TOKEN}@${GITLAB_URL}"

echo "Pushing to GitLab..."
git push gitlab --mirror --force

echo "=== Sync complete: GitHub → GitLab ==="
