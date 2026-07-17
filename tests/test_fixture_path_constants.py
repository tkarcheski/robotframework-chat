"""Fixture-path constant checker — the generalized #384/#392 guard (#397).

Runtime fixture locations under ``src/rfc/`` are encoded as module-level
``Path`` constants built relative to ``__file__`` — ``FIXTURE_SUITE``,
``DEFAULT_FIXTURES_ROOT``, ``DEFAULT_SANDBOX_SCENARIOS_ROOT`` — each pointing
into the ``robot/`` tree. Because such a path is only dereferenced at
child-run time, a robot-tree restructuring (the tier-renumbering migration was
the latest) rots a stale literal *silently*: nothing fails at import, the break
surfaces much later when a child robot run or a runner cannot find its fixture.
The tier-renumbering updated one of the three constants and missed the other
two (#384); #392 then added per-constant guards for those two.

This guard generalizes that instinct so the whole class is covered by
construction. It discovers every ``*_ROOT`` / ``*_SUITE`` fixture-path constant
across ``rfc.*`` — a module-level ``Path`` whose name follows the convention and
that resolves under the ``robot/`` tree — and asserts each points at real
fixture content. A newly-added constant of the same shape is guarded the moment
it lands, with no per-constant test to remember to write.

Discovery derives from source truth rather than a hand-maintained list: the
constant names are read from the ``src/rfc/*.py`` module ASTs (cheap and
side-effect-free), then only the declaring modules are imported to read each
constant's resolved ``Path`` value. This mirrors ``test_keyword_surface``'s
import-derived approach — the guarded set tracks reality instead of a second
literal that can itself go stale.
"""

from __future__ import annotations

import ast
import importlib
from collections.abc import Iterator
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).resolve().parent.parent
_RFC_DIR = _CORE_DIR / "src" / "rfc"
_ROBOT_DIR = _CORE_DIR / "robot"

# Naming convention for the fixture-path-constant class this guard protects: a
# module-level constant whose name ends in one of these suffixes (see #397).
_CONSTANT_SUFFIXES = ("_ROOT", "_SUITE")


def _iter_constant_names(rfc_dir: Path = _RFC_DIR) -> Iterator[tuple[str, str]]:
    """Yield ``(module, name)`` for every module-level ``*_ROOT`` / ``*_SUITE``
    assignment across ``src/rfc/``.

    Reads each module's AST rather than importing it: discovery must be cheap and
    side-effect-free, and only the handful of modules that actually declare such
    a constant are imported later (in :func:`_discover_fixture_path_constants`)
    to read its value. Only top-level assignments are inspected, so a same-named
    local inside a function is never mistaken for a module constant.
    """
    for path in sorted(rfc_dir.glob("*.py")):
        module = f"rfc.{path.stem}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id.endswith(
                    _CONSTANT_SUFFIXES
                ):
                    yield module, target.id


def _discover_fixture_path_constants() -> list[tuple[str, str, Path]]:
    """Return ``(module, name, value)`` for every fixture-path constant.

    A fixture-path constant is a discovered ``*_ROOT`` / ``*_SUITE`` module
    attribute whose value is a ``Path`` resolving under the ``robot/`` tree. The
    ``robot/`` filter is what distinguishes a fixture location from an unrelated
    same-suffixed constant such as ``rfc.live_agent_runner.REPO_ROOT`` (the
    ``core/`` repo root, not fixture content).
    """
    robot_dir = _ROBOT_DIR.resolve()
    found: list[tuple[str, str, Path]] = []
    for module_name, attr in sorted(set(_iter_constant_names())):
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        if isinstance(value, Path) and value.resolve().is_relative_to(robot_dir):
            found.append((module_name, attr, value))
    return found


def _resolves(path: Path) -> bool:
    """Return whether a fixture-path constant points at real fixture content.

    A file must exist as a file. A directory must exist AND list at least one
    real (non-``__pycache__``) entry — a listing check, not a bare ``exists()``.
    A stale directory can linger holding only a ``__pycache__`` (Python writes
    one beside any importable ``.py`` fixture), which satisfies ``exists()`` while
    carrying zero fixtures: exactly the false positive #384 hit, and the reason
    the #392 per-constant guards assert *listing*, not existence.
    """
    if path.is_file():
        return True
    if path.is_dir():
        return any(child.name != "__pycache__" for child in path.iterdir())
    return False


_FIXTURE_PATH_CONSTANTS = _discover_fixture_path_constants()


@pytest.mark.parametrize(
    ("module", "name", "path"),
    _FIXTURE_PATH_CONSTANTS,
    ids=[f"{module}.{name}" for module, name, _ in _FIXTURE_PATH_CONSTANTS],
)
def test_fixture_path_constant_resolves(module: str, name: str, path: Path) -> None:
    """Every discovered fixture-path constant must point at real fixture content.

    Fails fast the next time a robot-tree restructuring moves fixtures without
    updating the constant, instead of the break surfacing at child-run time.
    """
    assert _resolves(path), (
        f"{module}.{name} points at a stale or empty fixture path: {path}. "
        "A robot-tree restructuring likely moved the fixtures without updating "
        "the constant (see #384/#397). Repoint it at the current location."
    )


def test_discovery_covers_known_constants() -> None:
    """Pin the three known fixture-path constants so discovery cannot go blind.

    If a refactor of the AST scan or the naming convention drops these, the
    parametrized guard above shrinks to zero cases and stays green while
    protecting nothing — the same silent-blindness failure mode #384 is about.
    """
    discovered = {(module, name) for module, name, _ in _FIXTURE_PATH_CONSTANTS}
    assert {
        ("rfc.dialog_e2e_keywords", "FIXTURE_SUITE"),
        ("rfc.fake_agent_runner", "DEFAULT_FIXTURES_ROOT"),
        ("rfc.agent_sandbox", "DEFAULT_SANDBOX_SCENARIOS_ROOT"),
    } <= discovered


def test_non_fixture_root_constant_excluded() -> None:
    """A ``*_ROOT`` constant outside the ``robot/`` tree is not a fixture path.

    ``rfc.live_agent_runner.REPO_ROOT`` is the ``core/`` repo root — same suffix,
    but not fixture content. The ``robot/`` filter must exclude it so the guard
    never asserts an unrelated directory as if it held fixtures.
    """
    discovered = {(module, name) for module, name, _ in _FIXTURE_PATH_CONSTANTS}
    assert ("rfc.live_agent_runner", "REPO_ROOT") not in discovered


def test_resolves_accepts_a_file(tmp_path: Path) -> None:
    fixture = tmp_path / "record_dialog_fixture.robot"
    fixture.write_text("*** Test Cases ***\n", encoding="utf-8")
    assert _resolves(fixture)


def test_resolves_accepts_a_populated_directory(tmp_path: Path) -> None:
    (tmp_path / "scenario").mkdir()
    assert _resolves(tmp_path)


def test_resolves_rejects_missing_path(tmp_path: Path) -> None:
    assert not _resolves(tmp_path / "gone")


def test_resolves_rejects_pycache_only_directory(tmp_path: Path) -> None:
    """The #384 false positive: a stale fixtures dir holding only ``__pycache__``
    satisfies ``exists()`` but carries no fixtures, so the listing check must
    reject it. An empty directory is rejected for the same reason.
    """
    (tmp_path / "__pycache__").mkdir()
    assert not _resolves(tmp_path)
