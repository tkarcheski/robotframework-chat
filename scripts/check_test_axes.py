#!/usr/bin/env python3
"""CI guard: every Robot suite declares exactly one ``axis:*`` tag (RFC-008 A1).

RFC-008 (section 4) adds a new, orthogonal tagging dimension to the suite: the
**axis** a test is designed to discriminate. ``tier:*`` says *how* a test is
graded and ``verify:*`` says the grading *style*; neither says *which single
variable* -- the model, the harness, or the prompt -- a moving scoreboard cell
should be attributed to. The axis vocabulary names that variable:

  * ``axis:model``   -- the LLM model is the discriminating variable
  * ``axis:harness`` -- the coding-agent harness is, model held constant
  * ``axis:prompt``  -- a prompt / template version is
  * ``axis:none``    -- pure code: no model, harness, or prompt in the loop

This guard, a sibling to ``check_battery_scenarios.py`` / ``check_rfc_index.py``
/ ``check_agent_signoffs.py`` / ``check_submodule_ownership.py``, makes the
"exactly one axis per suite" rule mechanical -- "prompts request, checks
enforce" (ai/GIT.md). Every check is decidable from the suite source and its
transitive ``Library`` / ``Resource`` import surface (RFC-008 section 4.3); no
live model is needed.

Three checks, per RFC-008 section 4.3:

  1. **Exactly one axis.** A suite that declares no ``axis:*`` tag, or two
     different ones, is flagged. The tag may live on the suite (``Test Tags`` /
     ``Force Tags``), on an ancestor ``__init__.robot`` (which cascades to child
     suites), or per-test.
  2. **``axis:none`` must be honest.** A suite whose import surface touches an
     LLM keyword library (``rfc.keywords.LLMKeywords`` and kin) or a harness
     keyword library (``rfc.harness_keywords`` / ``harness_cli_kw`` /
     ``harness_listener_kw``) is not "pure code" and may not claim ``axis:none``.
  3. **The declared axis matches the surface.** ``axis:harness`` requires the
     harness surface; ``axis:model`` requires an LLM surface. A mismatch is a
     violation the author resolves -- either the tag is wrong or the import is.
     (``axis:prompt`` has no positive import requirement: a prompt A/B is a data
     variation, not an import one, so it cannot be decided from the surface.)

Two modes, mirroring the RFC-008 migration (section 11):

  * ``--enforce`` (default) -- **exit 1** on any violation, including an
     untagged suite. A4 made this the default once every suite carried an axis
     tag: the guard is now a hard gate, like ``check_rfc_index.py``.
  * ``--report`` -- classify every suite from its imports, list the UNTAGGED
     suites with a proposed axis, and surface violations as warnings, but
     **exit 0**. The A1 posture, kept for local triage of a work-in-progress
     tree; CI always runs the default (enforce).

Legacy provenance tags (``harness:opencode``, ``agent:claude_code``,
``prompt:reference`` -- runtime facts encoded as static tags, RFC-008 section
4.3) are *reported*, never failed: A4 reconciles them (keep-as-filter /
drop-as-provenance). Their presence here is a note, not a violation.

Usage:
  python modules/ops/scripts/check_test_axes.py              # --enforce (default)
  python modules/ops/scripts/check_test_axes.py --report     # A1 triage posture
  python modules/ops/scripts/check_test_axes.py --root path/to/robot
  python modules/ops/scripts/check_test_axes.py --suite harness_matrix
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

from robot.api import get_model
from robot.parsing.model.blocks import TestCase as _TestCaseBlock
from robot.parsing.model.statements import (
    DefaultTags,
    LibraryImport,
    ResourceImport,
    Tags,
    TestTags,
)

# core/robot -- relative to the repo root (this file lives at
# modules/ops/scripts/, so parents[3] is the repo root).
DEFAULT_ROBOT_ROOT = Path(__file__).resolve().parents[3] / "core" / "robot"

# The four-value axis vocabulary (RFC-008 section 4.1). Exactly one per suite.
AXIS_TAGS: frozenset[str] = frozenset(
    {"axis:model", "axis:harness", "axis:prompt", "axis:none"}
)

# The harness keyword surface (RFC-008 section 4.3, plus the A4 audit's
# agentic_coding addition): a suite that imports any of these -- directly or
# transitively via a ``.resource`` or an ancestor ``__init__.robot`` -- exercises
# the harness axis. Matched by module prefix so
# ``rfc.harness_keywords.HarnessKeywords`` matches ``rfc.harness_keywords``.
HARNESS_LIBRARY_MODULES: frozenset[str] = frozenset(
    {
        "rfc.harness_keywords",
        "rfc.harness_cli_kw",
        "rfc.harness_listener_kw",
        # A4 (RFC-008 section 8 / open question section 10): the agentic_coding
        # suites drive coding-agent scenarios that, since #174/#230, run live
        # harness adapters (SANDBOX_HARNESS / harness= param). Their keyword
        # library is a harness surface, not a model one -- the suites
        # discriminate the coding-agent harness, so they are axis:harness. This
        # is the audit's substantive re-classification (import => model,
        # intent => harness); it also keeps harness_matrix (which imports it)
        # consistent.
        "rfc.agentic_coding_keywords",
    }
)

# The LLM (model-under-test) keyword surface. ``rfc.keywords`` (``LLMKeywords``)
# is the canonical call surface many eval suites reach transitively via
# ``resources/llm_setup.resource`` (``rfc.graders`` is the LLM-judge surface);
# but most domain evals drive a model through their own ``rfc.<domain>_keywords``
# library and never import ``LLMKeywords`` in the ``.robot`` source. RFC-008
# section 8's ~98 ``axis:model`` count only holds if those domain keyword
# libraries count as an LLM surface, so the heuristic in :func:`_is_llm_library`
# treats any ``rfc.*_keywords`` library as model-under-test EXCEPT the handful
# that are pure infrastructure (below). A4's audit refined this membership for
# the suites that needed human judgment (agentic_coding -> harness surface;
# computer_use / dialog_e2e -> infrastructure).
LLM_EXPLICIT_MODULES: frozenset[str] = frozenset(
    {
        "rfc.keywords",  # rfc.keywords.LLMKeywords -- the canonical LLM surface
        "rfc.graders",  # LLM judge panels (module-level keywords, no class)
    }
)

# ``rfc.*_keywords`` libraries that are NOT a model-under-test surface: pure
# infrastructure a suite can import while still being ``axis:none``. A docker or
# superset suite that also drives a model reaches the model via ``rfc.keywords``
# (still ``axis:model``); these libraries alone do not.
NON_LLM_KEYWORD_MODULES: frozenset[str] = frozenset(
    {
        "rfc.docker_keywords",  # runs containers; not itself a model
        "rfc.superset_keywords",  # PostgreSQL / BI plumbing
        "rfc.hitl_keywords",  # human-in-the-loop gating mechanism
        "rfc.agent_workflow_keywords",  # synthetic workflows are deterministic
        "rfc.benchmark_keywords",  # token-throughput measurement
        "rfc.dialog_recorder",  # records dialogs to disk
        # A4 audit (RFC-008 section 8, human-adjudicated): tool/DB substrate
        # suites that import a domain *_keywords library but drive no model.
        "rfc.computer_use_keywords",  # browser/ToolSchema dispatch substrate
        "rfc.dialog_e2e_keywords",  # dialog-recorder e2e DB plumbing
    }
)

# Runtime bindings encoded as static tags (RFC-008 section 4.3's anti-pattern):
# reported so A4 can reconcile them, never failed here.
LEGACY_PROVENANCE_TAG_PREFIXES: tuple[str, ...] = ("harness:", "agent:", "prompt:")


@dataclass(frozen=True)
class ParsedRobotFile:
    """The axis-relevant facts read from one ``.robot`` / ``.resource`` file.

    Pure syntax -- no import resolution, no inheritance. ``libraries`` are the
    ``Library`` names declared in *this* file; ``resources`` are the raw
    ``Resource`` path strings as written (resolved by the caller).
    """

    path: Path
    libraries: frozenset[str]
    resources: tuple[str, ...]
    # Tags that apply to every test in the file (``Test Tags`` / ``Force Tags`` /
    # ``Default Tags``) plus every per-test ``[Tags]`` value -- the pool of tags
    # any test in the suite can carry.
    tags: frozenset[str]


@dataclass
class SuiteAxisFacts:
    """Everything the three checks need about one real (non-init) test suite."""

    path: Path
    axis_tags: frozenset[str]
    legacy_tags: frozenset[str]
    harness_surface: frozenset[str]
    llm_surface: frozenset[str]
    # Resource paths that could not be resolved statically (e.g. contain a
    # variable) -- reported so a silent gap in the surface is visible, not hidden.
    unresolved_resources: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_harness_surface(self) -> bool:
        return bool(self.harness_surface)

    @property
    def has_llm_surface(self) -> bool:
        return bool(self.llm_surface)

    @property
    def is_untagged(self) -> bool:
        return not self.axis_tags

    def suggested_axis(self) -> str:
        """The axis proposed from the import surface (RFC-008 section 8).

        A proposal, not a verdict: a suite exercising BOTH surfaces is the
        harness-vs-model boundary the audit adjudicates by hand, so it is
        surfaced as ``axis:harness?`` rather than silently decided.
        """
        if self.has_harness_surface and self.has_llm_surface:
            return "axis:harness?"  # both surfaces -- needs human judgment
        if self.has_harness_surface:
            return "axis:harness"
        if self.has_llm_surface:
            return "axis:model"
        return "axis:none"


# --- parsing (one file, pure syntax) -----------------------------------------


def parse_robot_file(path: Path | str) -> ParsedRobotFile:
    """Read the ``Library`` / ``Resource`` imports and every tag from one file.

    Uses Robot's own parser (``robot.api.get_model``) so line continuations,
    cell splitting, and section boundaries are handled exactly as at run time,
    but nothing is imported or executed -- the guard stays static. Per-test
    ``[Tags]`` are harvested only from ``TestCase`` blocks, so a keyword's
    ``[Tags]`` is never mistaken for a test's.
    """
    path = Path(path)
    model = get_model(str(path))

    libraries: set[str] = set()
    resources: list[str] = []
    tags: set[str] = set()

    for node in ast.walk(model):
        if isinstance(node, LibraryImport):
            if node.name:
                libraries.add(node.name)
        elif isinstance(node, ResourceImport):
            if node.name:
                resources.append(node.name)
        elif isinstance(node, (TestTags, DefaultTags)):
            tags.update(node.values or ())
        elif isinstance(node, _TestCaseBlock):
            for stmt in node.body:
                if isinstance(stmt, Tags):
                    tags.update(stmt.values or ())

    return ParsedRobotFile(
        path=path,
        libraries=frozenset(libraries),
        resources=tuple(resources),
        tags=frozenset(tags),
    )


# --- import-surface resolution (transitive across Resource files) ------------


def _resolve_resource(importing_file: Path, raw: str) -> Path | None:
    """Resolve a ``Resource`` path string relative to the importing file.

    Returns None when the path cannot be resolved statically -- it references a
    variable (``${...}``) or points at a file that is not on disk. Callers
    record the miss rather than guessing.
    """
    if "$" in raw or "{" in raw:
        return None
    candidate = (importing_file.parent / raw).resolve()
    return candidate if candidate.is_file() else None


def resolve_import_surface(
    path: Path, *, _seen: set[Path] | None = None
) -> tuple[frozenset[str], tuple[str, ...]]:
    """The transitive set of ``Library`` names reachable from ``path``.

    Follows ``Resource`` imports depth-first, guarding against cycles with a
    ``_seen`` set of resolved paths. Returns the library set plus the list of
    resource strings that could not be resolved (surfaced, not swallowed).
    """
    path = Path(path).resolve()
    seen = _seen if _seen is not None else set()
    if path in seen:
        return frozenset(), ()
    seen.add(path)
    if not path.is_file():
        return frozenset(), ()

    parsed = parse_robot_file(path)
    libraries: set[str] = set(parsed.libraries)
    unresolved: list[str] = []
    for raw in parsed.resources:
        resolved = _resolve_resource(path, raw)
        if resolved is None:
            unresolved.append(raw)
            continue
        child_libs, child_unresolved = resolve_import_surface(resolved, _seen=seen)
        libraries.update(child_libs)
        unresolved.extend(child_unresolved)
    return frozenset(libraries), tuple(unresolved)


# --- suite-tag inheritance (ancestor __init__.robot cascade) -----------------


def ancestor_init_files(suite_path: Path, root: Path) -> list[Path]:
    """The ``__init__.robot`` files that cascade tags/setup onto ``suite_path``.

    Robot applies a directory-init suite's ``Test Tags`` (and its imports, via
    Suite Setup) to every test in the directory and its sub-suites, so the
    effective axis of a suite includes any axis tag set on an ancestor
    ``__init__.robot``. Ordered outermost-first (root down to the suite dir).
    """
    suite_path = suite_path.resolve()
    root = root.resolve()
    inits: list[Path] = []
    try:
        relative = suite_path.parent.relative_to(root)
    except ValueError:
        return inits
    # The root directory's own __init__.robot (if any) cascades first.
    root_init = root / "__init__.robot"
    if root_init.is_file():
        inits.append(root_init)
    current = root
    for part in relative.parts:
        current = current / part
        candidate = current / "__init__.robot"
        if candidate.is_file():
            inits.append(candidate)
    return inits


def _matches_any_prefix(lib: str, modules: frozenset[str]) -> bool:
    """Whether ``lib`` is, or is a class imported from, one of ``modules``.

    A ``Library rfc.keywords.LLMKeywords`` import matches the ``rfc.keywords``
    module prefix; ``rfc.keyword_helpers`` does not (the match is
    dot-boundary-aware, never a bare ``startswith``).
    """
    return any(lib == m or lib.startswith(m + ".") for m in modules)


def _is_harness_library(lib: str) -> bool:
    """Whether ``lib`` is one of the three harness keyword surfaces (RFC-008 4.3)."""
    return _matches_any_prefix(lib, HARNESS_LIBRARY_MODULES)


def _is_llm_library(lib: str) -> bool:
    """Whether ``lib`` puts a model under test (the model-under-test surface).

    ``rfc.keywords`` / ``rfc.graders`` are the explicit surfaces; every other
    ``rfc.*_keywords`` domain library is treated as a model driver EXCEPT the
    pure-infrastructure exceptions (:data:`NON_LLM_KEYWORD_MODULES`). A harness
    library is never an LLM library -- the harness axis owns it.
    """
    if _is_harness_library(lib):
        return False
    if _matches_any_prefix(lib, NON_LLM_KEYWORD_MODULES):
        return False
    if _matches_any_prefix(lib, LLM_EXPLICIT_MODULES):
        return True
    return lib.startswith("rfc.") and any(
        segment.endswith("_keywords") for segment in lib.split(".")
    )


def _harness_surface(libraries: frozenset[str]) -> set[str]:
    return {lib for lib in libraries if _is_harness_library(lib)}


def _llm_surface(libraries: frozenset[str]) -> set[str]:
    return {lib for lib in libraries if _is_llm_library(lib)}


def collect_suite_facts(suite_path: Path, root: Path) -> SuiteAxisFacts:
    """Resolve one suite's axis tags and import surface, inheritance included."""
    suite_path = Path(suite_path)
    inits = ancestor_init_files(suite_path, root)

    tags: set[str] = set()
    libraries: set[str] = set()
    unresolved: list[str] = []

    for source in (*inits, suite_path):
        parsed = parse_robot_file(source)
        tags.update(parsed.tags)
        libs, missed = resolve_import_surface(source)
        libraries.update(libs)
        unresolved.extend(missed)

    all_libraries = frozenset(libraries)
    axis_tags = frozenset(t for t in tags if t in AXIS_TAGS)
    legacy_tags = frozenset(
        t for t in tags if t.startswith(LEGACY_PROVENANCE_TAG_PREFIXES)
    )
    return SuiteAxisFacts(
        path=suite_path,
        axis_tags=axis_tags,
        legacy_tags=legacy_tags,
        harness_surface=frozenset(_harness_surface(all_libraries)),
        llm_surface=frozenset(_llm_surface(all_libraries)),
        unresolved_resources=tuple(dict.fromkeys(unresolved)),
    )


