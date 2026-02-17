"""Tests for scripts/generate_ci_metadata.py — CI metadata generation.

Since this script runs code at module level (not inside ``if __name__``),
we test it by invoking it as a subprocess with controlled environment
variables and verifying the generated JSON output.
"""

import json
import os
import subprocess
import sys


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_PROJECT_ROOT, "scripts", "generate_ci_metadata.py")


def _clean_env(**overrides) -> dict:
    """Return a copy of os.environ with CI vars stripped, then overrides applied."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CI_", "GITLAB_", "GITHUB_", "RUNNER_"))}
    env.update(overrides)
    return env


def _run_script(tmp_path, env):
    result = subprocess.run(
        [sys.executable, _SCRIPT],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result


class TestGitHubPlatform:
    def test_github_metadata(self, tmp_path):
        env = _clean_env(
            GITHUB_ACTIONS="true",
            GITHUB_SERVER_URL="https://github.com",
            GITHUB_REPOSITORY="org/repo",
            GITHUB_SHA="abc12345def67890abc12345def67890abcd1234",
            GITHUB_RUN_ID="12345",
            GITHUB_REF_NAME="main",
            GITHUB_RUN_NUMBER="42",
            RUNNER_NAME="ubuntu-latest",
            RUNNER_OS="Linux",
            OLLAMA_ENDPOINT="http://my-ollama:11434",
            DEFAULT_MODEL="mistral",
        )
        result = _run_script(tmp_path, env)
        assert result.returncode == 0, result.stderr
        assert "Metadata generated" in result.stdout

        meta_path = tmp_path / "results" / "combined" / "ci_metadata.json"
        assert meta_path.exists()
        data = json.loads(meta_path.read_text())

        assert data["ci_platform"] == "github"
        assert data["ci"]["project_url"] == "https://github.com/org/repo"
        assert data["ci"]["commit_sha"] == "abc12345def67890abc12345def67890abcd1234"
        assert data["ci"]["commit_short_sha"] == "abc12345"
        assert data["ci"]["branch"] == "main"
        assert data["ci"]["job_id"] == "42"
        assert "actions/runs/12345" in data["ci"]["pipeline_url"]
        assert data["runner"]["id"] == "ubuntu-latest"
        assert data["runner"]["description"] == "Linux"
        assert data["ollama"]["endpoint"] == "http://my-ollama:11434"
        assert data["ollama"]["default_model"] == "mistral"
        assert "version" in data
        assert data["timestamp"].endswith("Z")

    def test_github_empty_repository(self, tmp_path):
        env = _clean_env(
            GITHUB_ACTIONS="true",
            GITHUB_SHA="",
            GITHUB_REPOSITORY="",
            GITHUB_RUN_ID="",
        )
        result = _run_script(tmp_path, env)
        assert result.returncode == 0, result.stderr

        data = json.loads(
            (tmp_path / "results" / "combined" / "ci_metadata.json").read_text()
        )
        assert data["ci_platform"] == "github"
        assert data["ci"]["project_url"] == ""
        assert data["ci"]["commit_short_sha"] == ""
        assert data["ci"]["pipeline_url"] == ""


class TestGitLabPlatform:
    def test_gitlab_metadata(self, tmp_path):
        env = _clean_env(
            GITLAB_CI="true",
            CI_PROJECT_URL="https://gitlab.example.com/group/project",
            CI_COMMIT_SHA="deadbeefcafe1234",
            CI_COMMIT_SHORT_SHA="deadbeef",
            CI_COMMIT_REF_NAME="develop",
            CI_PIPELINE_URL="https://gitlab.example.com/group/project/pipelines/999",
            CI_JOB_URL="https://gitlab.example.com/group/project/-/jobs/1234",
            CI_JOB_ID="1234",
            CI_RUNNER_ID="77",
            CI_RUNNER_DESCRIPTION="shared-runner",
            CI_RUNNER_TAGS="docker,linux",
        )
        result = _run_script(tmp_path, env)
        assert result.returncode == 0, result.stderr

        data = json.loads(
            (tmp_path / "results" / "combined" / "ci_metadata.json").read_text()
        )
        assert data["ci_platform"] == "gitlab"
        assert data["ci"]["project_url"] == "https://gitlab.example.com/group/project"
        assert data["ci"]["commit_sha"] == "deadbeefcafe1234"
        assert data["ci"]["commit_short_sha"] == "deadbeef"
        assert data["ci"]["branch"] == "develop"
        assert data["ci"]["job_id"] == "1234"
        assert data["runner"]["id"] == "77"
        assert data["runner"]["description"] == "shared-runner"
        assert data["runner"]["tags"] == "docker,linux"


class TestNoPlatform:
    def test_unknown_platform(self, tmp_path):
        env = _clean_env()
        result = _run_script(tmp_path, env)
        assert result.returncode == 0, result.stderr

        data = json.loads(
            (tmp_path / "results" / "combined" / "ci_metadata.json").read_text()
        )
        assert data["ci_platform"] == "unknown"
        # Falls into the GitLab (else) branch with empty env vars
        assert data["ci"]["commit_sha"] == ""


class TestDefaults:
    def test_ollama_defaults(self, tmp_path):
        env = _clean_env()
        # Don't set OLLAMA_ENDPOINT or DEFAULT_MODEL
        env.pop("OLLAMA_ENDPOINT", None)
        env.pop("DEFAULT_MODEL", None)
        result = _run_script(tmp_path, env)
        assert result.returncode == 0, result.stderr

        data = json.loads(
            (tmp_path / "results" / "combined" / "ci_metadata.json").read_text()
        )
        assert data["ollama"]["endpoint"] == "http://localhost:11434"
        assert data["ollama"]["default_model"] == "llama3"

    def test_creates_output_directory(self, tmp_path):
        env = _clean_env()
        # Verify the directory doesn't exist before running
        assert not (tmp_path / "results").exists()
        result = _run_script(tmp_path, env)
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "results" / "combined" / "ci_metadata.json").exists()
