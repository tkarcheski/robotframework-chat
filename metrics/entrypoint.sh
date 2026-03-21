#!/bin/bash
set -euo pipefail

RESULTS_DIR="${RESULTS_DIR:-/app/results}"
OUTPUT_DIR="${OUTPUT_DIR:-/var/www/html/metrics}"
REFRESH_INTERVAL="${METRICS_REFRESH_INTERVAL:-300}"  # seconds (default: 5 min)
NAV_INDEX_NAME="${METRICS_NAV_INDEX_NAME:-navigation.html}"

relative_path() {
    local root path
    root="${1%/}"
    path="${2%/}"

    if [ "$path" = "$root" ]; then
        printf '.'
    else
        printf '%s' "${path#"$root"/}"
    fi
}

suite_label() {
    local rel_path="${1:-.}"
    if [ "$rel_path" = "." ]; then
        printf 'root'
    else
        printf '%s' "$rel_path"
    fi
}

find_suite_entry() {
    local dir="${1:?suite dir required}"
    local candidate=""

    if [ -f "${dir}/index.html" ]; then
        candidate="${dir}/index.html"
    elif [ -f "${dir}/dashboard.html" ]; then
        candidate="${dir}/dashboard.html"
    else
        while IFS= read -r html_file; do
            case "$(basename "$html_file")" in
                index.html|"${NAV_INDEX_NAME}")
                    continue
                    ;;
            esac
            candidate="$html_file"
            break
        done < <(find "$dir" -maxdepth 1 -name "*.html" -type f | sort)
    fi

    if [ -z "$candidate" ]; then
        return 1
    fi

    relative_path "$OUTPUT_DIR" "$candidate"
}

render_navigation_page() {
    local nav_index="$1"
    shift
    local entries=("$@")

    cat > "$nav_index" <<'HEADER'
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

    if [ ${#entries[@]} -eq 0 ]; then
        echo '  <p class="empty">No metrics generated yet. Run some Robot Framework tests and wait for the next refresh cycle.</p>' >> "$nav_index"
    else
        echo '  <ul class="suite-list">' >> "$nav_index"
        local entry suite link label
        for entry in "${entries[@]}"; do
            suite="${entry%%|*}"
            link="${entry#*|}"
            label=$(suite_label "$suite")
            echo "    <li><a href=\"${link}\">${label}</a></li>" >> "$nav_index"
        done
        echo '  </ul>' >> "$nav_index"
    fi

    local ts
    ts=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
    cat >> "$nav_index" <<FOOTER
  <p class="meta">Last updated: ${ts} &mdash; refreshes every ${REFRESH_INTERVAL}s</p>
</body>
</html>
FOOTER
}

generate_index() {
    # Build a navigation page listing all suite metric dashboards.
    local nav_index="${OUTPUT_DIR}/${NAV_INDEX_NAME}"
    local entries=()
    local suite_dirs=()

    while IFS= read -r html_file; do
        local dir rel_dir already=false
        dir=$(dirname "$html_file")
        rel_dir=$(relative_path "$OUTPUT_DIR" "$dir")
        for s in "${suite_dirs[@]+"${suite_dirs[@]}"}"; do
            [ "$s" = "$rel_dir" ] && already=true && break
        done
        "$already" || suite_dirs+=("$rel_dir")
    done < <(
        find "$OUTPUT_DIR" -mindepth 1 -name "*.html" -type f 2>/dev/null \
            ! -name "${NAV_INDEX_NAME}" | sort
    )

    local rel_dir link
    for rel_dir in "${suite_dirs[@]+"${suite_dirs[@]}"}"; do
        local dir_path="$OUTPUT_DIR"
        if [ "$rel_dir" != "." ]; then
            dir_path="${OUTPUT_DIR}/${rel_dir}"
        fi
        if link=$(find_suite_entry "$dir_path"); then
            entries+=("${rel_dir}|${link}")
        fi
    done

    render_navigation_page "$nav_index" "${entries[@]+"${entries[@]}"}"

    if [ ! -f "${OUTPUT_DIR}/index.html" ]; then
        cp "$nav_index" "${OUTPUT_DIR}/index.html"
    fi
}

generate_metrics() {
    echo "$(date -u '+%Y-%m-%d %H:%M:%S') Scanning ${RESULTS_DIR} for output.xml files..."

    local count=0 found=0
    while IFS= read -r xml; do
        [ -z "$xml" ] && continue
        local suite_dir rel_path dest label
        found=$((found + 1))
        suite_dir=$(dirname "$xml")
        # Use the full relative path from RESULTS_DIR to avoid collisions.
        # e.g. results/local/node1/model1/output.xml → local/node1/model1
        rel_path=$(relative_path "$RESULTS_DIR" "$suite_dir")
        if [ "$rel_path" = "." ]; then
            dest="${OUTPUT_DIR}"
        else
            dest="${OUTPUT_DIR}/${rel_path}"
        fi
        label=$(suite_label "$rel_path")

        mkdir -p "$dest"
        echo "  Generating metrics for '${label}' from ${xml}..."

        # robotmetrics writes report into --metrics-report-path
        if robotmetrics \
            --inputpath "$suite_dir" \
            --output "output.xml" \
            --metrics-report-path "$dest/" 2>&1; then
            count=$((count + 1))
        else
            echo "  WARNING: metrics generation failed for '${label}' (non-fatal)"
        fi
    done < <(find "$RESULTS_DIR" -name "output.xml" -type f 2>/dev/null)

    if [ "$found" -eq 0 ]; then
        echo "$(date -u '+%Y-%m-%d %H:%M:%S') No output.xml files found under ${RESULTS_DIR}."
    fi

    echo "$(date -u '+%Y-%m-%d %H:%M:%S') Generated metrics for ${count} suite(s)."
    generate_index
}

main() {
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
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
