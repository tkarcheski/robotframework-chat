#!/usr/bin/env bash
# Reproduces the robotframework-chat SWE-bench harness verification for
# pytest-dev__pytest-11148 (see src/rfc/swebench_keywords.py, apply_and_test_patch).
# Run from the directory containing generated.patch and test_patch.diff.
# Exits with the real verification exit code.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="arc-pilot-pytest-dev__pytest-11148"

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --cpus 1.0 --memory 2048m --user root \
    -w /workspace python:3.11-slim sleep 3600 >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1' EXIT

x() { docker exec -w /workspace "$NAME" sh -c "$1"; }

x "apt-get update -qq && apt-get install -y -qq git >/dev/null 2>&1"
x "git clone --quiet https://github.com/pytest-dev/pytest.git /workspace \
   && cd /workspace && git checkout -q 2f7415cfbc4b6ca62f9013f1abd27136f46b9653" || exit $?

docker cp "$HERE/test_patch.diff" "$NAME:/tmp/test_patch.diff"
x "git apply --allow-empty /tmp/test_patch.diff" || exit $?

x "pip install -e . 2>/dev/null || pip install -r requirements.txt 2>/dev/null || true"

docker cp "$HERE/generated.patch" "$NAME:/tmp/patch.diff"
x "git apply --allow-empty /tmp/patch.diff" || exit $?

x "python -m pytest --tb=short -q"
exit $?
