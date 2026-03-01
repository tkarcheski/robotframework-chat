#!/usr/bin/env bash
# ci/release.sh - Build and verify PyPI package (dry-run only)
#
# Publishing is handled by GitHub Actions trusted publishing.
# See .github/workflows/pypi-publish.yml
#
# Usage:
#   bash ci/release.sh   # Build sdist+wheel, verify with twine check

set -euo pipefail

echo "=== PyPI Package Verification ==="

# ── Read package version ─────────────────────────────────────────────

PKG_VERSION=$(uv run python -c "
import tomllib, pathlib
data = tomllib.loads(pathlib.Path('pyproject.toml').read_text())
print(data['project']['version'])
")

echo "Package version: $PKG_VERSION"

# ── Clean previous builds ────────────────────────────────────────────

echo "Cleaning dist/"
rm -rf dist/

# ── Build ─────────────────────────────────────────────────────────────

echo "Building sdist and wheel..."
uv run python -m build

echo "Built artifacts:"
ls -lh dist/

# ── Verify ────────────────────────────────────────────────────────────

echo "Verifying distributions..."
uv run twine check dist/*

echo "=== Verification complete ==="
echo "Package: robotframework-chat $PKG_VERSION"
echo "Publishing is handled by GitHub Actions on v* tags."
