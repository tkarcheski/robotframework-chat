"""Collect the git commit DAG for visualization.

Walks the repository's commit graph — all branches, full history by default —
and returns one :class:`~rfc.test_database.CommitGraphNode` per commit, each
carrying its parent SHAs so a downstream consumer can reconstruct the edges.
Feeds the ``commit_graph`` / ``commit_edges`` tables that Superset renders as
a tree.

Two entry points:

* :func:`walk_commit_graph` — the git-invoking walker (backfill + incremental).
* :func:`parse_commit_log` — the pure parser, split out so it is unit-testable
  without a repository.

The parser is deliberately separate from I/O: subprocess failures (git absent,
not a repo) degrade to an empty list rather than raising, matching the
skip-and-log contract for optional/external dependencies.
"""

import subprocess
from typing import List, Optional

from .test_database import CommitGraphNode

# ASCII unit/record separators. git commit metadata never contains 0x1f/0x1e,
# so a subject with spaces, pipes, commas or other punctuation still parses
# unambiguously — unlike a comma/pipe/tab-delimited format.
_FIELD_SEP = "\x1f"
_RECORD_SEP = "\x1e"

# %H sha, %P parent shas (space-separated), %an author, %ae email,
# %aI author date (strict ISO-8601), %D ref names, %s subject.
_LOG_FORMAT = (
    _FIELD_SEP.join(["%H", "%P", "%an", "%ae", "%aI", "%D", "%s"]) + _RECORD_SEP
)


def parse_commit_log(raw: str) -> List[CommitGraphNode]:
    """Parse ``git log`` output formatted with :data:`_LOG_FORMAT`.

    Records are split on the ASCII record separator and fields on the unit
    separator. Malformed or empty records are skipped rather than raising.
    """
    nodes: List[CommitGraphNode] = []
    for record in raw.split(_RECORD_SEP):
        record = record.strip("\n")
        if not record:
            continue
        fields = record.split(_FIELD_SEP)
        if len(fields) < 7:
            continue
        sha, parents, author, author_email, timestamp, refs, subject = fields[:7]
        parent_shas = parents.split()
        nodes.append(
            CommitGraphNode(
                sha=sha,
                parent_shas=parent_shas,
                author=author,
                author_email=author_email,
                commit_timestamp=timestamp,
                subject=subject,
                refs=refs.strip(),
                is_merge=len(parent_shas) > 1,
            )
        )
    return nodes


def _run_git(args: List[str], cwd: Optional[str], timeout: float) -> str:
    """Run a git command, returning stdout or ``""`` on any failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        if result.returncode == 0:
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def walk_commit_graph(
    *,
    all_refs: bool = True,
    limit: Optional[int] = None,
    ref: Optional[str] = None,
    cwd: Optional[str] = None,
    timeout: float = 30.0,
) -> List[CommitGraphNode]:
    """Walk the repository's commit graph into ``CommitGraphNode`` rows.

    Args:
        all_refs: Include every branch/tag (``git log --all``). Ignored when
            ``ref`` is given.
        limit: Cap the number of commits (``-n``). ``None`` = full history.
        ref: Walk from a specific ref/SHA instead of ``--all`` — used for the
            per-run incremental capture (``ref=HEAD``, small ``limit``).
        cwd: Repository directory. Defaults to the process working directory.
        timeout: Per-invocation git timeout in seconds.

    Returns an empty list when git is unavailable or ``cwd`` is not a repo.
    """
    args = ["log", f"--pretty=format:{_LOG_FORMAT}"]
    if limit is not None:
        args += ["-n", str(limit)]
    if ref:
        args.append(ref)
    elif all_refs:
        args.append("--all")
    return parse_commit_log(_run_git(args, cwd=cwd, timeout=timeout))
