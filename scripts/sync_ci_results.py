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
import logging
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

_log = logging.getLogger(__name__)


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
        if api_url and project_id:
            resolved_token = token or os.environ.get("GITLAB_TOKEN", "")
            return api_url.rstrip("/"), project_id, resolved_token

        # CI_API_V4_URL / CI_PROJECT_ID (inside GitLab CI)
        ci_api = os.environ.get("CI_API_V4_URL", "")
        ci_pid = os.environ.get("CI_PROJECT_ID", "")
        if ci_api and ci_pid:
            # CI_API_V4_URL is like https://gitlab.example.com/api/v4
            base_url = ci_api.rsplit("/api/v4", 1)[0]
            resolved_token = token or os.environ.get("GITLAB_TOKEN", "")
            return base_url, ci_pid, resolved_token

        # GITLAB_API_URL / GITLAB_PROJECT_ID env vars
        env_api = os.environ.get("GITLAB_API_URL", "")
        env_pid = os.environ.get("GITLAB_PROJECT_ID", "")
        if env_api and env_pid:
            resolved_token = token or os.environ.get("GITLAB_TOKEN", "")
            return env_api.rstrip("/"), env_pid, resolved_token

        return "", "", token or ""

    @property
    def api_url(self) -> str:
        """The resolved GitLab base URL."""
        return self._api_url

    @property
    def project_id(self) -> str:
        """The resolved GitLab project ID."""
        return self._project_id

    @property
    def has_token(self) -> bool:
        """Whether an API token is configured."""
        return bool(self._token)

    def _headers(self) -> dict[str, str]:
        """Build HTTP headers for GitLab API requests."""
        headers: dict[str, str] = {}
        if self._token:
            headers["PRIVATE-TOKEN"] = self._token
        return headers

    def check_connection(self) -> dict[str, Any]:
        """Test connectivity to the GitLab API.

        Returns:
            Dictionary with connection status and details.
        """
        url = f"{self._api_url}/api/v4/projects/{self._project_id}"
        result: dict[str, Any] = {
            "ok": False,
            "api_url": self._api_url,
            "project_id": self._project_id,
            "has_token": bool(self._token),
            "error": None,
            "project_name": None,
        }
        try:
            resp = requests.get(url, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            data = resp.json()
            result["ok"] = True
            result["project_name"] = data.get("path_with_namespace", "")
        except requests.exceptions.ConnectionError:
            result["error"] = f"Cannot connect to {self._api_url}"
        except requests.exceptions.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            if code == 401:
                result["error"] = "Authentication failed (check GITLAB_TOKEN)"
            elif code == 404:
                result["error"] = f"Project {self._project_id} not found"
            else:
                result["error"] = f"HTTP {code}"
        except requests.exceptions.RequestException as exc:
            result["error"] = str(exc)
        return result

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
        except requests.exceptions.RequestException as exc:
            _log.warning("Failed to fetch pipelines: %s", exc)
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
        except requests.exceptions.RequestException as exc:
            _log.warning("Failed to fetch jobs for pipeline %s: %s", pipeline_id, exc)
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
        except requests.exceptions.RequestException as exc:
            _log.debug("No artifact %s for job %s: %s", artifact_path, job_id, exc)
            return None

        safe_name = artifact_path.replace("/", "_")
        out_path = os.path.join(output_dir, f"job_{job_id}_{safe_name}")
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
    existing_urls = {run.get("pipeline_url", "") for run in recent_runs if run}

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


def _make_fetcher() -> GitLabArtifactFetcher:
    """Create a GitLabArtifactFetcher, exiting on config errors."""
    try:
        return GitLabArtifactFetcher()
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)


def _make_db(db_path: Optional[str] = None) -> TestDatabase:
    """Create a TestDatabase from CLI args or environment."""
    if db_path:
        return TestDatabase(db_path=db_path)
    return TestDatabase()


# -- Subcommand handlers ----------------------------------------------------


def cmd_status(args: argparse.Namespace) -> None:
    """Show GitLab connection status and configuration."""
    fetcher = _make_fetcher()
    info = fetcher.check_connection()
    print("GitLab CI Status")
    print(f"  API URL:     {info['api_url']}")
    print(f"  Project ID:  {info['project_id']}")
    print(f"  Token:       {'configured' if info['has_token'] else 'NOT SET'}")
    print(f"  Connection:  {'OK' if info['ok'] else 'FAILED'}")
    if info["project_name"]:
        print(f"  Project:     {info['project_name']}")
    if info["error"]:
        print(f"  Error:       {info['error']}")
    sys.exit(0 if info["ok"] else 1)


def cmd_list_pipelines(args: argparse.Namespace) -> None:
    """List recent pipelines from GitLab."""
    fetcher = _make_fetcher()
    pipelines = fetcher.fetch_recent_pipelines(
        ref=args.ref, status=args.status, limit=args.limit
    )
    if not pipelines:
        print("No pipelines found.")
        sys.exit(0)
    print(f"{'ID':<12} {'Status':<10} {'Branch':<20} {'SHA':<10} URL")
    print("-" * 80)
    for p in pipelines:
        print(
            f"{p['id']:<12} {p.get('status', '?'):<10} "
            f"{p.get('ref', '?'):<20} {p.get('sha', '?')[:8]:<10} "
            f"{p.get('web_url', '')}"
        )


