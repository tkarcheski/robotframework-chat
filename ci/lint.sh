#!/usr/bin/env bash
# ci/lint.sh - Run code quality checks (fail fast, verbose)
#
# Runs all linters in sequence. Collects all failures before exiting
# so you see every problem in a single run.
#
# Usage:
#   bash ci/lint.sh              # run all checks
#   bash ci/lint.sh pre-commit   # run only pre-commit
#   bash ci/lint.sh ruff         # run only ruff
#   bash ci/lint.sh mypy         # run only mypy

set -uo pipefail

CHECKS="${1:-all}"
FAILURES=0

run_check() {
    local name="$1"
    shift
    echo ""
    echo "=== $name ==="
    if "$@"; then
        echo "--- $name: PASSED ---"
    else
        echo "--- $name: FAILED ---"
        FAILURES=$((FAILURES + 1))
    fi
}

if [ "$CHECKS" = "all" ] || [ "$CHECKS" = "pre-commit" ]; then
    run_check "pre-commit" uv run pre-commit run --all-files
fi

if [ "$CHECKS" = "all" ] || [ "$CHECKS" = "ruff" ]; then
    run_check "ruff check" uv run ruff check .
    run_check "ruff format" uv run ruff format --check .
fi

if [ "$CHECKS" = "all" ] || [ "$CHECKS" = "mypy" ]; then
    run_check "mypy" uv run mypy src/
fi

echo ""
echo "==============================="
if [ "$FAILURES" -gt 0 ]; then
    echo "LINT RESULT: $FAILURES check(s) FAILED"
    exit 1
else
    echo "LINT RESULT: all checks passed"
fi
