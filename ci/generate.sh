#!/usr/bin/env bash
# ci/generate.sh - Generate child pipeline YAML
#
# Wraps scripts/generate_pipeline.py with diagnostics.
#
# Usage:
#   bash ci/generate.sh regular             # generate regular pipeline
#   bash ci/generate.sh dynamic             # generate dynamic pipeline
#   bash ci/generate.sh discover            # discover Ollama nodes only
#
# Output files:
#   regular  -> generated-pipeline.yml
#   dynamic  -> generated-dynamic-pipeline.yml
#   discover -> config/nodes_inventory.yaml

set -euo pipefail

MODE="${1:-regular}"

case "$MODE" in
    regular)
        echo "=== Generate Regular Pipeline ==="
        uv run python scripts/generate_pipeline.py --mode regular -o generated-pipeline.yml
        echo "--- generated-pipeline.yml ---"
        cat generated-pipeline.yml
        echo ""
        echo "--- Validation ---"
        FILE_SIZE=$(wc -c < generated-pipeline.yml)
        echo "File size: ${FILE_SIZE} bytes"
        if [ "$FILE_SIZE" -lt 10 ]; then
            echo "ERROR: generated-pipeline.yml is too small (${FILE_SIZE} bytes)"
            exit 1
        fi
        JOB_COUNT=$(uv run python -c "
import yaml, sys
with open('generated-pipeline.yml') as f:
    data = yaml.safe_load(f)
reserved = {'stages','variables','include','default','workflow','image','services','cache','before_script','after_script'}
jobs = [k for k in data if k not in reserved and not k.startswith('.')]
print(len(jobs))
")
        echo "Jobs in generated pipeline: ${JOB_COUNT}"
        if [ "$JOB_COUNT" -lt 1 ]; then
            echo "ERROR: generated pipeline has no jobs"
            exit 1
        fi
        echo "=== Done ==="
        ;;

    discover)
        echo "=== Discover Ollama Nodes ==="
        echo "Probing configured nodes for Ollama services..."
        uv run python scripts/discover_nodes.py -o config/nodes_inventory.yaml
        echo "--- nodes_inventory.yaml ---"
        cat config/nodes_inventory.yaml
        echo "=== Done ==="
        ;;

    dynamic)
        echo "=== Generate Dynamic Pipeline ==="
        echo "Discovering Ollama nodes..."
        # Node discovery is best-effort; generate pipeline even if some nodes unreachable
        uv run python scripts/discover_ollama.py --pretty || echo "WARNING: Ollama discovery failed (continuing with defaults)"
        uv run python scripts/generate_pipeline.py --mode dynamic -o generated-dynamic-pipeline.yml
        echo "--- generated-dynamic-pipeline.yml ---"
        cat generated-dynamic-pipeline.yml
        echo "=== Done ==="
        ;;

    *)
        echo "ERROR: Unknown mode '$MODE'"
        echo "Usage: $0 [regular|dynamic|discover]"
        exit 1
        ;;
esac
