#!/usr/bin/env bash
# ci/release.sh - Build and publish package to PyPI
#
# Required env vars (one of):
#   PYPI_TOKEN           - PyPI API token (preferred)
#   TWINE_USERNAME/PASSWORD - PyPI credentials
#
# Usage: bash ci/release.sh
#
# This script:
#   1. Validates the tag matches pyproject.toml version
#   2. Builds sdist and wheel
#   3. Verifies the distributions with twine check
#   4. Uploads to PyPI

set -euo pipefail

echo "=== PyPI Release ==="

# ── Resolve credentials ──────────────────────────────────────────────

if [ -n "${PYPI_TOKEN:-}" ]; then
    export TWINE_USERNAME="__token__"
    export TWINE_PASSWORD="$PYPI_TOKEN"
    echo "Using PYPI_TOKEN for authentication"
elif [ -n "${TWINE_USERNAME:-}" ] && [ -n "${TWINE_PASSWORD:-}" ]; then
    echo "Using TWINE_USERNAME/TWINE_PASSWORD for authentication"
else
    echo "ERROR: Set PYPI_TOKEN or TWINE_USERNAME+TWINE_PASSWORD"
    exit 1
fi

# ── Validate tag vs version ──────────────────────────────────────────

if [ -n "${CI_COMMIT_TAG:-}" ]; then
    TAG_VERSION="${CI_COMMIT_TAG#v}"
    PKG_VERSION=$(python -c "
import tomllib, pathlib
data = tomllib.loads(pathlib.Path('pyproject.toml').read_text())
print(data['project']['version'])
")
    echo "Tag version:     $TAG_VERSION"
    echo "Package version: $PKG_VERSION"
    if [ "$TAG_VERSION" != "$PKG_VERSION" ]; then
        echo "ERROR: Tag $CI_COMMIT_TAG does not match pyproject.toml version $PKG_VERSION"
        exit 1
    fi
else
    echo "WARNING: No CI_COMMIT_TAG set — skipping version validation"
fi

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

# ── Upload ────────────────────────────────────────────────────────────

echo "Uploading to PyPI..."
uv run twine upload dist/*

echo "=== Release complete ==="
echo "Published: https://pypi.org/project/robotframework-chat/$PKG_VERSION/"
