#!/usr/bin/env bash
# ci/test_dashboard.sh - Run dashboard tests (pytest + Playwright)
#
# Usage:
#   bash ci/test_dashboard.sh pytest       # Unit/integration tests only
#   bash ci/test_dashboard.sh playwright   # Browser self-tests only
#   bash ci/test_dashboard.sh all          # Both (default)

set -euo pipefail

MODE="${1:-all}"

echo "=== Dashboard Tests (mode: $MODE) ==="

# ---------------------------------------------------------------------------
# Pytest: unit and integration tests for dashboard modules
# ---------------------------------------------------------------------------
run_pytest() {
    echo "--- Running pytest for dashboard ---"
    uv run pytest tests/test_dashboard_layout.py tests/test_dashboard_monitoring.py -v \
        --tb=short \
        --junitxml=results/dashboard/pytest-results.xml
    echo "--- pytest complete ---"
}

# ---------------------------------------------------------------------------
# Playwright: Robot Framework Browser tests against a running dashboard
# ---------------------------------------------------------------------------
run_playwright() {
    echo "--- Ensuring compatible Node.js ---"
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # shellcheck disable=SC1091
    . "$SCRIPT_DIR/ensure_node.sh"

    echo "--- Installing Playwright browsers ---"
    uv run rfbrowser init chromium

    echo "--- Starting dashboard in background ---"
    uv run rfc-dashboard --port 8050 &
    DASHBOARD_PID=$!
    # Give it time to start
    echo "    Waiting for dashboard (PID $DASHBOARD_PID) ..."
    for i in $(seq 1 30); do
        if curl -s http://localhost:8050 >/dev/null 2>&1; then
            echo "    Dashboard ready after ${i}s"
            break
        fi
        sleep 1
    done

    echo "--- Running Playwright self-tests ---"
    uv run robot \
        -d results/dashboard/playwright \
        --exclude ollama \
        --exclude llm \
        robot/dashboard/tests/ || true

    echo "--- Stopping dashboard ---"
    kill "$DASHBOARD_PID" 2>/dev/null || true
    wait "$DASHBOARD_PID" 2>/dev/null || true
    echo "--- Playwright tests complete ---"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
mkdir -p results/dashboard results/dashboard/playwright

case "$MODE" in
    pytest)
        run_pytest
        ;;
    playwright)
        run_playwright
        ;;
    all)
        run_pytest
        run_playwright
        ;;
    *)
        echo "Unknown mode: $MODE"
        echo "Usage: $0 [pytest|playwright|all]"
        exit 1
        ;;
esac

echo "=== Dashboard tests done ==="
