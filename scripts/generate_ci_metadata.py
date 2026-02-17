"""Generate CI metadata JSON file.

Auto-detects GitHub Actions or GitLab CI and collects the
appropriate environment variables.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rfc import __version__
from rfc.git_metadata import detect_ci_platform

platform = detect_ci_platform()

if platform == "github":
    server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    project_url = f"{server_url}/{repository}" if repository else ""
    sha = os.getenv("GITHUB_SHA", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    ci_data = {
        "project_url": project_url,
        "commit_sha": sha,
        "commit_short_sha": sha[:8] if sha else "",
        "branch": os.getenv("GITHUB_REF_NAME", ""),
        "pipeline_url": f"{project_url}/actions/runs/{run_id}"
        if project_url and run_id
        else "",
        "job_url": f"{project_url}/actions/runs/{run_id}"
        if project_url and run_id
        else "",
        "job_id": os.getenv("GITHUB_RUN_NUMBER", ""),
    }
    runner_data = {
        "id": os.getenv("RUNNER_NAME", ""),
        "description": os.getenv("RUNNER_OS", ""),
        "tags": "",
    }
else:
    ci_data = {
        "project_url": os.getenv("CI_PROJECT_URL", ""),
        "commit_sha": os.getenv("CI_COMMIT_SHA", ""),
        "commit_short_sha": os.getenv("CI_COMMIT_SHORT_SHA", ""),
        "branch": os.getenv("CI_COMMIT_REF_NAME", ""),
        "pipeline_url": os.getenv("CI_PIPELINE_URL", ""),
        "job_url": os.getenv("CI_JOB_URL", ""),
        "job_id": os.getenv("CI_JOB_ID", ""),
    }
    runner_data = {
        "id": os.getenv("CI_RUNNER_ID", ""),
        "description": os.getenv("CI_RUNNER_DESCRIPTION", ""),
        "tags": os.getenv("CI_RUNNER_TAGS", ""),
    }

data = {
    "version": __version__,
    "ci_platform": platform or "unknown",
    "ci": ci_data,
    "runner": runner_data,
    "ollama": {
        "endpoint": os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434"),
        "default_model": os.getenv("DEFAULT_MODEL", "gpt-oss:20b"),
    },
    "timestamp": datetime.utcnow().isoformat() + "Z",
}

os.makedirs("results/combined", exist_ok=True)
with open("results/combined/ci_metadata.json", "w") as f:
    json.dump(data, f, indent=2)

print("Metadata generated")
