"""Single owned policy for scenario-workspace churn manifests (#248, #231).

A *churn manifest* maps every path in an agent scenario workspace to a content
token, so two manifests (before / after an agent runs) can be diffed to see
exactly what the agent touched -- the "no unexpected churn" gate that keeps the
tier:4 agentic-coding reward signal honest (:mod:`rfc.agent_sandbox`).

Two consumers need this manifest, in two different execution contexts:

* :mod:`rfc.agent_sandbox` -- the container-side grader and the *source of
  truth* for the reward signal. It cannot walk the workspace host-side (the
  workspace lives inside a disposable, network-isolated container), so it runs
  :func:`manifest_command` as a shell command *inside* the container and parses
  the output with :func:`parse_manifest`.
* ``modules/ops/scripts/check_battery_scenarios.py`` -- the host-side CI guard
  that proves each scenario's grader discriminates good from bad. It has no
  Docker daemon, so it walks a seeded copy of the workspace host-side with
  :func:`manifest_from_dir`.

Before this module the two reimplemented the manifest independently and drifted:
the checker followed symlinks and excluded bytecode while the harness omitted
symlinks (``find -type f``) and counted bytecode -- so the checker could bless a
solution the real grader would reject (#231) and the grader was blind to an
out-of-allowlist symlink the checker would have seen (#248). Owning ONE policy
here -- one exclusion rule, one symlink rule -- ends that: :func:`manifest_command`
(shell) and :func:`manifest_from_dir` (Python walk) both apply the *same*
exclusion rule (below), and ``core/tests/test_churn_manifest.py`` pins them
byte-identical -- including on the excluded-name-leaf and hostile-name trees
(#231, #274, #280) that earlier drifted silently.

Exclusion rule (decided once, applied identically by both renderings):

A path is excluded **iff one of its *ancestor* directory components** (every
component except the leaf) is a directory named ``.git`` or ``__pycache__``. In
other words: prune the *contents* of a ``.git`` / ``__pycache__`` directory and
never descend into it, but **record a leaf** (regular file, symlink, or dangling
symlink) whose *own* name is ``.git`` / ``__pycache__`` -- such a leaf is authored
content, not the pruned directory's contents (#280). The shell renders this as
``find ... -not -path '*/.git/*' -not -path '*/__pycache__/*'`` (``-path``
matches only a *non-final* ``.git`` / ``__pycache__`` component); the walk renders
it as "excluded iff any of ``rel.parts[:-1]`` is an excluded dir", pruning only
*real* directories of those names from descent. Same rule, two renderings.

* **``.git`` / ``__pycache__`` directory contents** -- excluded. VCS metadata is
  never an agent artifact; compiled bytecode under ``__pycache__/`` is a
  non-deterministic *byproduct of executing* Python, not a solution the agent
  authored. Counting it would penalise an agent for the legitimate act of
  running/verifying its own code (the live adapter, #288, runs the tests),
  training the reward signal to punish self-verification. Git ignores bytecode
  for exactly this reason.
* **Bytecode outside ``__pycache__/``** (a bare ``*.pyc``) -- **included /
  counted**. CPython 3 always writes byproduct bytecode under ``__pycache__/``;
  a ``.pyc`` *outside* it is only ever produced deliberately (``py_compile`` with
  an explicit ``cfile``, ``compileall -b``) -- i.e. authored, importable content
  (``import evil``), a smuggle surface that must register as churn (#280). It is
  excluded *only* when it lives under ``__pycache__/`` (caught by the ancestor
  rule), never by suffix-anywhere.
* **Symlinks** -- **included**, keyed by ``symlink:<sha256 of the link target
  bytes>`` so both creating a symlink and *retargeting* an existing one register
  as churn, and a regular-file <-> symlink swap at one path registers as churn (a
  ``symlink:``-prefixed value can never collide with a file's bare hex digest).
  The target is *hashed*, never embedded raw, so an attacker-chosen target
  (newline, double-space) cannot inject a delimiter into the manifest text
  (#274). A symlink *named* ``.git`` / ``__pycache__`` is a leaf, so it is
  recorded (not pruned) like any other -- the walk records it in lockstep with
  the shell (#280). ``find -type f`` alone (the old harness) never saw symlinks.
* **Regular files** -- included, keyed by the sha256 of their contents.

The manifest is **NUL-delimited**: every ``<value>  <path>`` record is
terminated by a NUL byte (``sha256sum -z`` and the symlink pass both do this)
and paths are emitted raw, so a newline or backslash in a *path* can never split
a record or be silently escaped on one side only. Combined with hashing the
symlink target, this keeps the shell rendering and the Python walk byte-identical
on hostile names -- the parity pinned by ``core/tests/test_churn_manifest.py``
(#231, #274, #280).

Kept stdlib-only on purpose: the private ``modules/ops`` guard imports this
without dragging in Robot / Docker / yaml, preserving its "runs anywhere,
no daemon" property while ending the duplication.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

# The container mount the scenario repo is seeded into; also the prefix stripped
# from shell-manifest paths so keys are workspace-relative on both renderings.
WORKSPACE = "/workspace"

# The ONE exclusion policy, shared by both renderings: prune the CONTENTS of a
# .git / __pycache__ directory (VCS metadata / bytecode byproduct are not agent
# artifacts -- see the module docstring), but record a LEAF named .git /
# __pycache__ as authored content (#280). A `.pyc` is excluded only when it lives
# under __pycache__/ (an ancestor, caught by the rule), never by suffix-anywhere.
EXCLUDE_DIRS: frozenset[str] = frozenset({".git", "__pycache__"})

# Manifest-value marker for a symlink; the sha256 of the link target follows it
# (hashed, never the raw target -- #274, so an attacker-chosen target cannot
# inject a manifest delimiter). Chosen so a symlink value can never be mistaken
# for a file's bare 64-char hex sha256 digest, which lets a file <-> symlink swap
# at one path read as churn.
SYMLINK_PREFIX = "symlink:"


def _find_predicates() -> str:
    """The shared exclusion rule rendered as ``find`` predicates (sorted, stable).

    ``-path '*/NAME/*'`` matches only when NAME is a *non-final* path component --
    a real ancestor directory with content beneath it -- so a *leaf* named
    ``.git`` / ``__pycache__`` is recorded, matching :func:`_excluded` on the walk
    side (#280). Bytecode under ``__pycache__/`` is excluded by this same rule; a
    ``.pyc`` outside ``__pycache__/`` is authored and counts (no suffix predicate).
    """
    return " ".join(f"-not -path '*/{name}/*'" for name in sorted(EXCLUDE_DIRS))


# The symlink pass hashes each link's target (readlink -> sha256) so no
# attacker-controlled target byte ever reaches the manifest text (#274). POSIX
# sh (dash-compatible): `for l` iterates the batch find hands to `sh -c`, and
# `readlink -n` emits the target with no trailing newline so its sha256 matches
# the host walk's byte-for-byte. printf terminates each record with NUL.
_SYMLINK_HASH_SCRIPT = (
    "for l; do "
    'printf "' + SYMLINK_PREFIX + '%s  %s\\0" '
    '"$(readlink -n -- "$l" | sha256sum | cut -c1-64)" "$l"; '
    "done"
)


def manifest_command(root: str = WORKSPACE) -> str:
    """The in-container shell command that emits the churn manifest for ``root``.

    Two ``find`` passes, one policy: regular files hashed by ``sha256sum -z`` and
    symlinks keyed by ``symlink:<sha256 of the target>`` (the target is read with
    ``readlink -n`` and hashed, never embedded raw). Both passes share
    :func:`_find_predicates` so ``.git`` / ``__pycache__`` directory contents are
    excluded identically, and both emit **NUL-terminated** ``<value>  <path>``
    records with raw paths -- ``-z`` disables ``sha256sum``'s filename escaping, so
    a newline/backslash in a name can neither split a record nor be escaped on only
    one side (#274). The union is ``sort -z``ed for a stable, order-independent
    manifest. Requires GNU ``find``, ``sha256sum``, ``readlink``, and ``cut`` --
    all present in the sandbox image, as the existing ``find ... -delete`` sync
    already assumes.
    """
    predicates = _find_predicates()
    files = f"find {root} -type f {predicates} -exec sha256sum -z {{}} +"
    links = (
        f"find {root} -type l {predicates} "
        f"-exec sh -c '{_SYMLINK_HASH_SCRIPT}' _ {{}} +"
    )
    return f"{{ {files} ; {links} ; }} | sort -z"


def parse_manifest(text: str, root: str = WORKSPACE) -> dict[str, str]:
    """Parse :func:`manifest_command` output into {``root``-relative path: value}.

    Records are **NUL-terminated** ``<value>  <path>`` (two-space separated):
    ``<value>`` is a file's sha256 hex digest (from ``sha256sum -z``) or
    ``symlink:<sha256 of the target>``; both are compared opaquely by
    :func:`diff_manifests`. Splitting on NUL (not newline) means a newline in a
    path cannot split a record, and the value never carries a delimiter because
    the symlink target is hashed (#274).
    """
    manifest: dict[str, str] = {}
    prefix = f"{root.rstrip('/')}/"
    for record in text.split("\0"):
        if not record:
            continue
        value, sep, path = record.partition("  ")
        if not sep or not path:
            continue
        manifest[path.removeprefix(prefix)] = value
    return manifest


def _symlink_value(link_path: Path) -> str:
    """The manifest value for a symlink: ``symlink:`` + sha256 of its raw target.

    Hashing the target bytes (never embedding them) keeps attacker-chosen targets
    -- newline, double-space -- out of the manifest text entirely, so they can
    neither split a record nor collide with the field separator (#274). Byte-for-
    byte identical to the shell ``readlink -n -- <link> | sha256sum``.
    """
    target = os.readlink(os.fsencode(link_path))
    return f"{SYMLINK_PREFIX}{hashlib.sha256(target).hexdigest()}"


def _excluded(rel: Path) -> bool:
    """Whether ``rel`` is excluded: an *ancestor* component is an excluded dir.

    Mirrors ``find``'s ``-path '*/.git/*'`` / ``'*/__pycache__/*'`` exactly -- the
    predicate matches only a *non-final* ``.git`` / ``__pycache__`` component, so
    the check is over ``rel.parts[:-1]`` (ancestors), never the leaf. A leaf named
    ``.git`` / ``__pycache__`` (file, symlink, or dangling symlink) is authored
    content and is recorded on both renderings (#280). Bytecode is excluded only
    via this rule: a ``*.pyc`` under ``__pycache__/`` has ``__pycache__`` as an
    ancestor; a ``.pyc`` outside ``__pycache__/`` is authored and counts.
    """
    return any(part in EXCLUDE_DIRS for part in rel.parts[:-1])


def manifest_from_dir(directory: Path | str) -> dict[str, str]:
    """Walk ``directory`` host-side, rendering the same policy as the shell path.

    Mirrors ``find`` semantics exactly (no ``-L``): symlinks are recorded as
    ``symlink:<sha256 of target>`` and never followed for recursion, regular files
    are hashed, and only the *contents* of real ``.git`` / ``__pycache__``
    directories are pruned -- a *leaf* named ``.git`` / ``__pycache__`` is recorded
    (#280). So this and :func:`manifest_command` produce identical manifests for
    identical trees (pinned by ``test_churn_manifest``). Used by the host-side
    battery-scenario guard, which has no Docker daemon to run the shell command in.
    """
    directory = Path(directory)
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(directory, followlinks=False):
        base = Path(dirpath)
        kept: list[str] = []
        for name in dirnames:
            child = base / name
            if child.is_symlink():
                # A symlink to a directory is a LEAF: find lists it as -type l and
                # never recurses into it (no -L). Record it (subject only to the
                # ancestor rule), then do not descend -- even when it is *named*
                # .git / __pycache__, which is authored content, not a pruned dir
                # (#280). The name-based prune below applies to REAL dirs only.
                rel = child.relative_to(directory)
                if not _excluded(rel):
                    out[rel.as_posix()] = _symlink_value(child)
                continue
            if name in EXCLUDE_DIRS:
                continue  # prune a REAL .git/__pycache__ dir: do not descend
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            child = base / name
            rel = child.relative_to(directory)
            if _excluded(rel):
                continue
            if child.is_symlink():
                out[rel.as_posix()] = _symlink_value(child)
            elif child.is_file():
                out[rel.as_posix()] = hashlib.sha256(child.read_bytes()).hexdigest()
    return out


def diff_manifests(before: dict[str, str], after: dict[str, str]) -> tuple[str, ...]:
    """Paths added, removed, or modified between two manifests (sorted)."""
    changed = {
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    }
    return tuple(sorted(changed))


def filter_unexpected(
    changed: tuple[str, ...], allowed: tuple[str, ...]
) -> tuple[str, ...]:
    """Changed paths not covered by an allowed exact path or directory prefix."""

    def is_allowed(path: str) -> bool:
        return any(
            path == entry or (entry.endswith("/") and path.startswith(entry))
            for entry in allowed
        )

    return tuple(p for p in changed if not is_allowed(p))
