"""Shared CI metadata collection for GitLab CI environments.

Used by both the pre-run modifier and the CI metadata listener to avoid
duplicating environment variable collection logic.
"""

import os
from datetime import datetime
from typing import Dict


def collect_ci_metadata() -> Dict[str, str]:
    """Collect metadata from GitLab CI environment variables.

    Returns:
        Dictionary of CI metadata with empty values filtered out.
    """
    metadata = {
        # GitLab CI core
        "CI": os.getenv("CI", "false"),
        "GitLab_URL": os.getenv("CI_PROJECT_URL", ""),
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
        # Test environment
        "Test_Environment": os.getenv("CI_ENVIRONMENT_NAME", ""),
        "User": os.getenv("GITLAB_USER_LOGIN", ""),
        # Model information
        "Ollama_Endpoint": os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434"),
        "Default_Model": os.getenv("DEFAULT_MODEL", "llama3"),
        # Timestamp
        "Timestamp": datetime.utcnow().isoformat() + "Z",
    }

    return {k: v for k, v in metadata.items() if v}