def cmd_list_jobs(args: argparse.Namespace) -> None:
    """List jobs from a specific pipeline."""
    fetcher = _make_fetcher()
    jobs = fetcher.fetch_pipeline_jobs(
        pipeline_id=args.pipeline_id, scope=args.scope
    )
    if not jobs:
        print(f"No jobs found for pipeline {args.pipeline_id}.")
        sys.exit(0)
    print(f"{'Job ID':<12} {'Name':<25} {'Status':<10} {'Duration':<10}")
    print("-" * 60)
    for j in jobs:
        dur = j.get("duration")
        dur_str = f"{dur:.0f}s" if dur else "-"
        print(
            f"{j['id']:<12} {j.get('name', '?'):<25} "
            f"{j.get('status', '?'):<10} {dur_str:<10}"
        )


def cmd_fetch_artifact(args: argparse.Namespace) -> None:
    """Download an artifact from a specific job."""
    fetcher = _make_fetcher()
    output_dir = args.output_dir or "."
    os.makedirs(output_dir, exist_ok=True)
    path = fetcher.download_job_artifact(
        job_id=args.job_id,
        output_dir=output_dir,
        artifact_path=args.artifact_path,
    )
    if path:
        print(f"Downloaded: {path}")
    else:
        print(f"Artifact '{args.artifact_path}' not found for job {args.job_id}.")
        sys.exit(1)


def cmd_sync(args: argparse.Namespace) -> None:
    """Sync recent pipeline artifacts into the database."""
    fetcher = _make_fetcher()
    db = _make_db(args.db)

    if args.dry_run:
        pipelines = fetcher.fetch_recent_pipelines(ref=args.ref, limit=args.limit)
        print(f"Would sync {len(pipelines)} pipeline(s):")
        for p in pipelines:
            print(
                f"  Pipeline #{p['id']} ({p.get('ref', '?')}) "
                f"- {p.get('web_url', '')}"
            )
        sys.exit(0)

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


def cmd_verify(args: argparse.Namespace) -> None:
    """Verify database contents after sync."""
    db = _make_db(args.db)
    result = verify_sync(db)
    print(f"Database verification: {'PASS' if result['success'] else 'FAIL'}")
    print(f"  Recent runs: {result['recent_runs']}")
    print(f"  Latest timestamp: {result['latest_timestamp']}")
    print(f"  Models found: {', '.join(result['models_found'])}")
    sys.exit(0 if result["success"] else 1)


def main() -> None:
    """CLI entry point for CI pipeline sync."""
    parser = argparse.ArgumentParser(
        description="GitLab CI artifact sync tools",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    sub = parser.add_subparsers(dest="command")

    # -- status ---------------------------------------------------------------
    sub.add_parser("status", help="Check GitLab connection and configuration")

    # -- list-pipelines -------------------------------------------------------
    lp = sub.add_parser("list-pipelines", help="List recent GitLab pipelines")
    lp.add_argument("-n", "--limit", type=int, default=10, help="Max pipelines")
    lp.add_argument("--ref", help="Filter by branch")
    lp.add_argument(
        "--status", default="success", help="Pipeline status filter (default: success)"
    )

    # -- list-jobs ------------------------------------------------------------
    lj = sub.add_parser("list-jobs", help="List jobs from a pipeline")
    lj.add_argument("pipeline_id", type=int, help="Pipeline ID")
    lj.add_argument(
        "--scope", default="success", help="Job scope filter (default: success)"
    )

    # -- fetch-artifact -------------------------------------------------------
    fa = sub.add_parser("fetch-artifact", help="Download a job artifact")
    fa.add_argument("job_id", type=int, help="Job ID")
    fa.add_argument(
        "--artifact-path", default="output.xml", help="Path within archive"
    )
    fa.add_argument("-o", "--output-dir", help="Output directory (default: .)")

    # -- sync (default) -------------------------------------------------------
    sy = sub.add_parser("sync", help="Sync pipeline artifacts to database")
    sy.add_argument("-n", "--limit", type=int, default=5, help="Pipelines to sync")
    sy.add_argument("--ref", help="Filter by branch")
    sy.add_argument("--db", help="Database path override")
    sy.add_argument("--dry-run", action="store_true", help="Show what would sync")

    # -- verify ---------------------------------------------------------------
    ve = sub.add_parser("verify", help="Verify database contents")
    ve.add_argument("--db", help="Database path override")

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level, format="%(levelname)s: %(message)s", stream=sys.stderr
    )

    # Dispatch to subcommand (default: sync for backward compat)
    handlers = {
        "status": cmd_status,
        "list-pipelines": cmd_list_pipelines,
        "list-jobs": cmd_list_jobs,
        "fetch-artifact": cmd_fetch_artifact,
        "sync": cmd_sync,
        "verify": cmd_verify,
    }

    if args.command is None:
        # Backward compatibility: no subcommand = old-style flags
        # Re-parse with legacy argument set
        legacy = argparse.ArgumentParser(description="Sync CI results (legacy)")
        legacy.add_argument("-v", "--verbose", action="store_true")
        legacy.add_argument("-n", "--limit", type=int, default=5)
        legacy.add_argument("--ref")
        legacy.add_argument("--db")
        legacy.add_argument("--verify-only", action="store_true")
        legacy.add_argument("--dry-run", action="store_true")
        args = legacy.parse_args()

        level = logging.DEBUG if args.verbose else logging.WARNING
        logging.basicConfig(
            level=level, format="%(levelname)s: %(message)s", stream=sys.stderr
        )

        if args.verify_only:
            args.command = "verify"
            cmd_verify(args)
        else:
            args.command = "sync"
            cmd_sync(args)
    else:
        handlers[args.command](args)


if __name__ == "__main__":
    main()
