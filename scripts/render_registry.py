#!/usr/bin/env python3
"""Generate the root README modules block + CODEOWNERS from each module.toml.

RFC-001 declares both the root ``README.md`` modules block and ``CODEOWNERS`` to
be "generated from per-module ``module.toml`` ``owner`` roles". They were
maintained by hand and drifted: a ``module.toml`` could appear with no matching
README/CODEOWNERS entry (e.g. ``modules/knowledge`` / ``modules/jury``), or a
CODEOWNERS path could linger with no backing manifest (e.g.
``/modules/graylog/``). This script makes the claim literally true.

It walks ``core/module.toml`` and ``modules/*/module.toml`` (one level of
nesting, e.g. ``modules/ops/monitoring-logs/``) and, from each manifest's
``name`` / ``visibility`` / ``owner`` / ``description``:

  - renders ``CODEOWNERS`` in full (header + one anchored line per module,
    owner-role recorded in the trailing comment); and
  - renders the README "Modules" table inside a generator-owned block delimited
    by ``<!-- BEGIN GENERATED MODULES -->`` / ``<!-- END GENERATED MODULES -->``
    sentinels, so the surrounding hand-written prose is never disturbed.

Two modes:

  --write   regenerate both registries in place (the fix / one-file-edit path).
  --check   (default) fail when either registry drifts from the manifests — the
            CI guard. Mirrors the sibling ``check_submodule_ownership.py`` /
            ``check_agent_signoffs.py`` exit-code contract (0 ok, 1 violations).

Usage:
  uv run python scripts/render_registry.py --check
  uv run python scripts/render_registry.py --write
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Single human reviewer today (RFC-001); split into per-role teams later.
REVIEWER = "@tkarcheski"

# Column at which the reviewer handle starts in CODEOWNERS, matching the
# existing file's alignment. Paths shorter than this are left-padded with
# spaces; a longer path simply pushes its own line out (still valid CODEOWNERS).
_OWNER_COLUMN = 37
_COMMENT_GAP = "   "  # spaces between the reviewer handle and the role comment

README_BEGIN = "<!-- BEGIN GENERATED MODULES -->"
README_END = "<!-- END GENERATED MODULES -->"

CODEOWNERS_HEADER = """\
# CODEOWNERS — generated from per-module module.toml `owner` roles (RFC-001).
# DO NOT EDIT BY HAND — run `python scripts/render_registry.py --write`.
# Role -> reviewer mapping (single human owner today; split into teams later):
#   engineering, design, test-design, project-management -> @tkarcheski
"""


@dataclass(frozen=True)
class Module:
    """One registered unit, parsed from its ``module.toml``."""

    name: str
    path: str  # repo-root-relative dir, e.g. "core" or "modules/ops/monitoring-logs"
    visibility: str
    owner: str
    description: str

    @property
    def codeowners_path(self) -> str:
        """Anchored, trailing-slashed path as CODEOWNERS expects it."""
        return f"/{self.path}/"


# --- discovery --------------------------------------------------------------


def repo_root() -> Path:
    """Repo root: this file is at ``modules/ops/scripts/render_registry.py``."""
    return Path(__file__).resolve().parents[3]


def _load_module(manifest: Path, root: Path) -> Module:
    with manifest.open("rb") as fh:
        data = tomllib.load(fh)
    rel = manifest.parent.relative_to(root).as_posix()
    return Module(
        name=str(data["name"]),
        path=rel,
        visibility=str(data.get("visibility", "private")),
        owner=str(data.get("owner", "")),
        description=str(data.get("description", "")).strip(),
    )


def discover_modules(root: Path) -> list[Module]:
    """Every ``module.toml`` under the root: ``core`` + ``modules/*`` (+ one
    level of nesting), sorted by path for deterministic output."""
    manifests: list[Path] = []
    core = root / "core" / "module.toml"
    if core.is_file():
        manifests.append(core)
    manifests.extend(sorted((root / "modules").glob("*/module.toml")))
    manifests.extend(sorted((root / "modules").glob("*/*/module.toml")))
    modules = [_load_module(m, root) for m in manifests]
    # core first, then modules alphabetically by path — stable and readable.
    return sorted(modules, key=lambda m: (m.path != "core", m.path))


# --- rendering --------------------------------------------------------------


def render_codeowners(modules: list[Module]) -> str:
    modules = sorted(modules, key=lambda m: (m.path != "core", m.path))
    lines = [CODEOWNERS_HEADER.rstrip("\n"), ""]
    for m in modules:
        path = m.codeowners_path
        pad = " " * max(_OWNER_COLUMN - len(path), 1)
        lines.append(f"{path}{pad}{REVIEWER}{_COMMENT_GAP}# owner role: {m.owner}")
    return "\n".join(lines) + "\n"


def render_readme_table(modules: list[Module]) -> str:
    """The generator-owned README block: a Markdown table bracketed by sentinels."""
    modules = sorted(modules, key=lambda m: (m.path != "core", m.path))
    rows = [
        README_BEGIN,
        "<!-- Generated by scripts/render_registry.py from each module.toml. "
        "Edit module.toml, then run --write. -->",
        "| Module | Path | Visibility | Owner | Description |",
        "| --- | --- | --- | --- | --- |",
    ]
    for m in modules:
        rows.append(
            f"| `{m.name}` | `{m.path}/` | {m.visibility} | {m.owner} "
            f"| {m.description} |"
        )
    rows.append(README_END)
    return "\n".join(rows) + "\n"


