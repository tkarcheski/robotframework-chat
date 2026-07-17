"""Guard: every Robot path named in ``config/*.yaml`` resolves to a real file.

Prevents config drift (rfc-monorepo #202): ``config/test_suites.yaml`` pointed at
``robot/20__tier2/github/tests/repo_review.robot`` while the suite actually lives
at ``robot/20__tier2/github/repo_review.robot`` (no ``tests/`` segment). A stale
suite path resolves to nothing, so whatever consumes the config either skips the
suite silently or errors. This check turns that drift into a test failure so it
cannot recur.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

# core/tests/test_config_paths.py -> core/
_CORE_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_DIR = _CORE_ROOT / "config"

# YAML keys whose value names a Robot suite path relative to the core root.
_PATH_KEYS = ("path", "suite")


def _iter_robot_paths(node: object) -> Iterator[str]:
    """Yield every ``path``/``suite`` value that names a ``robot/`` path."""
    if isinstance(node, dict):
        for key, value in node.items():
            if (
                key in _PATH_KEYS
                and isinstance(value, str)
                and value.startswith("robot/")
            ):
                yield value
            yield from _iter_robot_paths(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_robot_paths(item)


def _collect_references() -> list[tuple[str, str]]:
    """Return ``(config filename, robot path)`` for every ``config/*.yaml`` ref."""
    refs: list[tuple[str, str]] = []
    for config_file in sorted(_CONFIG_DIR.glob("*.yaml")):
        data = yaml.safe_load(config_file.read_text())
        for robot_path in _iter_robot_paths(data):
            refs.append((config_file.name, robot_path))
    return refs


_REFERENCES = _collect_references()


def test_configs_reference_robot_paths() -> None:
    """Sanity: the configs do reference robot paths, so the guard is not a no-op."""
    assert _REFERENCES, "no robot/ paths found in config/*.yaml"


@pytest.mark.parametrize(
    "config_name,robot_path",
    _REFERENCES,
    ids=[f"{name}:{path}" for name, path in _REFERENCES],
)
def test_config_robot_path_resolves(config_name: str, robot_path: str) -> None:
    """Every Robot path a config names must resolve to a real file or directory."""
    resolved = _CORE_ROOT / robot_path
    assert resolved.exists(), (
        f"{config_name} references {robot_path!r}, which does not exist at "
        f"{resolved}. Fix the config entry or the suite path (config drift, #202)."
    )
