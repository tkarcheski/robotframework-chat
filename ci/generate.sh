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
        uv run python scripts/discover_ollama.py --pretty
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
