#!/usr/bin/env bash
# ci/sync.sh - Mirror GitLab repo to GitHub
#
# Required env vars:
#   CI_REPOSITORY_URL  - GitLab clone URL (set by GitLab CI)
#   GITHUB_USER        - GitHub username
#   GITHUB_TOKEN       - GitHub personal access token
#   CI_PROJECT_NAME    - Repository name (set by GitLab CI)
#
# Usage: bash ci/sync.sh

set -euo pipefail

echo "=== Mirror to GitHub ==="

# Validate required variables
for var in CI_REPOSITORY_URL GITHUB_USER GITHUB_TOKEN CI_PROJECT_NAME; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: $var is not set"
        exit 1
    fi
done

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

echo "Cloning mirror..."
git clone --mirror "$CI_REPOSITORY_URL" "$WORKDIR/repo.git"

cd "$WORKDIR/repo.git"
git remote add github "https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${CI_PROJECT_NAME}.git"

echo "Pushing to GitHub..."
git push github --mirror --force

echo "=== Mirror sync complete ==="
