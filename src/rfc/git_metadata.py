"""Platform-agnostic Git/CI metadata collection.

Detects whether we're running in GitHub Actions and collects the
appropriate environment variables into a canonical dictionary. Used
by the GitMetaData listener, DbListener, and the pre-run modifier.

GitLab CI support was removed (rfc-monorepo #106/#107). Read-side
parsing of historical GitLab-era metadata keys (for re-importing old
``output.xml`` files) lives in ``result_import.py`` and is unaffected.
"""

import os
import subprocess
from datetime import UTC, datetime
from typing import Dict, Optional


def detect_ci_platform() -> Optional[str]:
    """Detect which CI platform is running.

    Returns:
        ``"github"`` for GitHub Actions, or ``None`` when no known
        CI is detected.
    """
    if os.getenv("GITHUB_ACTIONS") == "true":
        return "github"
    return None


def _collect_github_metadata() -> Dict[str, str]:
    """Collect metadata from GitHub Actions environment variables."""
    server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    project_url = f"{server_url}/{repository}" if repository else ""
    sha = os.getenv("GITHUB_SHA", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")

    return {
        "CI": "true",
        "CI_Platform": "github",
        "Project_URL": project_url,
        "Commit_SHA": sha,
        "Commit_Short_SHA": sha[:8] if sha else "",
        "Branch": os.getenv("GITHUB_REF_NAME", ""),
        "Pipeline_ID": run_id,
        # Job information
        "Job_URL": f"{project_url}/actions/runs/{run_id}"
        if project_url and run_id
        else "",
        "Job_ID": os.getenv("GITHUB_RUN_NUMBER", ""),
        "Job_Name": os.getenv("GITHUB_JOB", ""),
        # Pull request information
        "Merge_Request_IID": os.getenv("GITHUB_EVENT_NUMBER", ""),
        # Repository
        "Repository_URL": f"{project_url}.git" if project_url else "",
        "Triggered_By": os.getenv("GITHUB_EVENT_NAME", ""),
        # Environment
        "Test_Environment": os.getenv("GITHUB_ENVIRONMENT", ""),
        "User": os.getenv("GITHUB_ACTOR", ""),
    }


def _git_command(*args: str) -> str:
    """Run a git command and return its stripped stdout.

    Returns an empty string if git is not installed, the working
    directory is not a git repository, or any other error occurs.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def _collect_local_metadata() -> Dict[str, str]:
    """Collect metadata from local git repository.

    Uses ``git rev-parse`` to determine the current branch and commit SHA.
    Falls back gracefully when git is not installed or when running
    outside a git repository.
    """
    branch = _git_command("rev-parse", "--abbrev-ref", "HEAD")
    sha = _git_command("rev-parse", "HEAD")

    return {
        "CI": "false",
        "CI_Platform": "local",
        "Branch": branch,
        "Commit_SHA": sha,
        "Commit_Short_SHA": sha[:8] if sha else "",
    }


def collect_ci_metadata() -> Dict[str, str]:
    """Collect metadata from the current CI environment.

    Auto-detects GitHub Actions and collects the appropriate
    environment variables into a canonical dictionary with
    consistent key names; falls back to local git metadata
    outside CI.

    Returns:
        Dictionary of CI metadata with empty values filtered out.
    """
    platform = detect_ci_platform()

    metadata: Dict[str, str]
    if platform == "github":
        metadata = _collect_github_metadata()
    else:
        metadata = _collect_local_metadata()

    # Common fields (always present regardless of platform)
    metadata["Ollama_Endpoint"] = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
    # No silent fallback: downstream consumers (DbListener, import_test_results)
    # fall through to "unknown". A hardcoded default here would mislabel runs.
    metadata["Default_Model"] = os.getenv("DEFAULT_MODEL", "")
    metadata["Timestamp"] = datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"

    return {k: v for k, v in metadata.items() if v}