# --- the three checks --------------------------------------------------------


def axis_violations(facts: SuiteAxisFacts) -> list[str]:
    """Every RFC-008 section 4.3 violation for one suite (excludes untagged).

    An *untagged* suite (no ``axis:*`` at all) is not returned here: it is a
    report-mode warning and an enforce-mode failure handled by the caller, which
    knows the mode. This function reports the mistakes an author made *while*
    declaring an axis, so ``--report`` can surface them without failing CI.
    """
    v: list[str] = []
    name = facts.path.name
    axes = facts.axis_tags

    # Check 1 -- exactly one axis (the multi-axis half; untagged is the caller's).
    if len(axes) > 1:
        v.append(
            f"{name}: declares {len(axes)} axis tags {sorted(axes)} -- a suite "
            "discriminates exactly one variable, so it carries exactly one axis"
        )

    # Check 2 -- axis:none must be honest about its import surface.
    if "axis:none" in axes and (facts.has_harness_surface or facts.has_llm_surface):
        surface = sorted(facts.harness_surface | facts.llm_surface)
        v.append(
            f"{name}: claims axis:none but imports an LLM/harness keyword library "
            f"{surface} -- it is not pure code; retag it axis:model or axis:harness"
        )

    # Check 3 -- the declared axis must match the exercised surface.
    if "axis:harness" in axes and not facts.has_harness_surface:
        v.append(
            f"{name}: declares axis:harness but imports no harness keyword library "
            f"({sorted(HARNESS_LIBRARY_MODULES)}) -- the tag or the import is wrong"
        )
    if "axis:model" in axes and not facts.has_llm_surface:
        v.append(
            f"{name}: declares axis:model but imports no LLM keyword library -- "
            "the tag or the import is wrong"
        )

    return v


