"""Sync CI pipeline test artifacts to the database.

Fetches output.xml artifacts from recent GitLab CI pipeline jobs
and imports them into the test database (PostgreSQL/Superset).

Reuses:
  - GitLab API patterns from dashboard/monitoring.py
  - Import logic from scripts/import_test_results.py
  - Database from src/rfc/test_database.py

Environment variables:
  GITLAB_API_URL     - GitLab instance base URL
  GITLAB_PROJECT_ID  - Numeric project ID
  GITLAB_TOKEN       - API token with read_api scope
  DATABASE_URL       - PostgreSQL connection string (for Superset)
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

import requests

# Add src and scripts to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from import_test_results import import_results
from rfc.test_database import TestDatabase


class GitLabArtifactFetcher:
    """Fetch pipeline artifacts from the GitLab API.

    Resolution priority for GitLab settings:
    1. Explicit constructor parameters
    2. CI_API_V4_URL / CI_PROJECT_ID (inside GitLab CI)
    3. GITLAB_API_URL / GITLAB_PROJECT_ID env vars
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        project_id: Optional[str] = None,
        token: Optional[str] = None,
    ) -> None:
        self._api_url, self._project_id, self._token = self._resolve_settings(
            api_url, project_id, token
        )
        if not self._api_url or not self._project_id:
            raise ValueError(
                "GitLab API URL and project ID are required. "
                "Set GITLAB_API_URL/GITLAB_PROJECT_ID env vars, "
                "or pass api_url/project_id to constructor."
            )

    def _resolve_settings(
        self,
        api_url: Optional[str],
        project_id: Optional[str],
        token: Optional[str],
    ) -> tuple[str, str, str]:
        """Resolve GitLab API settings from params or environment."""
        # Explicit params take priority
        resolved_token = (
            token if token is not None else os.environ.get("GITLAB_TOKEN", "")
        )
        if api_url and project_id:
            return api_url.rstrip("/"), project_id, resolved_token

        # CI_API_V4_URL / CI_PROJECT_ID (inside GitLab CI)
        ci_api = os.environ.get("CI_API_V4_URL", "")
        ci_pid = os.environ.get("CI_PROJECT_ID", "")
        if ci_api and ci_pid:
            # CI_API_V4_URL is like https://gitlab.example.com/api/v4
            base_url = ci_api.rsplit("/api/v4", 1)[0]
            return base_url, ci_pid, resolved_token

        # GITLAB_API_URL / GITLAB_PROJECT_ID env vars
        env_api = os.environ.get("GITLAB_API_URL", "")
        env_pid = os.environ.get("GITLAB_PROJECT_ID", "")
        if env_api and env_pid:
            return env_api.rstrip("/"), env_pid, resolved_token

        return "", "", resolved_token

    def _headers(self) -> dict[str, str]:
        """Build HTTP headers for GitLab API requests."""
        headers: dict[str, str] = {}
        if self._token:
            headers["PRIVATE-TOKEN"] = self._token
        return headers

    def fetch_recent_pipelines(
        self,
        ref: Optional[str] = None,
        status: str = "success",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch recent pipelines from GitLab API.

        Args:
            ref: Optional branch filter.
            status: Pipeline status filter (default: success).
            limit: Maximum number of pipelines to return.

        Returns:
            List of pipeline dictionaries.
        """
        url = (
            f"{self._api_url}/api/v4/projects/{self._project_id}"
            f"/pipelines?status={status}&per_page={limit}"
            f"&order_by=updated_at&sort=desc"
        )
        if ref:
            url += f"&ref={ref}"

        try:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException:
            return []

    def fetch_pipeline_jobs(
        self,
        pipeline_id: int,
        scope: str = "success",
    ) -> list[dict[str, Any]]:
        """Fetch jobs from a specific pipeline.

        Args:
            pipeline_id: GitLab pipeline ID.
            scope: Job scope filter (default: success).

        Returns:
            List of job dictionaries.
        """
        url = (
            f"{self._api_url}/api/v4/projects/{self._project_id}"
            f"/pipelines/{pipeline_id}/jobs?scope[]={scope}&per_page=100"
        )

        try:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException:
            return []

    def download_job_artifact(
        self,
        job_id: int,
        output_dir: str,
        artifact_path: str = "output.xml",
    ) -> Optional[str]:
        """Download a specific artifact file from a job.

        Args:
            job_id: GitLab job ID.
            output_dir: Directory to save the artifact.
            artifact_path: Path within artifacts archive (default: output.xml).

        Returns:
            Path to downloaded file, or None if not found.
        """
        url = (
            f"{self._api_url}/api/v4/projects/{self._project_id}"
            f"/jobs/{job_id}/artifacts/{artifact_path}"
        )

        try:
            resp = requests.get(url, headers=self._headers(), timeout=60)
            resp.raise_for_status()
        except requests.exceptions.RequestException:
            return None

        out_path = os.path.join(output_dir, f"job_{job_id}_{artifact_path}")
        with open(out_path, "wb") as f:
            f.write(resp.content)
        return out_path


def sync_ci_results(
    fetcher: GitLabArtifactFetcher,
    db: TestDatabase,
    pipeline_limit: int = 5,
    ref: Optional[str] = None,
) -> dict[str, Any]:
    """Fetch recent CI pipeline artifacts and import into database.

    Args:
        fetcher: Configured GitLab API client.
        db: Database instance.
        pipeline_limit: Number of recent pipelines to process.
        ref: Optional branch filter.

    Returns:
        Dictionary with sync results.
    """
    result: dict[str, Any] = {
        "pipelines_checked": 0,
        "artifacts_downloaded": 0,
        "runs_imported": 0,
        "errors": [],
    }

    pipelines = fetcher.fetch_recent_pipelines(
        ref=ref, status="success", limit=pipeline_limit
    )

    # Get existing pipeline URLs to avoid duplicates
    recent_runs = db.get_recent_runs(limit=100)
    existing_urls = {run.get("gitlab_pipeline_url", "") for run in recent_runs if run}

    with tempfile.TemporaryDirectory() as tmpdir:
        for pipeline in pipelines:
            result["pipelines_checked"] += 1
            pipeline_url = pipeline.get("web_url", "")

            # Skip already-imported pipelines
            if pipeline_url and pipeline_url in existing_urls:
                continue

            pipeline_id = pipeline["id"]
            jobs = fetcher.fetch_pipeline_jobs(pipeline_id)

            for job in jobs:
                job_id = job["id"]
                xml_path = fetcher.download_job_artifact(
                    job_id=job_id, output_dir=tmpdir
                )
                if xml_path is None:
                    continue

                result["artifacts_downloaded"] += 1

                try:
                    import_results(xml_path, db)
                    result["runs_imported"] += 1
                except Exception as e:
                    result["errors"].append(f"Failed to import job {job_id}: {e}")

    return result


def verify_sync(db: TestDatabase, min_runs: int = 1) -> dict[str, Any]:
    """Verify that data was successfully synced to the database.

    Args:
        db: Database instance to verify.
        min_runs: Minimum number of recent runs expected.

    Returns:
        Dictionary with verification results.
    """
    recent = db.get_recent_runs(limit=min_runs)
    models_found = list({run["model_name"] for run in recent if run.get("model_name")})
    latest_ts = recent[0]["timestamp"] if recent else None

    return {
        "success": len(recent) >= min_runs,
        "recent_runs": len(recent),
        "latest_timestamp": str(latest_ts) if latest_ts else None,
        "models_found": models_found,
    }


def main() -> None:
    """CLI entry point for CI pipeline sync."""
    parser = argparse.ArgumentParser(
        description="Sync CI pipeline test results to database"
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=5,
        help="Number of recent pipelines to sync (default: 5)",
    )
    parser.add_argument(
        "--ref",
        help="Filter pipelines by branch (default: all branches)",
    )
    parser.add_argument(
        "--db",
        help="Database path (default: from DATABASE_URL env var)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify database contents, don't sync",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be synced without importing",
    )

    args = parser.parse_args()

    # Initialize database
    if args.db:
        db = TestDatabase(db_path=args.db)
    else:
        db = TestDatabase()

    if args.verify_only:
        result = verify_sync(db)
        print(f"Database verification: {'PASS' if result['success'] else 'FAIL'}")
        print(f"  Recent runs: {result['recent_runs']}")
        print(f"  Latest timestamp: {result['latest_timestamp']}")
        print(f"  Models found: {', '.join(result['models_found'])}")
        sys.exit(0 if result["success"] else 1)

    # Initialize fetcher
    try:
        fetcher = GitLabArtifactFetcher()
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    if args.dry_run:
        pipelines = fetcher.fetch_recent_pipelines(ref=args.ref, limit=args.limit)
        print(f"Would sync {len(pipelines)} pipeline(s):")
        for p in pipelines:
            print(
                f"  Pipeline #{p['id']} ({p.get('ref', '?')}) - {p.get('web_url', '')}"
            )
        sys.exit(0)

    # Run sync
    result = sync_ci_results(fetcher, db, pipeline_limit=args.limit, ref=args.ref)

    print("Sync complete:")
    print(f"  Pipelines checked: {result['pipelines_checked']}")
    print(f"  Artifacts downloaded: {result['artifacts_downloaded']}")
    print(f"  Runs imported: {result['runs_imported']}")
    if result["errors"]:
        print(f"  Errors ({len(result['errors'])}):")
        for err in result["errors"]:
            print(f"    - {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
