"""Plugin and skill snapshots for the Agentic Stack Tracker.

Captures the environment an agent session runs in: which
robotframework-* / LLM-client packages are installed (plugins), and the
git blob SHA of every Robot ``.resource`` file (skills). Both snapshots
are taken once at ``rfc harness start`` (see harness_cli.py).
"""

import subprocess
from importlib import metadata
from pathlib import Path

from rfc.harness_models import AgenticPlugin, AgenticSkill

PLUGIN_ALLOWLIST = frozenset({"anthropic", "openai", "ollama"})
_PLUGIN_PREFIX = "robotframework"


def should_include_plugin(name: str) -> bool:
    """Return True for robotframework-* packages and allowlisted LLM clients."""
    lowered = name.lower()
    return lowered.startswith(_PLUGIN_PREFIX) or lowered in PLUGIN_ALLOWLIST


def snapshot_plugins(session_id: str, recorded_at: str) -> list[AgenticPlugin]:
    """Snapshot installed packages matching the plugin filter.

    Reads installed distributions via importlib.metadata (equivalent to
    ``pip list`` but without a subprocess).
    """
    plugins: dict[str, AgenticPlugin] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"] or ""
        if not should_include_plugin(name):
            continue
        plugins[name.lower()] = AgenticPlugin(
            session_id=session_id,
            plugin_name=name.lower(),
            recorded_at=recorded_at,
            semver=dist.version,
            source="pip",
        )
    return sorted(plugins.values(), key=lambda p: p.plugin_name)


def _git_blob_sha(repo_root: str, rel_path: str) -> str:
    """Return the blob SHA of ``rel_path`` at HEAD, or "" if untracked."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", f"HEAD:{rel_path}"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=repo_root,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def snapshot_skills(
    session_id: str, recorded_at: str, repo_root: str = "."
) -> list[AgenticSkill]:
    """Snapshot every ``.resource`` file under ``<repo_root>/robot/``.

    Untracked files get an empty ``git_sha`` rather than being dropped,
    so the snapshot still records that the skill existed in the worktree.
    """
    robot_dir = Path(repo_root) / "robot"
    if not robot_dir.is_dir():
        return []
    skills = []
    for resource in sorted(robot_dir.rglob("*.resource")):
        rel_path = resource.relative_to(repo_root).as_posix()
        skills.append(
            AgenticSkill(
                session_id=session_id,
                skill_path=rel_path,
                recorded_at=recorded_at,
                git_sha=_git_blob_sha(repo_root, rel_path),
                skill_name=resource.stem,
            )
        )
    return skills
