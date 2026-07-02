"""Tests validating MCP (GitHub) tool operations against the local repository.

Covers: get_file_contents, list_branches, list_commits, list_issues,
list_pull_requests, and run_secret_scanning — using local filesystem
and git subprocess calls (no network required).
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
SRC_RFC: Path = REPO_ROOT / "src" / "rfc"


def _git(*args: str) -> str:
    """Run a git command in the repo root and return stripped stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


# ── Repository Discovery (Tests 1-3) ────────────────────────────────────


class TestRepositoryDiscovery:
    """Validate root structure, README, and source module enumeration."""

    def test_root_structure_contains_expected_entries(self) -> None:
        expected = [
            "src",
            "robot",
            "tests",
            "Makefile",
            "docker-compose.yml",
            "readme.md",
        ]
        for name in expected:
            assert (REPO_ROOT / name).exists(), f"Missing root entry: {name}"

    def test_readme_contains_project_description(self) -> None:
        content = (REPO_ROOT / "readme.md").read_text().lower()
        assert "robot framework" in content
        assert "llm" in content

    @pytest.mark.parametrize(
        "module",
        [
            "keywords.py",
            "ollama.py",
            "ceo_keywords.py",
            "safety_keywords.py",
            "db_listener.py",
            "docker_keywords.py",
        ],
    )
    def test_src_rfc_contains_expected_modules(self, module: str) -> None:
        assert (SRC_RFC / module).is_file(), f"Missing module: src/rfc/{module}"


# ── Core Keyword Module Inspection (Tests 4-7) ──────────────────────────


class TestCoreKeywordModules:
    """Validate core keyword library files have expected content."""

    def test_keywords_module_has_rf_definitions(self) -> None:
        path = SRC_RFC / "keywords.py"
        assert path.stat().st_size > 500
        content = path.read_text()
        assert "LLMKeywords" in content

    def test_ceo_keywords_has_orchestration_content(self) -> None:
        content = (SRC_RFC / "ceo_keywords.py").read_text()
        assert "CEOKeywords" in content
        assert re.search(r"def \w+", content)

    def test_ollama_module_references_api(self) -> None:
        content = (SRC_RFC / "ollama.py").read_text()
        assert "OllamaClient" in content

    def test_openai_client_has_setup(self) -> None:
        content = (SRC_RFC / "openai_client.py").read_text()
        assert "OpenAIClient" in content


# ── Safety & Grading Modules (Tests 8-10) ────────────────────────────────


class TestSafetyAndGrading:
    """Validate safety and creativity evaluation modules."""

    def test_safety_keywords_has_grading_keywords(self) -> None:
        content = (SRC_RFC / "safety_keywords.py").read_text()
        assert "SafetyKeywords" in content
        assert re.search(r"def \w+", content)

    def test_safety_grader_has_scoring_logic(self) -> None:
        content = (SRC_RFC / "safety_grader.py").read_text()
        assert "SafetyGrader" in content
        assert "SafetyResult" in content

    def test_creativity_keywords_has_functions(self) -> None:
        content = (SRC_RFC / "creativity_keywords.py").read_text()
        assert "CreativityGrader" in content
        assert "@keyword" in content


# ── CI/CD and Config Files (Tests 11-14) ─────────────────────────────────


class TestCICDAndConfig:
    """Validate environment, Docker, CI, and dependency configuration."""

    def test_env_example_lists_required_vars(self) -> None:
        content = (REPO_ROOT / ".env.example").read_text()
        for var in ("POSTGRES_USER", "POSTGRES_PASSWORD", "DATABASE_HOST"):
            assert var in content, f"Missing env var: {var}"

    def test_docker_compose_has_named_services(self) -> None:
        content = (REPO_ROOT / "docker-compose.yml").read_text()
        assert "services:" in content
        assert "app:" in content
        assert "postgres:" in content

    def test_no_gitlab_ci_file(self) -> None:
        """GitLab CI support was removed at source (rfc-monorepo #106/#107):
        no .gitlab-ci.yml may exist in the repo."""
        assert not (REPO_ROOT / ".gitlab-ci.yml").exists()

    def test_pyproject_lists_robotframework_dependency(self) -> None:
        content = (REPO_ROOT / "pyproject.toml").read_text()
        assert "robotframework" in content


# ── Branch and Commit History (Tests 15-18) ──────────────────────────────


class TestBranchAndCommitHistory:
    """Validate git metadata: branches, commits, and remote configuration."""

    def test_git_has_branches(self) -> None:
        output = _git("branch", "--list")
        assert output, "No git branches found"

    def test_recent_commit_history_exists(self) -> None:
        # Only assert at least one commit is present. Shallow checkouts
        # (e.g. CI jobs using --depth 1) can legitimately have fewer
        # commits than a full clone.
        output = _git("log", "--oneline", "-20")
        lines = [line for line in output.splitlines() if line.strip()]
        assert len(lines) >= 1, "Expected at least one commit in history"

    def test_repo_is_git_repo(self) -> None:
        # Validate this is a git working tree. Remotes are optional — local
        # snapshots, CI worktrees, and forks may have none configured.
        assert _git("rev-parse", "--is-inside-work-tree") == "true"

    def test_remote_url_is_well_formed_when_present(self) -> None:
        # If any remote is configured, its URL should look like a valid
        # git remote (ssh, https, or local path). Skip when no remotes exist
        # so the suite stays portable across forks/mirrors/snapshots.
        remotes = _git("remote").splitlines()
        if not remotes:
            pytest.skip("No git remotes configured")
        url = _git("remote", "get-url", remotes[0])
        assert url, "remote URL should not be empty"
        assert re.match(r"^(https?://|git@|ssh://|git://|file://|/)", url), (
            f"remote URL has unexpected format: {url}"
        )


# ── Secret Scanning (Tests 19-20) ────────────────────────────────────────

# Patterns that indicate real credentials (not placeholders).
_SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI API keys
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),  # GitHub PATs
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key IDs
]


class TestSecretScanning:
    """Scan configuration and source files for accidentally committed secrets."""

    def test_env_example_contains_no_real_secrets(self) -> None:
        content = (REPO_ROOT / ".env.example").read_text()
        for pattern in _SECRET_PATTERNS:
            assert not pattern.search(content), (
                f"Secret pattern found: {pattern.pattern}"
            )

    def test_openai_client_has_no_hardcoded_keys(self) -> None:
        content = (SRC_RFC / "openai_client.py").read_text()
        for pattern in _SECRET_PATTERNS:
            assert not pattern.search(content), (
                f"Secret pattern found: {pattern.pattern}"
            )
