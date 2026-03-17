#!/bin/bash
set -euo pipefail

RESULTS_DIR="/app/results"
OUTPUT_DIR="/var/www/html/metrics"
REFRESH_INTERVAL="${METRICS_REFRESH_INTERVAL:-300}"  # seconds (default: 5 min)

generate_index() {
    # Build an index page listing all suite metric dashboards.
    local index="${OUTPUT_DIR}/index.html"
    local suites=()

    for dir in "${OUTPUT_DIR}"/*/; do
        [ -d "$dir" ] || continue
        suite=$(basename "$dir")
        # Only list suites that have a generated metrics file
        if ls "$dir"/*.html >/dev/null 2>&1; then
            suites+=("$suite")
        fi
    done

    cat > "$index" <<'HEADER'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Robot Framework Metrics</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
           max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; }
    h1 { border-bottom: 2px solid #2196F3; padding-bottom: 10px; }
    .suite-list { list-style: none; padding: 0; }
    .suite-list li { margin: 8px 0; }
    .suite-list a { display: block; padding: 12px 16px; background: #f5f5f5;
                    border-radius: 4px; text-decoration: none; color: #1565C0;
                    transition: background 0.2s; }
    .suite-list a:hover { background: #e3f2fd; }
    .empty { color: #888; font-style: italic; }
    .meta { color: #888; font-size: 0.85em; margin-top: 20px; }
  </style>
</head>
<body>
  <h1>Robot Framework Metrics</h1>
HEADER

    if [ ${#suites[@]} -eq 0 ]; then
        echo '  <p class="empty">No metrics generated yet. Run some Robot Framework tests and wait for the next refresh cycle.</p>' >> "$index"
    else
        echo '  <ul class="suite-list">' >> "$index"
        for suite in "${suites[@]}"; do
            echo "    <li><a href=\"${suite}/\">${suite}</a></li>" >> "$index"
        done
        echo '  </ul>' >> "$index"
    fi

    local ts
    ts=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
    cat >> "$index" <<FOOTER
  <p class="meta">Last updated: ${ts} &mdash; refreshes every ${REFRESH_INTERVAL}s</p>
</body>
</html>
FOOTER
}

generate_metrics() {
    echo "$(date -u '+%Y-%m-%d %H:%M:%S') Scanning ${RESULTS_DIR} for output.xml files..."

    local count=0
    while IFS= read -r xml; do
        [ -z "$xml" ] && continue
        local suite_dir suite_name dest
        suite_dir=$(dirname "$xml")
        suite_name=$(basename "$suite_dir")
        dest="${OUTPUT_DIR}/${suite_name}"

        mkdir -p "$dest"
        echo "  Generating metrics for suite '${suite_name}' from ${xml}..."

        # robotmetrics writes report into --metrics-report-path
        if robotmetrics \
            --inputpath "$suite_dir" \
            --output "output.xml" \
            --metrics-report-path "$dest/" 2>&1; then
            count=$((count + 1))
        else
            echo "  WARNING: metrics generation failed for '${suite_name}' (non-fatal)"
        fi
    done < <(find "$RESULTS_DIR" -name "output.xml" -type f 2>/dev/null)

    echo "$(date -u '+%Y-%m-%d %H:%M:%S') Generated metrics for ${count} suite(s)."
    generate_index
}

# ── Main ─────────────────────────────────────────────────────────────
echo "=== robotframework-metrics dashboard ==="
echo "Results dir : ${RESULTS_DIR}"
echo "Output dir  : ${OUTPUT_DIR}"
echo "Refresh     : every ${REFRESH_INTERVAL}s"

# Initial generation
generate_metrics

# Start nginx in background
echo "Starting nginx..."
nginx

# Regeneration loop
while true; do
    sleep "$REFRESH_INTERVAL"
    generate_metrics
done
