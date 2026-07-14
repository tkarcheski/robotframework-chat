"""Unit + parity tests for the one owned churn manifest policy (#248, #231).

:mod:`rfc.churn_manifest` renders a single manifest/exclusion policy two ways: a
shell command run inside the sandbox container (:func:`manifest_command` +
:func:`parse_manifest`) and a host-side directory walk (:func:`manifest_from_dir`)
used by the battery-scenario guard. The two divergences these tests exist to
prevent are:

* #248 -- the container grader was blind to symlinks (``find -type f``), so an
  out-of-allowlist symlink smuggled past the churn gate.
* #231 -- the host-side checker excluded bytecode while the grader counted it, so
  the checker could bless a solution the grader would reject.

The headline is :class:`TestShellWalkParity`, which runs the *actual* shell
rendering on the host and asserts it produces byte-identical manifests to the
Python walk -- the pin that keeps the two consumers from ever drifting again.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from rfc.churn_manifest import (
    EXCLUDE_DIRS,
    SYMLINK_PREFIX,
    diff_manifests,
    filter_unexpected,
    manifest_command,
    manifest_from_dir,
    parse_manifest,
)


def _have_gnu_find() -> bool:
    with tempfile.TemporaryDirectory() as d:
        try:
            r = subprocess.run(
                f"find {d} -maxdepth 0 -printf '%p\\n'",
                shell=True,
                capture_output=True,
                text=True,
            )
        except OSError:
            return False
        return r.returncode == 0 and d in r.stdout


requires_gnu_find = pytest.mark.skipif(
    not _have_gnu_find(),
    reason="GNU find with -printf required for the shell-vs-walk parity pin",
)


# --- policy constants --------------------------------------------------------


class TestPolicyConstants:
    def test_vcs_and_bytecode_dirs_excluded(self) -> None:
        # #231/#280: exclusion keys on an ANCESTOR dir named .git/__pycache__, in
        # ONE set shared by both renderings. There is no suffix-anywhere rule --
        # a .pyc is excluded only under __pycache__/, a bare .pyc counts.
        assert ".git" in EXCLUDE_DIRS
        assert "__pycache__" in EXCLUDE_DIRS


# --- shell command shape -----------------------------------------------------


class TestManifestCommand:
    def test_has_file_and_symlink_passes(self) -> None:
        cmd = manifest_command()
        # regular files hashed...
        assert "-type f" in cmd and "sha256sum" in cmd
        # ...and symlinks captured as -type l with the target HASHED into the
        # value (readlink | sha256sum), never embedded raw -- #274, #248.
        assert "-type l" in cmd
        assert SYMLINK_PREFIX in cmd and "readlink" in cmd

    def test_applies_exclusions_to_both_passes(self) -> None:
        cmd = manifest_command()
        # each excluded dir appears once per find pass (2x total)
        assert cmd.count("-not -path '*/.git/*'") == 2
        assert cmd.count("-not -path '*/__pycache__/*'") == 2
        # #280: NO suffix-anywhere predicate -- a .pyc outside __pycache__ counts.
        assert "-name '*.pyc'" not in cmd

    def test_root_is_parameterised(self) -> None:
        assert "/tmp/scenario" in manifest_command(root="/tmp/scenario")


# --- parse_manifest ----------------------------------------------------------


class TestParseManifest:
    def test_file_and_symlink_lines(self) -> None:
        # NUL-terminated records; the symlink value is a hashed target (#274).
        text = "aa11  /workspace/calculator.py\0symlink:bb22  /workspace/escape\0"
        assert parse_manifest(text) == {
            "calculator.py": "aa11",
            "escape": "symlink:bb22",
        }

    def test_ignores_blank_lines(self) -> None:
        assert parse_manifest("\n\n") == {}

    def test_custom_root_prefix_stripped(self) -> None:
        assert parse_manifest("aa11  /tmp/x/a.py\0", root="/tmp/x") == {"a.py": "aa11"}


# --- host-side walk ----------------------------------------------------------


class TestManifestFromDir:
    def test_hashes_regular_files_relative(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.py").write_text("y", encoding="utf-8")
        assert set(manifest_from_dir(tmp_path)) == {"a.py", "sub/b.py"}

    def test_prunes_dir_contents_but_counts_stray_pyc(self, tmp_path: Path) -> None:
        # #280: prune the CONTENTS of __pycache__/.git dirs, but a bare .pyc
        # OUTSIDE __pycache__ is authored -> counted.
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "a.pyc").write_text("bc", encoding="utf-8")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("[core]", encoding="utf-8")
        (tmp_path / "stray.pyc").write_text("bc", encoding="utf-8")
        assert set(manifest_from_dir(tmp_path)) == {"a.py", "stray.pyc"}

    def test_symlink_recorded_as_target_not_followed(self, tmp_path: Path) -> None:
        # #248: the link target keys the value; the host walk never dereferences
        # it (the old is_file() did, hiding an escape symlink as target content).
        # #274: the target is hashed, not embedded raw.
        os.symlink("/etc/passwd", tmp_path / "escape")
        expected = f"symlink:{hashlib.sha256(b'/etc/passwd').hexdigest()}"
        assert manifest_from_dir(tmp_path) == {"escape": expected}

    def test_symlink_to_directory_recorded_not_descended(self, tmp_path: Path) -> None:
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "inside.py").write_text("z", encoding="utf-8")
        os.symlink("real", tmp_path / "link")
        m = manifest_from_dir(tmp_path)
        assert m["link"] == f"symlink:{hashlib.sha256(b'real').hexdigest()}"
        # the link is not followed for recursion -> no "link/inside.py" key
        assert "link/inside.py" not in m
        assert "real/inside.py" in m

    def test_retarget_is_churn(self, tmp_path: Path) -> None:
        os.symlink("/etc/hostname", tmp_path / "s")
        before = manifest_from_dir(tmp_path)
        (tmp_path / "s").unlink()
        os.symlink("/etc/passwd", tmp_path / "s")
        after = manifest_from_dir(tmp_path)
        assert diff_manifests(before, after) == ("s",)

    def test_file_to_symlink_swap_is_churn(self, tmp_path: Path) -> None:
        # A regular-file <-> symlink swap at one path must register: the symlink
        # value can never collide with the file's hex digest.
        (tmp_path / "p").write_text("real contents", encoding="utf-8")
        before = manifest_from_dir(tmp_path)
        (tmp_path / "p").unlink()
        os.symlink("/etc/passwd", tmp_path / "p")
        after = manifest_from_dir(tmp_path)
        assert diff_manifests(before, after) == ("p",)
        assert after["p"].startswith(SYMLINK_PREFIX)


# --- filter_unexpected -------------------------------------------------------


class TestFilterUnexpected:
    def test_exact_and_prefix_allowed(self) -> None:
        changed = ("calculator.py", "notes.txt", "src/extra.py")
        assert filter_unexpected(changed, ("calculator.py", "src/")) == ("notes.txt",)

    def test_empty_allowed_flags_everything(self) -> None:
        assert filter_unexpected(("x",), ()) == ("x",)


# --- the parity pin: shell rendering == python walk (#231's cross-check) ------


@requires_gnu_find
class TestShellWalkParity:
    """The container-side shell command and the host-side walk must agree exactly.

    Running the real ``manifest_command`` on the host (it is plain
    ``find | sha256sum | sort``, no Docker needed) over the same tree the Python
    walk sees is the mechanical guarantee that the two consumers -- the grader and
    the guard -- can never silently diverge on symlinks, bytecode, or ``.git``.
    """

    def _shell_manifest(self, root: Path) -> dict[str, str]:
        out = subprocess.run(
            manifest_command(root=str(root)),
            shell=True,
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0, out.stderr
        return parse_manifest(out.stdout, root=str(root))

    def test_rich_tree_parity(self, tmp_path: Path) -> None:
        (tmp_path / "calculator.py").write_text("def f():\n    return 1\n")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "extra.py").write_text("y = 2\n")
        (tmp_path / ".sneaky").write_text("hidden\n")
        (tmp_path / "na me €.txt").write_text("weird\n")  # spaces + unicode
        # __pycache__ dir contents pruned on both sides; stray.pyc (outside) counts
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "calculator.cpython-313.pyc").write_text("bc\n")
        (tmp_path / "stray.pyc").write_text("bc\n")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("[core]\n")
        # symlinks: out-of-tree, and to a directory
        os.symlink("/etc/passwd", tmp_path / "escape")
        os.symlink("sub", tmp_path / "subln")

        walk = manifest_from_dir(tmp_path)
        shell = self._shell_manifest(tmp_path)
        assert walk == shell
        # and the policy actually took effect
        assert walk["escape"] == f"symlink:{hashlib.sha256(b'/etc/passwd').hexdigest()}"
        assert walk["subln"] == f"symlink:{hashlib.sha256(b'sub').hexdigest()}"
        # __pycache__/.git DIRECTORY contents are pruned...
        assert not any(k.startswith("__pycache__/") for k in walk)
        assert not any(k.startswith(".git/") for k in walk)
        # ...but a bare .pyc outside __pycache__ is authored -> counted (#280)
        assert "stray.pyc" in walk

    def test_empty_tree_parity(self, tmp_path: Path) -> None:
        assert manifest_from_dir(tmp_path) == self._shell_manifest(tmp_path) == {}


# --- test-design adversarial regressions (#248 filer) ------------------------
# The parity pin above uses only benign names. `sha256sum` ESCAPES special chars
# in regular-file names (leading '\\' + '\\n'/'\\\\'), but the symlink pass emits the
# target/name RAW via `find -printf 'symlink:%l  %p\\n'`, and `parse_manifest`
# strips + splits on two-space. A newline or double-space in an attacker-chosen
# symlink target therefore desyncs the walk vs the shell (#231 class) and can
# drop the line entirely (#248 class). These pin the intended invariants and
# currently FAIL on PR #271 -- see the from:testing issue for the exploit.


@requires_gnu_find
class TestHostileNameParity:
    """Byte-identical parity must survive pathological path/target names."""

    def _shell(self, root: Path) -> dict[str, str]:
        out = subprocess.run(
            manifest_command(root=str(root)),
            shell=True,
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0, out.stderr
        return parse_manifest(out.stdout, root=str(root))

    def test_newline_in_filename_parity(self, tmp_path: Path) -> None:
        (tmp_path / "ev\nil.py").write_text("payload", encoding="utf-8")
        assert manifest_from_dir(tmp_path) == self._shell(tmp_path)

    def test_newline_in_symlink_target_parity(self, tmp_path: Path) -> None:
        os.symlink("/etc/passwd\n", tmp_path / "escape")
        assert manifest_from_dir(tmp_path) == self._shell(tmp_path)

    def test_double_space_in_symlink_target_parity(self, tmp_path: Path) -> None:
        os.symlink("/a  b/c", tmp_path / "escape")
        assert manifest_from_dir(tmp_path) == self._shell(tmp_path)


@requires_gnu_find
class TestGraderSymlinkSmuggle:
    """#248's own promise, driven through the real grader (shell) rendering.

    The container grader runs :func:`manifest_command` then
    :func:`parse_manifest` -> :func:`diff_manifests` -> :func:`filter_unexpected`.
    An out-of-allowlist symlink MUST land in the unexpected set regardless of its
    target. FAILS on #271: a newline-terminated target hides it entirely.
    """

    def _shell(self, root: Path) -> dict[str, str]:
        out = subprocess.run(
            manifest_command(root=str(root)),
            shell=True,
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0, out.stderr
        return parse_manifest(out.stdout, root=str(root))

    def test_newline_target_symlink_is_unexpected_churn(self, tmp_path: Path) -> None:
        (tmp_path / "calculator.py").write_text("def f():\n    return 1\n")
        before = self._shell(tmp_path)
        os.symlink("/etc/passwd\n", tmp_path / "escape")  # out-of-allowlist
        after = self._shell(tmp_path)
        unexpected = filter_unexpected(
            diff_manifests(before, after), ("calculator.py",)
        )
        assert unexpected != ()  # #271: () -> symlink smuggled past the gate


@requires_gnu_find
class TestExcludedNameLeafParity:
    """#280: a LEAF named .git/__pycache__ is authored -> recorded on BOTH sides.

    The shell prunes only *directory contents* (``find -path '*/NAME/*'`` needs a
    non-final NAME component); the walk now matches (ancestor-only exclusion). A
    leaf (regular file, symlink, dangling symlink) named ``.git`` / ``__pycache__``
    -- and a bare ``.pyc`` outside ``__pycache__`` -- must appear identically in
    walk and shell, and register as unexpected churn when out of the allowlist.
    These are the six DRIFT cases design reproduced against #271's "impossible by
    construction" claim, now byte-identical.
    """

    def _shell(self, root: Path) -> dict[str, str]:
        out = subprocess.run(
            manifest_command(root=str(root)),
            shell=True,
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0, out.stderr
        return parse_manifest(out.stdout, root=str(root))

    def test_symlink_named_pycache_to_dir(self, tmp_path: Path) -> None:
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "x.py").write_text("z")
        os.symlink("real", tmp_path / "__pycache__")
        walk = manifest_from_dir(tmp_path)
        assert walk == self._shell(tmp_path)
        assert walk["__pycache__"].startswith(SYMLINK_PREFIX)  # recorded, not pruned
        assert "real/x.py" in walk
        assert "__pycache__/x.py" not in walk  # symlink not descended

    def test_symlink_named_git_to_outside_file(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x")
        os.symlink("/etc/passwd", tmp_path / ".git")
        walk = manifest_from_dir(tmp_path)
        assert walk == self._shell(tmp_path)
        assert walk[".git"].startswith(SYMLINK_PREFIX)

    def test_symlink_named_pycache_to_file(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x")
        os.symlink("/etc/passwd", tmp_path / "__pycache__")
        walk = manifest_from_dir(tmp_path)
        assert walk == self._shell(tmp_path)
        assert walk["__pycache__"].startswith(SYMLINK_PREFIX)

    def test_dangling_symlink_named_pycache(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x")
        os.symlink("/no/such/target", tmp_path / "__pycache__")
        walk = manifest_from_dir(tmp_path)
        assert walk == self._shell(tmp_path)
        assert walk["__pycache__"].startswith(SYMLINK_PREFIX)

    def test_nested_symlink_named_pycache(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "a.py").write_text("x")
        os.symlink("/etc/passwd", tmp_path / "sub" / "__pycache__")
        walk = manifest_from_dir(tmp_path)
        assert walk == self._shell(tmp_path)
        assert walk["sub/__pycache__"].startswith(SYMLINK_PREFIX)

    def test_regular_file_named_git(self, tmp_path: Path) -> None:
        # git-worktree seed shape: a top-level regular FILE named .git.
        (tmp_path / "a.py").write_text("x")
        (tmp_path / ".git").write_text("gitdir: /somewhere\n")
        walk = manifest_from_dir(tmp_path)
        assert walk == self._shell(tmp_path)
        assert ".git" in walk and not walk[".git"].startswith(SYMLINK_PREFIX)

    def test_real_pycache_dir_still_pruned(self, tmp_path: Path) -> None:
        # control: a REAL __pycache__ dir's .pyc IS still pruned, both sides.
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "a.cpython-313.pyc").write_text("bc")
        walk = manifest_from_dir(tmp_path)
        assert walk == self._shell(tmp_path)
        assert set(walk) == {"a.py"}

    def test_top_level_pyc_is_unexpected_churn(self, tmp_path: Path) -> None:
        # #280 Part B: a bare evil.pyc outside __pycache__ is authored -> counted
        # identically on both sides, and flagged when out of the allowlist.
        (tmp_path / "calculator.py").write_text("x")
        before = manifest_from_dir(tmp_path)
        (tmp_path / "evil.pyc").write_text("payload")
        after = manifest_from_dir(tmp_path)
        assert after == self._shell(tmp_path)
        assert "evil.pyc" in after
        assert "evil.pyc" in filter_unexpected(
            diff_manifests(before, after), ("calculator.py",)
        )

    def test_excluded_name_leaves_are_unexpected_churn(self, tmp_path: Path) -> None:
        # the guarantee #280 says the walk-drop broke: an out-of-allowlist leaf
        # named .git/__pycache__ (and a bare .pyc) is flagged, not smuggled, and
        # the guard (walk) agrees with the grader (shell).
        (tmp_path / "calculator.py").write_text("def f():\n    return 1\n")
        before = self._shell(tmp_path)
        os.symlink("/etc/passwd", tmp_path / ".git")
        os.symlink("/etc/passwd", tmp_path / "__pycache__")
        (tmp_path / "evil.pyc").write_text("payload")
        after = self._shell(tmp_path)
        assert manifest_from_dir(tmp_path) == after  # guard == grader
        unexpected = filter_unexpected(
            diff_manifests(before, after), ("calculator.py",)
        )
        assert set(unexpected) == {".git", "__pycache__", "evil.pyc"}

    def test_all_excluded_name_leaves_one_tree_parity(self, tmp_path: Path) -> None:
        # the full #280 hostile-leaf tree in a single manifest: byte-identical.
        (tmp_path / "a.py").write_text("x")
        (tmp_path / ".git").write_text("gitdir: x\n")  # regular file leaf
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "a.py").write_text("y")
        os.symlink("/etc/passwd", tmp_path / "sub" / "__pycache__")  # nested symlink
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "x.py").write_text("z")
        os.symlink("real", tmp_path / "linkdir")  # ordinary dir symlink
        (tmp_path / "evil.pyc").write_text("bc")  # counted
        keep_cache = tmp_path / "keep" / "__pycache__"
        keep_cache.mkdir(parents=True)
        (keep_cache / "m.pyc").write_text("bc")  # pruned (real dir)
        walk = manifest_from_dir(tmp_path)
        assert walk == self._shell(tmp_path)
        assert {".git", "evil.pyc", "sub/__pycache__", "linkdir"} <= set(walk)
        assert not any(k.startswith("keep/__pycache__") for k in walk)
