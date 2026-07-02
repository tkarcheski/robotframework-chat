"""Import Robot Framework test results into the database (ops CLI shim).

The output.xml -> database import logic now lives in the public ``core``
package at :mod:`rfc.result_import`, because it manipulates the core
``test_database`` schema and depends only on ``rfc.*`` (RFC-001: ``core`` must
never depend on a private module; the allowed direction is ops -> core). This
module is a thin shim that re-exports that logic so existing ops entrypoints —
``uv run python scripts/import_test_results.py ...`` and the ops test suite —
keep working unchanged.

Respects DATABASE_URL for PostgreSQL; defaults to SQLite.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `from rfc.result_import import ...` when this script is run standalone
# from a checkout where the `rfc` package is not already installed/on the path.
# ops -> core is the allowed dependency direction; core/src holds the package.
# (Under pytest, modules/ops/conftest.py wires core/src instead.)
_CORE_SRC = Path(__file__).resolve().parent.parent.parent.parent / "core" / "src"
if _CORE_SRC.is_dir() and str(_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(_CORE_SRC))

from rfc.result_import import (  # noqa: E402
    _parse_rf_timestamp,
    import_results,
    main,
    parse_output_xml,
)

__all__ = [
    "_parse_rf_timestamp",
    "import_results",
    "main",
    "parse_output_xml",
]


if __name__ == "__main__":
    main()