# --- discovery ---------------------------------------------------------------


def discover_suites(root: Path) -> list[Path]:
    """Every real test suite under ``root``: ``*.robot`` minus ``__init__.robot``.

    ``__init__.robot`` files are suite-directory configuration, not test suites
    (they hold no test cases), so they are never graded on their own -- their
    axis tags cascade onto the real suites via :func:`ancestor_init_files`.
    """
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.rglob("*.robot") if p.is_file() and p.name != "__init__.robot"
    )


# --- orchestration -----------------------------------------------------------


@dataclass
class Report:
    """The classification of every suite under a root, ready to print."""

    tagged: dict[str, list[SuiteAxisFacts]]  # axis value -> suites carrying it
    untagged: list[SuiteAxisFacts]
    violations: list[str]
    legacy: list[SuiteAxisFacts]  # suites still carrying a legacy provenance tag

    @property
    def suite_count(self) -> int:
        return sum(len(s) for s in self.tagged.values()) + len(self.untagged)


def build_report(facts: list[SuiteAxisFacts]) -> Report:
    """Bucket suites by axis, collect untagged suites and every violation."""
    tagged: dict[str, list[SuiteAxisFacts]] = {a: [] for a in sorted(AXIS_TAGS)}
    untagged: list[SuiteAxisFacts] = []
    violations: list[str] = []
    legacy: list[SuiteAxisFacts] = []

    for f in facts:
        violations.extend(axis_violations(f))
        if f.legacy_tags:
            legacy.append(f)
        if f.is_untagged:
            untagged.append(f)
        else:
            # A suite with exactly one axis buckets under it; a multi-axis suite
            # (a violation) is listed under each so the summary stays honest.
            for axis in sorted(f.axis_tags):
                tagged.setdefault(axis, []).append(f)
    return Report(
        tagged=tagged, untagged=untagged, violations=violations, legacy=legacy
    )


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def print_report(report: Report, root: Path, *, enforce: bool) -> None:
    """Human-readable classification: per-axis counts, untagged proposals, legacy."""
    print(f"Axis tags: {report.suite_count} suite(s) under {root}")
    for axis in sorted(AXIS_TAGS):
        suites = report.tagged.get(axis, [])
        print(f"  {axis:<14} {len(suites)} suite(s)")

    if report.untagged:
        header = "MISSING axis tag" if enforce else "untagged (proposed axis)"
        print(f"\n{len(report.untagged)} suite(s) {header}:")
        for f in report.untagged:
            print(f"  - {_rel(f.path, root):<60} -> {f.suggested_axis()}")

    if report.legacy:
        print(
            f"\n{len(report.legacy)} suite(s) still carry a legacy provenance tag "
            "(runtime fact in a static tag -- A4 reconciles, not failed here):"
        )
        for f in report.legacy:
            print(f"  - {_rel(f.path, root):<60} {sorted(f.legacy_tags)}")

    if report.violations:
        label = "violations" if enforce else "violations (warnings in report mode)"
        print(f"\n{len(report.violations)} {label}:")
        for msg in report.violations:
            print(f"  - {msg}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--report",
        action="store_true",
        help="Classify and warn but never fail (exit 0); the A1 triage posture.",
    )
    mode.add_argument(
        "--enforce",
        action="store_true",
        help="Fail (exit 1) on any violation, including an untagged suite. Default since A4.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROBOT_ROOT,
        help=f"Robot suite root to check (default: {DEFAULT_ROBOT_ROOT}).",
    )
    parser.add_argument(
        "--suite",
        type=str,
        default=None,
        help="Check only suites whose filename stem matches this (substring).",
    )
    args = parser.parse_args(argv)
    # A4: enforce is the default gate; --report explicitly opts back out.
    enforce = not args.report

    root: Path = args.root
    if not root.is_dir():
        print(f"axis guard: robot root not found: {root}", file=sys.stderr)
        return 1

    suites = discover_suites(root)
    if args.suite is not None:
        suites = [s for s in suites if args.suite in s.stem]
        if not suites:
            print(f"axis guard: no suite matching {args.suite!r} under {root}")
            return 1
    if not suites:
        print(f"axis guard: no suites found under {root}", file=sys.stderr)
        return 1

    facts = [collect_suite_facts(s, root) for s in suites]
    report = build_report(facts)
    print_report(report, root, enforce=enforce)

    if enforce:
        # Enforce: an untagged suite is a failure, as is any check violation.
        failures = len(report.violations) + len(report.untagged)
        if failures:
            print(
                f"\naxis guard: FAIL ({failures} issue(s)) -- see RFC-008 section 4.3",
                file=sys.stderr,
            )
            return 1
        print(f"\naxis guard: ok ({report.suite_count} suite(s), enforce mode)")
        return 0

    # Report mode (A1 triage posture, opt-in via --report): classify and warn.
    print(
        f"\naxis guard: report mode ({report.suite_count} suite(s); "
        f"{len(report.untagged)} untagged, {len(report.violations)} warning(s)) "
        "-- opt-in triage; CI runs the default (--enforce)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
