"""Tests for release version consistency.

Validates that version strings are consistent across pyproject.toml
and src/rfc/__init__.py — the invariant that ci/release.sh depends on
when matching CI_COMMIT_TAG against the package version.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestVersionConsistency:
    """Ensure version strings stay in sync across all sources."""

    def test_pyproject_version_is_valid_semver(self) -> None:
        """pyproject.toml version must be a valid semver string."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        version = data["project"]["version"]
        assert re.match(
            r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?(\+[a-zA-Z0-9.]+)?$", version
        ), f"Invalid semver: {version}"

    def test_init_version_matches_pyproject(self) -> None:
        """src/rfc/__init__.py __version__ must match pyproject.toml."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        pyproject_version = data["project"]["version"]

        init_text = (ROOT / "src" / "rfc" / "__init__.py").read_text()
        match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
        assert match is not None, "__version__ not found in src/rfc/__init__.py"
        init_version = match.group(1)

        assert init_version == pyproject_version, (
            f"Version mismatch: __init__.py={init_version} vs "
            f"pyproject.toml={pyproject_version}"
        )

    def test_pyproject_has_build_backend(self) -> None:
        """pyproject.toml must declare hatchling as the build backend."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        assert data["build-system"]["build-backend"] == "hatchling.build"

    def test_dev_dependencies_include_build_tools(self) -> None:
        """dev dependencies must include build and twine for releases."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        dev_deps = data["project"]["optional-dependencies"]["dev"]
        dep_names = [d.split("[")[0].split(">=")[0].split("==")[0] for d in dev_deps]
        assert "build" in dep_names, "build package missing from dev dependencies"
        assert "twine" in dep_names, "twine package missing from dev dependencies"

    def test_release_script_exists_and_is_executable(self) -> None:
        """ci/release.sh must exist."""
        release_sh = ROOT / "ci" / "release.sh"
        assert release_sh.is_file(), "ci/release.sh not found"


class TestReleaseScriptContent:
    """Validate ci/release.sh script structure."""

    @pytest.fixture()
    def release_script(self) -> str:
        return (ROOT / "ci" / "release.sh").read_text()

    def test_uses_strict_mode(self, release_script: str) -> None:
        """Release script must use set -euo pipefail."""
        assert "set -euo pipefail" in release_script

    def test_validates_tag_version(self, release_script: str) -> None:
        """Release script must validate CI_COMMIT_TAG against pyproject.toml."""
        assert "CI_COMMIT_TAG" in release_script
        assert "pyproject.toml" in release_script

    def test_supports_dry_run(self, release_script: str) -> None:
        """Release script must support --dry-run flag."""
        assert "--dry-run" in release_script

    def test_builds_with_uv(self, release_script: str) -> None:
        """Release script must build using uv run."""
        assert "uv run python -m build" in release_script

    def test_verifies_with_twine(self, release_script: str) -> None:
        """Release script must verify distributions with twine check."""
        assert "uv run twine check" in release_script

    def test_uploads_with_twine(self, release_script: str) -> None:
        """Release script must upload with twine upload."""
        assert "uv run twine upload" in release_script
