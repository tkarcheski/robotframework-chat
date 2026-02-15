#!/usr/bin/env bash
# ci/deploy.sh - Deploy Superset stack to remote host
#
# Required env vars:
#   SUPERSET_DEPLOY_HOST  - Target hostname
#   SUPERSET_DEPLOY_USER  - SSH user
#   SUPERSET_DEPLOY_PATH  - Remote path to project
#
# Usage: bash ci/deploy.sh

set -euo pipefail

echo "=== Deploy Superset ==="

for var in SUPERSET_DEPLOY_HOST SUPERSET_DEPLOY_USER SUPERSET_DEPLOY_PATH; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: $var is not set"
        exit 1
    fi
done

echo "Target: ${SUPERSET_DEPLOY_USER}@${SUPERSET_DEPLOY_HOST}:${SUPERSET_DEPLOY_PATH}"

ssh "$SUPERSET_DEPLOY_USER@$SUPERSET_DEPLOY_HOST" \
    "cd $SUPERSET_DEPLOY_PATH && git pull && docker compose -f docker-compose.yml up -d --pull always"

echo "=== Deploy complete ==="
