"""Guard the core -> ops mirror boundary (RFC-001, issues #66 / #68).

The public ``core`` package is published verbatim as the mirror
(robotframework-chat) and must never depend on a private module. The historical
violation was ``core/src/rfc/result_importer.py`` reaching into
``scripts.import_test_results`` (now private ``modules/ops/scripts``), which
dangled in the mirror and failed at runtime with ``No module named 'scripts'``.

These tests fail if that boundary is reintroduced:
  1. No ``core/src/rfc`` source imports the private ``scripts`` package (at any
     scope — module-level or function-local).
  2. ``rfc.result_importer`` imports *and* runs an import end-to-end without
     ``scripts`` being importable, proving the dependency moved into ``core``.
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_RFC_SRC = Path(__file__).resolve().parent.parent / "src" / "rfc"

# Forbidden private-module roots a public core/ file must never import.
_FORBIDDEN_IMPORT_ROOTS = {"scripts", "modules"}


def _imported_roots(source: str) -> set[str]:
    """Return the top-level package names imported anywhere in ``source``.

    Walks the whole AST, so function-local imports (the original #66 shape) are
    caught just like module-level ones.
    """
    roots: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # Ignore relative imports (node.level > 0); only absolute roots.
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_result_importer_has_no_private_module_import() -> None:
    """result_importer.py must not import scripts/modules at any scope (#66/#68)."""
    source = (_RFC_SRC / "result_importer.py").read_text()
    offending = _imported_roots(source) & _FORBIDDEN_IMPORT_ROOTS
    assert not offending, (
        f"core/src/rfc/result_importer.py imports private module(s) {offending}; "
        "core must never depend on a private module (RFC-001)."
    )


def test_no_core_rfc_source_imports_private_modules() -> None:
    """No core/src/rfc/*.py imports the private scripts/modules packages."""
    violations: dict[str, set[str]] = {}
    for py in _RFC_SRC.rglob("*.py"):
        offending = _imported_roots(py.read_text()) & _FORBIDDEN_IMPORT_ROOTS
        if offending:
            violations[str(py.relative_to(_RFC_SRC.parent.parent))] = offending
    assert not violations, (
        "public core/ files import private modules (RFC-001 mirror boundary): "
        f"{violations}"
    )


def test_result_importer_runs_without_scripts_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """import_results works end-to-end even if ``scripts`` cannot be imported.

    Simulates the public mirror, where ``modules/ops/scripts`` does not exist:
    any attempt to import ``scripts`` raises ImportError. The importer must
    still succeed because its base logic now lives in ``rfc.result_import``.
    """
    minimal_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<robot generator="Robot 7.0" generated="2025-06-15T10:00:00.000000">
  <suite name="Boundary Suite" id="s1">
    <metadata><item name="Model">llama3</item></metadata>
    <test name="t1" id="s1-t1">
      <status status="PASS" start="2025-06-15T10:00:01.000000" end="2025-06-15T10:00:02.000000"/>
    </test>
    <status status="PASS" start="2025-06-15T10:00:00.000000" end="2025-06-15T10:00:05.000000"/>
  </suite>
  <statistics><total><stat pass="1" fail="0" skip="0">All</stat></total></statistics>
</robot>
"""
    xml_file = tmp_path / "output.xml"
    xml_file.write_text(minimal_xml)

    # Make any `import scripts[...]` fail, the way the mirror would.
    real_import = builtins.__import__

    def _no_scripts(name: str, *args: object, **kwargs: object) -> object:
        if name == "scripts" or name.startswith("scripts."):
            raise ImportError(f"No module named '{name}' (mirror boundary)")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _no_scripts)

    # Import inside the patched context to prove no `scripts` import is needed.
    from rfc.result_importer import ImportResult, import_results

    db = MagicMock()
    db.add_test_run.return_value = 7
    db.add_test_results.side_effect = lambda results: list(range(1, len(results) + 1))

    result = import_results(str(xml_file), db)
    assert isinstance(result, ImportResult)
    assert result.run_id == 7
    assert result.skipped is False
