"""Tests for release version consistency and GitHub Actions publish workflow.

Validates that version strings are consistent across pyproject.toml
and src/rfc/__init__.py, and that the GitHub Actions workflow for
PyPI trusted publishing is correctly configured.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

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

    def test_pyproject_has_urls(self) -> None:
        """pyproject.toml must have project.urls for PyPI listing."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        urls = data["project"]["urls"]
        assert "Homepage" in urls
        assert "Repository" in urls

    def test_pyproject_has_keywords(self) -> None:
        """pyproject.toml must have keywords for PyPI discoverability."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        keywords = data["project"]["keywords"]
        assert len(keywords) > 0

    def test_version_is_at_least_1_18(self) -> None:
        """New public suites since 1.17.5 (OpenAI Evals, SWE-bench Verified
        knobs) require a minor bump to 1.18.0 per the version-bump policy."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        version = data["project"]["version"]
        parts = tuple(int(p) for p in version.split("-")[0].split("."))
        assert parts >= (1, 18, 0), f"Expected >= 1.18.0, got {version}"


class TestChangelog:
    """Validate core/CHANGELOG.md exists and tracks the release history."""

    @staticmethod
    def _changelog_text() -> str:
        path = ROOT / "CHANGELOG.md"
        assert path.is_file(), "core/CHANGELOG.md not found"
        return path.read_text()

    def test_changelog_exists(self) -> None:
        """CHANGELOG.md must exist at the core (public) root."""
        assert (ROOT / "CHANGELOG.md").is_file()

    def test_changelog_has_unreleased_top_section(self) -> None:
        """The first version heading must be the Unreleased section."""
        text = self._changelog_text()
        headings = re.findall(r"^## (.+)$", text, re.MULTILINE)
        assert headings, "CHANGELOG.md has no '## ' version headings"
        assert "Unreleased" in headings[0], (
            f"Top section must be Unreleased, got: {headings[0]}"
        )

    def test_changelog_top_section_matches_pyproject_version(self) -> None:
        """The Unreleased heading must carry the current pyproject version."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        version = data["project"]["version"]
        text = self._changelog_text()
        headings = re.findall(r"^## (.+)$", text, re.MULTILINE)
        assert version in headings[0], (
            f"Top CHANGELOG heading {headings[0]!r} does not mention "
            f"pyproject version {version}"
        )

    def test_changelog_covers_every_minor_line_since_1_5(self) -> None:
        """Every minor line 1.5 through 1.17 must have a section heading."""
        text = self._changelog_text()
        headings = " ".join(re.findall(r"^## (.+)$", text, re.MULTILINE))
        missing = [
            f"1.{minor}" for minor in range(5, 18) if f"1.{minor}" not in headings
        ]
        assert not missing, f"CHANGELOG.md missing minor lines: {missing}"


class TestGitHubActionsPublishWorkflow:
    """Validate .github/workflows/pypi-publish.yml configuration."""

    def test_workflow_exists(self) -> None:
        """GitHub Actions publish workflow must exist."""
        wf = ROOT / ".github" / "workflows" / "pypi-publish.yml"
        assert wf.is_file(), ".github/workflows/pypi-publish.yml not found"

    def test_triggers_on_version_tags(self) -> None:
        """Workflow must trigger on v* tags."""
        wf = yaml.safe_load(
            (ROOT / ".github" / "workflows" / "pypi-publish.yml").read_text()
        )
        assert "push" in wf[True]  # 'on' is parsed as True by PyYAML
        tags = wf[True]["push"]["tags"]
        assert "v*" in tags

    def test_has_id_token_permission(self) -> None:
        """Workflow must request id-token: write for OIDC trusted publishing."""
        wf = yaml.safe_load(
            (ROOT / ".github" / "workflows" / "pypi-publish.yml").read_text()
        )
        permissions = wf.get("permissions", {})
        assert permissions.get("id-token") == "write"

    def test_uses_pypi_publish_action(self) -> None:
        """Workflow must use pypa/gh-action-pypi-publish."""
        text = (ROOT / ".github" / "workflows" / "pypi-publish.yml").read_text()
        assert "pypa/gh-action-pypi-publish" in text

    def test_has_build_and_publish_jobs(self) -> None:
        """Workflow must have separate build and publish jobs."""
        wf = yaml.safe_load(
            (ROOT / ".github" / "workflows" / "pypi-publish.yml").read_text()
        )
        assert "build" in wf["jobs"]
        assert "publish" in wf["jobs"]

    def test_publish_needs_build(self) -> None:
        """Publish job must depend on build job."""
        wf = yaml.safe_load(
            (ROOT / ".github" / "workflows" / "pypi-publish.yml").read_text()
        )
        publish = wf["jobs"]["publish"]
        assert "build" in publish["needs"]

    def test_publish_has_pypi_environment(self) -> None:
        """Publish job must use the 'pypi' environment."""
        wf = yaml.safe_load(
            (ROOT / ".github" / "workflows" / "pypi-publish.yml").read_text()
        )
        publish = wf["jobs"]["publish"]
        env = publish.get("environment", {})
        assert env.get("name") == "pypi"


class TestReadmeLinks:
    """Validate that readme.md links resolve when rendered on PyPI.

    PyPI renders ``readme.md`` standalone, so any markdown link with a
    relative filesystem path 404s on the project page. Links must either
    be absolute URLs or in-document anchors (issue #145).
    """

    # Matches the second group of `[text](target)` while skipping image
    # links and code spans. Captures the target only.
    _LINK_RE = re.compile(r"(?<!\!)\[[^\]]+\]\(([^)]+)\)")

    @staticmethod
    def _readme_links() -> list[str]:
        text = (ROOT / "readme.md").read_text()
        return TestReadmeLinks._LINK_RE.findall(text)

    def test_readme_has_no_relative_filesystem_links(self) -> None:
        """Every readme link must be an absolute URL or in-document anchor."""
        bad = [
            target
            for target in self._readme_links()
            if not (target.startswith(("http://", "https://", "mailto:", "#")))
        ]
        assert not bad, (
            "readme.md contains relative links that 404 on PyPI; convert "
            f"them to absolute https://github.com/... URLs: {bad}"
        )
