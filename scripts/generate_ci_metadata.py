"""Generate CI metadata JSON file."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rfc import __version__

data = {
    "version": __version__,
    "gitlab": {
        "project_url": os.getenv("CI_PROJECT_URL", ""),
        "commit_sha": os.getenv("CI_COMMIT_SHA", ""),
        "commit_short_sha": os.getenv("CI_COMMIT_SHORT_SHA", ""),
        "branch": os.getenv("CI_COMMIT_REF_NAME", ""),
        "pipeline_url": os.getenv("CI_PIPELINE_URL", ""),
        "job_url": os.getenv("CI_JOB_URL", ""),
        "job_id": os.getenv("CI_JOB_ID", ""),
    },
    "runner": {
        "id": os.getenv("CI_RUNNER_ID", ""),
        "description": os.getenv("CI_RUNNER_DESCRIPTION", ""),
        "tags": os.getenv("CI_RUNNER_TAGS", ""),
    },
    "ollama": {
        "endpoint": os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434"),
        "default_model": os.getenv("DEFAULT_MODEL", "llama3"),
    },
    "timestamp": datetime.utcnow().isoformat() + "Z",
}

os.makedirs("results/combined", exist_ok=True)
with open("results/combined/ci_metadata.json", "w") as f:
    json.dump(data, f, indent=2)

print("Metadata generated")
