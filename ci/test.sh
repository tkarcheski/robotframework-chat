#!/usr/bin/env bash
# ci/test.sh - Run Robot Framework tests with full diagnostics
#
# Wraps Makefile test targets with Ollama health checks and verbose
# failure reporting. Designed for CI: fails fast, fails loud.
#
# Usage:
#   bash ci/test.sh              # run all suites
#   bash ci/test.sh math         # run math suite only
#   bash ci/test.sh docker       # run docker suite only
#   bash ci/test.sh safety       # run safety suite only
#
# Environment:
#   OLLAMA_ENDPOINT  - Ollama API URL (default: http://localhost:11434)
#   DEFAULT_MODEL    - Model to test with (default: llama3)

set -uo pipefail

SUITE="${1:-all}"
OLLAMA_ENDPOINT="${OLLAMA_ENDPOINT:-http://localhost:11434}"
DEFAULT_MODEL="${DEFAULT_MODEL:-llama3}"

# ── Ollama health check ──────────────────────────────────────────────

check_ollama() {
    echo "=== Ollama Health Check ==="
    echo "Endpoint: $OLLAMA_ENDPOINT"
    echo "Model:    $DEFAULT_MODEL"
    echo ""

    if ! curl -sf "$OLLAMA_ENDPOINT/api/tags" > /dev/null 2>&1; then
        echo "ERROR: Ollama is not reachable at $OLLAMA_ENDPOINT"
        echo ""
        echo "Troubleshooting:"
        echo "  1. Is Ollama running?  systemctl status ollama"
        echo "  2. Correct endpoint?   OLLAMA_ENDPOINT=$OLLAMA_ENDPOINT"
        echo "  3. Firewall blocking?  curl -v $OLLAMA_ENDPOINT/api/tags"
        exit 1
    fi
    echo "Ollama is reachable."

    # Check model availability
    if ! curl -sf "$OLLAMA_ENDPOINT/api/show" \
        -d "{\"name\": \"$DEFAULT_MODEL\"}" > /dev/null 2>&1; then
        echo ""
        echo "ERROR: Model '$DEFAULT_MODEL' not found on $OLLAMA_ENDPOINT"
        echo ""
        echo "Available models:"
        curl -s "$OLLAMA_ENDPOINT/api/tags" | \
            python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('models', []):
    print(f'  - {m[\"name\"]}')
" 2>/dev/null || echo "  (could not list models)"
        echo ""
        echo "Pull the model:  ollama pull $DEFAULT_MODEL"
        exit 1
    fi
    echo "Model '$DEFAULT_MODEL' is available."
    echo "=== Health check passed ==="
    echo ""
}

# ── Test execution ───────────────────────────────────────────────────

run_suite() {
    local suite="$1"
    local target="robot-$suite"

    echo "=== Running: $suite ==="
    if make "$target"; then
        echo "--- $suite: PASSED ---"
        return 0
    else
        local rc=$?
        echo ""
        echo "--- $suite: FAILED (exit code $rc) ---"
        echo ""
        # Show output.xml location for debugging
        local results_dir="results/$suite"
        if [ -f "$results_dir/output.xml" ]; then
            echo "Results: $results_dir/output.xml"
            echo "Report:  $results_dir/report.html"
            echo "Log:     $results_dir/log.html"
        fi
        return $rc
    fi
}

# ── Main ─────────────────────────────────────────────────────────────

check_ollama

FAILURES=0

case "$SUITE" in
    all)
        for s in math docker safety; do
            run_suite "$s" || FAILURES=$((FAILURES + 1))
        done
        ;;
    math|docker|safety)
        run_suite "$SUITE" || FAILURES=$((FAILURES + 1))
        ;;
    *)
        echo "ERROR: Unknown suite '$SUITE'"
        echo "Usage: $0 [all|math|docker|safety]"
        exit 1
        ;;
esac

echo ""
echo "==============================="
if [ "$FAILURES" -gt 0 ]; then
    echo "TEST RESULT: $FAILURES suite(s) FAILED"
    exit 1
else
    echo "TEST RESULT: all suites passed"
fi
