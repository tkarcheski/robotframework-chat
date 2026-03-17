"""Platform-agnostic Git/CI metadata collection.

Detects whether we're running in GitHub Actions or GitLab CI and
collects the appropriate environment variables into a canonical
dictionary. Used by the GitMetaData listener, DbListener, and
the pre-run modifier.
"""

import os
import subprocess
from datetime import UTC, datetime
from typing import Dict, Optional


def detect_ci_platform() -> Optional[str]:
    """Detect which CI platform is running.

    Returns:
        ``"github"`` for GitHub Actions, ``"gitlab"`` for GitLab CI,
        or ``None`` when no known CI is detected.
    """
    if os.getenv("GITHUB_ACTIONS") == "true":
        return "github"
    if os.getenv("GITLAB_CI") == "true":
        return "gitlab"
    return None


def _collect_gitlab_metadata() -> Dict[str, str]:
    """Collect metadata from GitLab CI environment variables."""
    return {
        "CI": os.getenv("CI", "false"),
        "CI_Platform": "gitlab",
        "Project_URL": os.getenv("CI_PROJECT_URL", ""),
        "Commit_SHA": os.getenv("CI_COMMIT_SHA", ""),
        "Commit_Short_SHA": os.getenv("CI_COMMIT_SHORT_SHA", ""),
        "Branch": os.getenv("CI_COMMIT_REF_NAME", ""),
        "Pipeline_URL": os.getenv("CI_PIPELINE_URL", ""),
        "Pipeline_ID": os.getenv("CI_PIPELINE_ID", ""),
        # Job information
        "Job_URL": os.getenv("CI_JOB_URL", ""),
        "Job_ID": os.getenv("CI_JOB_ID", ""),
        "Job_Name": os.getenv("CI_JOB_NAME", ""),
        # Merge request information
        "Merge_Request_IID": os.getenv("CI_MERGE_REQUEST_IID", ""),
        "Merge_Request_Source_Branch": os.getenv(
            "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME", ""
        ),
        "Merge_Request_Target_Branch": os.getenv(
            "CI_MERGE_REQUEST_TARGET_BRANCH_NAME", ""
        ),
        # Repository
        "Repository_URL": os.getenv("CI_REPOSITORY_URL", ""),
        "Triggered_By": os.getenv("CI_PIPELINE_SOURCE", ""),
        # Runner information
        "Runner_ID": os.getenv("CI_RUNNER_ID", ""),
        "Runner_Description": os.getenv("CI_RUNNER_DESCRIPTION", ""),
        "Runner_Tags": os.getenv("CI_RUNNER_TAGS", ""),
        # Environment
        "Test_Environment": os.getenv("CI_ENVIRONMENT_NAME", ""),
        "User": os.getenv("GITLAB_USER_LOGIN", ""),
    }


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
        "Pipeline_URL": f"{project_url}/actions/runs/{run_id}"
        if project_url and run_id
        else "",
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
        # Runner information
        "Runner_ID": os.getenv("RUNNER_NAME", ""),
        "Runner_Description": os.getenv("RUNNER_OS", ""),
        "Runner_Tags": "",
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

    Auto-detects GitHub Actions or GitLab CI and collects the
    appropriate environment variables into a canonical dictionary
    with consistent key names regardless of platform.

    Returns:
        Dictionary of CI metadata with empty values filtered out.
    """
    platform = detect_ci_platform()

    metadata: Dict[str, str]
    if platform == "github":
        metadata = _collect_github_metadata()
    elif platform == "gitlab":
        metadata = _collect_gitlab_metadata()
    else:
        metadata = _collect_local_metadata()

    # Common fields (always present regardless of platform)
    metadata["Ollama_Endpoint"] = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
    metadata["Default_Model"] = os.getenv("DEFAULT_MODEL", "phi4:14b")
    metadata["Timestamp"] = datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"

    return {k: v for k, v in metadata.items() if v}
