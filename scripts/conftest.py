"""Make scripts in this directory importable by their bare module name.

`modules/ops/scripts/` is a package (it has `__init__.py`), so pytest's default
prepend import mode would resolve test imports from the package parent rather
than this directory — `import check_rfc_index` then fails when the suite is run
from the repo root. Prepending this directory to sys.path lets the colocated
tests import the guard scripts directly (e.g. `from check_rfc_index import ...`),
matching how the scripts are invoked on the command line.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
