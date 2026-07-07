"""Keyword-surface snapshot guard.

Robot keyword names are this project's PUBLIC API: Robot suites here and in the
public mirror invoke keywords by these exact names, so a rename or removal is a
breaking change. This test AST-walks every ``src/rfc/*_keywords.py``, collects
the names registered via ``@keyword(...)`` (and the method-name form of a bare
``@keyword``), and compares them against the checked-in snapshot. Any drift
fails until the snapshot is deliberately regenerated.

Regenerate the snapshot after an *intentional* surface change with::

    python core/tests/test_keyword_surface.py
"""

from __future__ import annotations

import ast
from pathlib import Path

_RFC_DIR = Path(__file__).resolve().parent.parent / "src" / "rfc"
_SNAPSHOT = Path(__file__).resolve().parent / "keyword_surface_snapshot.txt"


def _keyword_name(decorator: ast.expr, method_name: str) -> str | None:
    """Return the Robot keyword name a decorator registers, else ``None``.

    Handles both ``@keyword("Explicit Name")`` and the method-name forms
    (bare ``@keyword`` or ``@keyword()`` with no name), where Robot derives the
    keyword name from the method name.
    """
    if isinstance(decorator, ast.Name) and decorator.id == "keyword":
        return method_name.replace("_", " ").title()
    if (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Name)
        and decorator.func.id == "keyword"
    ):
        if (
            decorator.args
            and isinstance(decorator.args[0], ast.Constant)
            and isinstance(decorator.args[0].value, str)
        ):
            return decorator.args[0].value
        return method_name.replace("_", " ").title()
    return None


def collect_keyword_surface(rfc_dir: Path = _RFC_DIR) -> list[str]:
    """Return the sorted, de-duplicated set of ``@keyword`` names in the tree."""
    names: set[str] = set()
    for path in sorted(rfc_dir.glob("*_keywords.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                name = _keyword_name(decorator, node.name)
                if name is not None:
                    names.add(name)
    return sorted(names)


def test_keyword_surface_matches_snapshot() -> None:
    current = collect_keyword_surface()
    expected = [
        line
        for line in _SNAPSHOT.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    added = sorted(set(current) - set(expected))
    removed = sorted(set(expected) - set(current))
    assert current == expected, (
        "Robot keyword surface drifted from tests/keyword_surface_snapshot.txt.\n"
        "keyword names are public API — if this rename/removal is intentional, "
        "update the snapshot and add a CHANGELOG migration note.\n"
        "Regenerate with: python core/tests/test_keyword_surface.py\n"
        f"  added:   {added}\n"
        f"  removed: {removed}"
    )


if __name__ == "__main__":
    _SNAPSHOT.write_text("\n".join(collect_keyword_surface()) + "\n", encoding="utf-8")
    print(f"wrote {_SNAPSHOT} ({len(collect_keyword_surface())} keyword names)")
