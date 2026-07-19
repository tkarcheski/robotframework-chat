"""Explicit-decoration guard for the harness runner keyword libraries (#256).

The harness runner libraries are real Robot Framework keyword libraries — suites
load them with ``Library rfc.harness_cli_kw.HarnessCliRunner`` and
``Library rfc.harness_listener_kw.HarnessListenerRunner`` — but their filenames
end in ``_kw.py`` and their classes are not named ``*Keywords``, so the
``src/rfc/*_keywords.py`` snapshot heuristic never scanned them and they exposed
their keywords purely by Robot's bare auto-exposure: every public method silently
became a keyword, and a helper added without a leading underscore would leak into
the public surface unnoticed (the #205 failure class).

This guard blesses the *explicit-decoration* convention already used across the
tree — ``LLMKeywords`` (13/13 ``@keyword``), ``HarnessKeywords``,
``IFEvalKeywords`` (``@not_keyword`` on its internal ``check_*`` helpers, #247),
``DialogRecorder`` — for these two remaining outliers: every public method of a
runner library must declare its Robot intent, ``@keyword`` for a real keyword or
``@not_keyword`` for an internal helper. Bare auto-exposure of a public method
fails, so a new keyword can never slip in undecorated (fail-closed) and a new
helper is a conscious ``@not_keyword`` rather than an accidental keyword.

Behaviour is unchanged: ``@keyword`` with the current method-derived name exposes
exactly the same keywords, so no suite and no keyword-surface snapshot moves.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_RFC_DIR = Path(__file__).resolve().parent.parent / "src" / "rfc"

# Runner-style keyword libraries loaded via ``Library rfc.<module>.<Class>`` that
# the ``*_keywords.py`` snapshot guard does not cover. Add future runner
# libraries here so their public surface stays explicitly decorated.
_RUNNER_LIBRARIES = (
    "harness_cli_kw.py",
    "harness_listener_kw.py",
)

# Robot decorators that make a method's exposure intent explicit either way.
_INTENT_DECORATORS = frozenset({"keyword", "not_keyword"})


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return the bare names of a function's decorators.

    Handles ``@keyword``, ``@keyword("Name")`` and dotted forms
    (``@deco.keyword`` / ``@deco.keyword("Name")``).
    """
    names: set[str] = set()
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def _undecorated_public_methods(path: Path) -> list[str]:
    """Return ``Class.method`` names lacking an explicit-intent decorator."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        for item in cls.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name.startswith("_"):
                continue
            if not (_decorator_names(item) & _INTENT_DECORATORS):
                offenders.append(f"{cls.name}.{item.name}")
    return offenders


@pytest.mark.parametrize("filename", _RUNNER_LIBRARIES)
def test_runner_public_methods_declare_robot_intent(filename: str) -> None:
    offenders = _undecorated_public_methods(_RFC_DIR / filename)
    assert not offenders, (
        f"{filename}: public method(s) rely on bare Robot auto-exposure: "
        f"{offenders}. Decorate each with @keyword (a real keyword) or "
        "@not_keyword (an internal helper) so exposure is an explicit, "
        "reviewable decision, not an accident (#256)."
    )