def splice_readme(readme_text: str, table: str) -> str:
    """Replace the sentinel-delimited block in ``readme_text`` with ``table``.

    If the sentinels are absent, append a fresh "## Modules" section before the
    trailing newline so a first run is self-bootstrapping.
    """
    begin = readme_text.find(README_BEGIN)
    end = readme_text.find(README_END)
    table_body = table.rstrip("\n")
    if begin != -1 and end != -1 and end > begin:
        end_full = end + len(README_END)
        return readme_text[:begin] + table_body + readme_text[end_full:]
    section = f"\n## Modules\n\n{table_body}\n"
    return readme_text.rstrip("\n") + "\n" + section


def _extract_block(readme_text: str) -> str | None:
    begin = readme_text.find(README_BEGIN)
    end = readme_text.find(README_END)
    if begin == -1 or end == -1 or end < begin:
        return None
    return readme_text[begin : end + len(README_END)]


# --- checking ---------------------------------------------------------------


def _codeowners_entries(codeowners_text: str) -> dict[str, str]:
    """Map each anchored path in CODEOWNERS to the owner role in its comment."""
    entries: dict[str, str] = {}
    for line in codeowners_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("/"):
            continue
        path = stripped.split()[0]
        role = ""
        marker = "# owner role:"
        if marker in stripped:
            role = stripped.split(marker, 1)[1].strip()
        entries[path] = role
    return entries


def check_registry(root: Path) -> list[str]:
    """Return one human-readable violation per registry/manifest disagreement."""
    modules = discover_modules(root)
    violations: list[str] = []

    # --- CODEOWNERS ---------------------------------------------------------
    codeowners_path = root / "CODEOWNERS"
    if not codeowners_path.is_file():
        violations.append("CODEOWNERS is missing — run --write")
    else:
        actual = codeowners_path.read_text()
        entries = _codeowners_entries(actual)
        by_path = {m.codeowners_path: m for m in modules}
        for m in modules:
            if m.codeowners_path not in entries:
                violations.append(
                    f"CODEOWNERS: module '{m.name}' ({m.path}/) has a module.toml "
                    "but no CODEOWNERS entry — run --write"
                )
            elif entries[m.codeowners_path] != m.owner:
                violations.append(
                    f"CODEOWNERS: '{m.codeowners_path}' owner role "
                    f"'{entries[m.codeowners_path]}' disagrees with module.toml "
                    f"owner '{m.owner}' for module '{m.name}' — run --write"
                )
        for path in entries:
            if path not in by_path:
                violations.append(
                    f"CODEOWNERS: path '{path}' has no backing module.toml — "
                    "drop the line or add the manifest"
                )
        # Whole-file render must match (catches header/ordering/format drift).
        if not violations and actual != render_codeowners(modules):
            violations.append(
                "CODEOWNERS is out of sync with the manifests (format/order) — "
                "run --write"
            )

    # --- README modules block ----------------------------------------------
    readme_path = root / "README.md"
    if not readme_path.is_file():
        violations.append("README.md is missing")
    else:
        readme_text = readme_path.read_text()
        block = _extract_block(readme_text)
        if block is None:
            violations.append(
                "README.md has no generated modules block "
                f"({README_BEGIN} … {README_END}) — run --write"
            )
        else:
            for m in modules:
                if f"`{m.name}`" not in block:
                    violations.append(
                        f"README.md: module '{m.name}' is absent from the "
                        "generated modules block — run --write"
                    )
            if block.rstrip("\n") != render_readme_table(modules).rstrip("\n"):
                if not any("README.md" in v for v in violations):
                    violations.append(
                        "README.md modules block is out of sync with the "
                        "manifests — run --write"
                    )

    return violations


# --- write ------------------------------------------------------------------


def write_registry(root: Path) -> list[str]:
    """Regenerate both registries in place. Returns the paths that changed."""
    modules = discover_modules(root)
    changed: list[str] = []

    codeowners_path = root / "CODEOWNERS"
    new_codeowners = render_codeowners(modules)
    if not codeowners_path.is_file() or codeowners_path.read_text() != new_codeowners:
        codeowners_path.write_text(new_codeowners)
        changed.append("CODEOWNERS")

    readme_path = root / "README.md"
    if readme_path.is_file():
        old = readme_path.read_text()
        new = splice_readme(old, render_readme_table(modules))
        if new != old:
            readme_path.write_text(new)
            changed.append("README.md")

    return changed


# --- cli --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="fail if README/CODEOWNERS drift from the manifests (default)",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="regenerate README modules block + CODEOWNERS in place",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repo root (default: inferred from this script's location)",
    )
    args = parser.parse_args(argv)
    root = args.root if args.root is not None else repo_root()

    if args.write:
        changed = write_registry(root)
        if changed:
            print(f"render_registry: regenerated {', '.join(changed)}")
        else:
            print("render_registry: already in sync, nothing to write")
        return 0

    violations = check_registry(root)
    if violations:
        print(
            "Module registry drift (see scripts/render_registry.py):", file=sys.stderr
        )
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    module_count = len(discover_modules(root))
    print(f"module registry: ok ({module_count} module(s) checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
