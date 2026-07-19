"""Keyword-surface snapshot guard.

Robot keyword names are this project's PUBLIC API: Robot suites here and in the
public mirror invoke keywords by these exact names, so a rename, removal, or
addition is a breaking or surface-widening change.

Robot Framework auto-exposes **every public method** of a keyword-library class
as a keyword unless the class sets ``ROBOT_AUTO_KEYWORDS = False``. The
``@keyword`` decorator is therefore optional: it only *renames* a keyword, or —
with auto-keywords switched off — opts a single method in. Snapshotting only the
``@keyword``-decorated methods (the original AST approach) was structurally blind
to that auto-exposed surface: an undecorated public method — or an entire
undecorated library such as ``AgenticCodingKeywords`` — was a live keyword that
tier-4 suites invoke, yet invisible to the guard, so a rename could silently
break those suites (#152).

The library **set** to enumerate is derived from the suites themselves: every
``Library rfc.<...>`` import across ``robot/`` (both ``.robot`` suites and
``.resource`` files) is parsed and resolved to its Python object. This is the
truth the guard must protect — exactly what suites load — rather than a filename
heuristic. The earlier ``src/rfc/*_keywords.py`` glob missed two live surfaces
(#208): ``rfc.keywords.LLMKeywords`` (13 keywords incl. ``Ask LLM`` /
``Grade Answer``, the most-imported library — its file has no ``_`` before
``keywords.py``), and any library class not named ``*Keywords`` (e.g.
``rfc.harness_cli_kw.HarnessCliRunner``, ``rfc.dialog_recorder.DialogRecorder``).
Deriving from imports also covers module keyword libraries (``Library rfc.graders``).
A variable-substituted import (``Library ${LIB}``) binds only at Robot runtime and
cannot be resolved statically, so it is rejected rather than silently skipped — an
``rfc.*`` library loaded by variable can never slip past the guard uncounted (#257).

Each resolved library — class or module — is enumerated for the exact keyword
names Robot exposes at runtime, applying Robot's own discovery rules
(``ROBOT_AUTO_KEYWORDS``, ``@keyword`` renames via ``robot_name``,
``@not_keyword`` exclusions, private ``_``-prefixed methods, property/non-routine
exclusion, module ``__all__``, and inherited methods) together with Robot's own
``printable_name`` formatter. Enumeration runs at the *class* level (never
instantiating the library) so libraries whose ``__init__`` requires arguments (a
model, a database URL) are still covered. The ``*_matches_robot_discovery`` tests
pin this replication to Robot's real ``TestLibrary`` discovery — for the fixture
shapes and for every no-arg library actually imported — so it cannot drift.

Regenerate the snapshot after an *intentional* surface change with::

    uv run python core/tests/test_keyword_surface.py
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import re
from collections.abc import Iterator
from functools import cached_property, partial
from pathlib import Path

from robot.api.deco import keyword, not_keyword
from robot.utils import printable_name

_ROBOT_DIR = Path(__file__).resolve().parent.parent / "robot"
_SNAPSHOT = Path(__file__).resolve().parent / "keyword_surface_snapshot.txt"

# A ``Library    rfc.<dotted.path>`` setting, capturing the import path only (no
# ``WITH NAME`` alias, no arguments). Only ``rfc.*`` libraries are the project's
# own public surface; Robot's standard libraries (Collections, String, …) are
# out of scope. Settings are case-insensitive in Robot, hence ``IGNORECASE``.
_LIBRARY_IMPORT = re.compile(
    r"^\s*Library\s+(rfc\.[\w.]+)", re.IGNORECASE | re.MULTILINE
)

# A ``Library`` setting whose import path contains a Robot variable
# (``${...}``/``@{...}``/``&{...}``/``%{...}``) — a *variable-substituted* import.
# Robot binds these at runtime, so the path (and thus the library) is unknown
# statically. Commented-out lines (``# Library ...``) and prose that merely
# mentions the word never match, exactly as for the static-import regex, because
# ``^\s*Library`` anchors to an active setting. Captured to reject, not resolve
# (#257).
_VARIABLE_LIBRARY_IMPORT = re.compile(
    r"^\s*Library\s+(\S*[$@&%]\{[^}]*\}\S*)", re.IGNORECASE | re.MULTILINE
)


def _parse_library_imports(robot_dir: Path = _ROBOT_DIR) -> set[str]:
    """Return the distinct ``rfc.*`` library import paths across the suite tree.

    Scans every ``.robot`` suite and ``.resource`` file (suites import libraries
    directly and via shared resources) for ``Library rfc...`` settings.

    A **variable-substituted** import (``Library ${LIB}``) binds only at Robot
    runtime, so the guard cannot see which library it loads and would under-cover
    that library's keyword surface — the exact #152/#208 blind spot this guard
    exists to close. Such imports are therefore rejected with a ``ValueError``
    naming each offending file (#257) rather than silently skipped; resolving the
    variable is deliberately out of scope. No suite uses one today, so this fires
    only the day one is introduced, making the coverage gap a conscious decision.
    """
    paths: set[str] = set()
    variable_imports: list[str] = []
    for path in (*robot_dir.rglob("*.robot"), *robot_dir.rglob("*.resource")):
        text = path.read_text(encoding="utf-8")
        paths.update(match.group(1) for match in _LIBRARY_IMPORT.finditer(text))
        variable_imports.extend(
            f"  {path.relative_to(robot_dir)}: Library {match.group(1)}"
            for match in _VARIABLE_LIBRARY_IMPORT.finditer(text)
        )
    if variable_imports:
        raise ValueError(
            "Keyword-surface guard found variable-substituted Library import(s) it "
            "cannot resolve. Robot binds these at runtime, so the guard is blind to "
            "the rfc.* keyword surface they load and would silently under-cover it "
            "(#257):\n"
            + "\n".join(sorted(variable_imports))
            + "\nRewrite as a static `Library rfc.<dotted.path>` so the guard sees "
            "its surface, or extend the guard to resolve the variable."
        )
    return paths


def _resolve_library(import_path: str) -> object:
    """Resolve a Robot ``Library`` import path to its Python object.

    ``rfc.graders`` resolves to a *module* (a module keyword library);
    ``rfc.keywords.LLMKeywords`` resolves to the *class* ``LLMKeywords`` in module
    ``rfc.keywords``. This mirrors Robot's own resolution: a path importable as a
    module is a module library, otherwise the final segment names a class in the
    parent module. Import failures are deliberately not swallowed — a library that
    will not import has no discoverable surface, and hiding it would reopen the
    exact blind spot this guard exists to close (#152/#208). Only the "path is not
    itself a module" case (``ModuleNotFoundError`` naming the full path) falls
    through to class resolution; a deeper missing dependency propagates.
    """
    try:
        spec = importlib.util.find_spec(import_path)
    except ModuleNotFoundError as exc:
        if exc.name != import_path:
            raise
        spec = None
    if spec is not None:
        return importlib.import_module(import_path)
    module_name, _, class_name = import_path.rpartition(".")
    return getattr(importlib.import_module(module_name), class_name)


def _iter_libraries(robot_dir: Path = _ROBOT_DIR) -> Iterator[object]:
    """Yield each distinct ``rfc.*`` keyword library (class or module) imported."""
    for import_path in sorted(_parse_library_imports(robot_dir)):
        yield _resolve_library(import_path)


def _exposed_keyword_names(library: object) -> set[str]:
    """Return the Robot keyword names ``library`` exposes at runtime.

    Mirrors ``robot.running.testlibraries`` discovery (Robot 7) for both class and
    module libraries: an attribute becomes a keyword when it is a public routine —
    or is explicitly opted in with ``@keyword`` while ``ROBOT_AUTO_KEYWORDS`` is
    off — and is neither marked ``@not_keyword`` nor a property. A *module* library
    that defines ``__all__`` exposes only its exported routines (Robot honours
    ``__all__``). The keyword name is the ``@keyword("...")`` override when given,
    else ``printable_name`` of the attribute. Operates on the class, not an
    instance, so libraries with required constructor arguments are covered without
    being instantiated.

    A bare ``functools.partial`` attribute surfaces only from *module* libraries.
    Class libraries are discovered via ``StaticKeywordCreator(avoid_properties=True)``
    whose ``_pre_validate_method`` rejects any non-routine (a ``partial`` included)
    before ``_validate_method`` runs; module libraries skip that pre-validation, so
    only ``_validate_method`` — which admits a ``partial`` — applies. The guard
    replicates that split rather than admitting partials everywhere (#211).
    """
    auto_keywords = getattr(library, "ROBOT_AUTO_KEYWORDS", True)
    is_module = inspect.ismodule(library)
    module_exports: set[str] | None = None
    if is_module:
        exports = getattr(library, "__all__", None)
        if exports is not None:
            module_exports = set(exports)
    names: set[str] = set()
    for attr_name in dir(library):
        try:
            attr = inspect.getattr_static(library, attr_name)
        except AttributeError:  # dynamically provided attribute — not a method
            continue
        func = attr.__func__ if isinstance(attr, (classmethod, staticmethod)) else attr
        # Inclusion: any public attribute under auto-keywords, or a method that
        # opted in with @keyword (which sets ``robot_name``) when auto is off. A
        # module's ``__all__`` further restricts the public set to its exports.
        explicitly_included = hasattr(func, "robot_name")
        included = (
            auto_keywords and not attr_name.startswith("_")
        ) or explicitly_included
        if (
            module_exports is not None
            and attr_name not in module_exports
            and not explicitly_included
        ):
            included = False
        if not included:
            continue
        # Exclusion: properties / non-routines are not keywords, and @not_keyword
        # opts a public method back out. Robot's non-routine handling differs by
        # library kind (see docstring): a bare ``functools.partial`` is admitted
        # only from a module library; a class library's ``_pre_validate_method``
        # rejects it (#211).
        if isinstance(attr, cached_property):
            continue
        if is_module:
            if not (inspect.isroutine(func) or isinstance(func, partial)):
                continue
        elif not inspect.isroutine(func):
            continue
        if getattr(func, "robot_not_keyword", False):
            continue
        robot_name = getattr(func, "robot_name", None)
        names.add(robot_name or printable_name(attr_name, code_style=True))
    return names


def collect_keyword_surface(robot_dir: Path = _ROBOT_DIR) -> list[str]:
    """Return the sorted, de-duplicated Robot keyword surface suites import."""
    names: set[str] = set()
    for library in _iter_libraries(robot_dir):
        names |= _exposed_keyword_names(library)
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
        "Robot exposes every public library method as a keyword — not only "
        "@keyword-decorated ones — so an added/renamed/removed public method is a "
        "public-API change. If this is intentional, regenerate the snapshot and add "
        "a CHANGELOG migration note.\n"
        "Regenerate with: uv run python core/tests/test_keyword_surface.py\n"
        f"  added:   {added}\n"
        f"  removed: {removed}"
    )


# --------------------------------------------------------------------------
# Guard-behaviour tests: prove the enumeration sees the auto-exposed surface,
# and that it matches what Robot actually exposes at runtime.
# --------------------------------------------------------------------------


class _FixtureKeywords:
    """Fixture library exercising Robot's auto-exposure rules for the guard tests.

    Named with a leading underscore so pytest does not collect it as a test class.
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def undecorated_public_keyword(self) -> None:
        """Auto-exposed: no decorator, yet a live Robot keyword (the #152 gap)."""

    @keyword("Renamed Keyword")
    def some_method(self) -> None:
        """@keyword renames this — the method name must not surface."""

    @not_keyword
    def public_but_excluded(self) -> None:
        """Public but explicitly opted out with @not_keyword."""

    def _private_helper(self) -> None:
        """Underscore-prefixed — never a keyword."""


def test_enumeration_includes_undecorated_public_methods() -> None:
    """The core of #152: undecorated public methods are live keywords."""
    names = _exposed_keyword_names(_FixtureKeywords)
    assert "Undecorated Public Keyword" in names  # auto-exposed, was invisible
    assert "Renamed Keyword" in names  # @keyword override honoured
    assert "Some Method" not in names  # renamed away from the method name
    assert "Public But Excluded" not in names  # @not_keyword excluded
    assert "Private Helper" not in names  # _-prefixed excluded


def test_guard_catches_undecorated_method_rename() -> None:
    """Renaming an undecorated public method must surface as remove + add.

    The old decorated-only guard saw neither name and stayed green while the
    rename silently broke every suite that invoked the keyword.
    """

    class _RenamedFixture:
        def undecorated_public_keyword_renamed(self) -> None:
            """Same method as the fixture, renamed — no decorator involved."""

    before = _exposed_keyword_names(_FixtureKeywords)
    after = _exposed_keyword_names(_RenamedFixture)
    removed = before - after
    added = after - before
    assert "Undecorated Public Keyword" in removed
    assert "Undecorated Public Keyword Renamed" in added


def test_enumeration_matches_robot_discovery() -> None:
    """Pin the replication to Robot's own runtime discovery.

    Build the fixture with Robot's real ``TestLibrary`` and require the names to
    match ``_exposed_keyword_names`` exactly, so this guard's enumeration cannot
    drift from what Robot actually exposes.
    """
    from robot.running.testlibraries import TestLibrary

    library = TestLibrary.from_class(_FixtureKeywords)
    robot_names = {kw.name for kw in library.keywords}
    assert _exposed_keyword_names(_FixtureKeywords) == robot_names
    assert robot_names == {"Undecorated Public Keyword", "Renamed Keyword"}


class _ShapeFixtureKeywords:
    """Fixture pinning Robot's discovery for method *shapes* the real libraries
    use (``@staticmethod``/``@classmethod``/``@property``) but the primary
    fixture omits — e.g. ``ifeval_keywords`` exposes its ``check_*`` helpers as
    ``@staticmethod``, and several libraries carry public ``@property``/
    ``cached_property`` attributes that must NOT surface as keywords.
    """

    @staticmethod
    def static_keyword() -> None:
        """A ``@staticmethod`` is a live keyword (Robot unwraps it)."""

    @classmethod
    def class_keyword(cls) -> None:
        """A ``@classmethod`` is a live keyword too."""

    @staticmethod
    @keyword("Renamed Static")
    def renamed_static() -> None:
        """A renamed ``@staticmethod`` keyword — method name must not surface."""

    @property
    def some_property(self) -> int:
        """A ``@property`` is NOT a keyword and must never be evaluated."""
        raise AssertionError("property getter must not be invoked during discovery")

    @cached_property
    def some_cached_property(self) -> int:
        """A ``cached_property`` is NOT a keyword either."""
        raise AssertionError("cached_property must not be invoked during discovery")

    def real_keyword(self) -> None:
        """A plain undecorated public method — a live keyword."""


def test_enumeration_matches_robot_discovery_across_shapes() -> None:
    """Pin the guard to Robot for static/class/property shapes real libs use.

    These branches of ``_exposed_keyword_names`` (static/class-method unwrapping,
    property and ``cached_property`` exclusion) are not exercised by the primary
    fixture nor — for ``ROBOT_AUTO_KEYWORDS``/property — by any current library,
    so this pins them against Robot's own runtime discovery to catch a future
    regression. Uses ``getattr_static`` semantics: property getters must never
    run during enumeration.
    """
    from robot.running.testlibraries import TestLibrary

    robot_names = {
        kw.name for kw in TestLibrary.from_class(_ShapeFixtureKeywords).keywords
    }
    assert _exposed_keyword_names(_ShapeFixtureKeywords) == robot_names
    assert robot_names == {
        "Static Keyword",
        "Class Keyword",
        "Renamed Static",
        "Real Keyword",
    }


def _partial_target(*args: object) -> None:
    """Plain function the ``functools.partial`` fidelity fixtures wrap (#211)."""


class _PartialFixtureKeywords:
    """Fixture pinning Robot's exclusion of a bare class-level ``functools.partial``.

    Class libraries are discovered via ``StaticKeywordCreator(avoid_properties=True)``,
    whose ``_pre_validate_method`` rejects any non-routine attribute — a bare
    ``partial`` included — so Robot does NOT expose it. The attribute names mirror
    the issue's evidence (``Normal`` kept, ``Part`` dropped).
    """

    part = partial(_partial_target, "x")

    def normal(self) -> None:
        """A plain undecorated public method — a live keyword."""


def test_class_level_partial_excluded_matching_robot_discovery() -> None:
    """A bare class-level ``functools.partial`` is NOT a keyword (#211).

    Robot builds class libraries with ``StaticKeywordCreator(avoid_properties=True)``;
    its ``_pre_validate_method`` rejects the non-routine ``partial`` before
    ``_validate_method`` runs, so the partial never surfaces. The guard previously
    admitted it via an unconditional ``isinstance(func, partial)`` clause — the
    over-inclusion this pins closed.
    """
    from robot.running.testlibraries import TestLibrary

    robot_names = {
        kw.name for kw in TestLibrary.from_class(_PartialFixtureKeywords).keywords
    }
    assert _exposed_keyword_names(_PartialFixtureKeywords) == robot_names
    assert robot_names == {"Normal"}
    assert "Part" not in robot_names


def test_module_level_partial_included_matching_robot_discovery() -> None:
    """A module-level ``functools.partial`` IS a keyword, unlike a class one (#211).

    Module libraries use ``StaticKeywordCreator`` WITHOUT ``avoid_properties``, so
    Robot skips ``_pre_validate_method`` and only ``_validate_method`` runs, which
    admits a ``partial``. Pinning both directions keeps the class-vs-module split
    faithful: dropping partial handling outright would silently drop a real module
    keyword — the #152 under-inclusion class this guard exists to prevent.
    """
    import types

    from robot.running.testlibraries import TestLibrary

    module = types.ModuleType("_partial_fixture_module")
    module.normal = _partial_target  # type: ignore[attr-defined]
    module.part = partial(_partial_target, "x")  # type: ignore[attr-defined]
    module.__all__ = ["normal", "part"]  # type: ignore[attr-defined]

    robot_names = {kw.name for kw in TestLibrary.from_module(module).keywords}
    assert _exposed_keyword_names(module) == robot_names
    assert robot_names == {"Normal", "Part"}


class _AutoKeywordsOffKeywords:
    """Fixture for the ``ROBOT_AUTO_KEYWORDS = False`` opt-in path.

    No current library sets this, so the guard's opt-in branch is otherwise
    untested. With auto-keywords off, only ``@keyword``-decorated methods are
    exposed; undecorated public methods are not.
    """

    ROBOT_AUTO_KEYWORDS = False

    @keyword
    def opted_in(self) -> None:
        """Decorated: exposed even with auto-keywords off."""

    @keyword("Custom Name")
    def custom(self) -> None:
        """Decorated with an explicit name."""

    def not_opted_in(self) -> None:
        """Undecorated: NOT a keyword when auto-keywords are off."""


def test_enumeration_matches_robot_discovery_auto_keywords_off() -> None:
    """Pin the ``ROBOT_AUTO_KEYWORDS = False`` opt-in path against Robot."""
    from robot.running.testlibraries import TestLibrary

    robot_names = {
        kw.name for kw in TestLibrary.from_class(_AutoKeywordsOffKeywords).keywords
    }
    assert _exposed_keyword_names(_AutoKeywordsOffKeywords) == robot_names
    assert robot_names == {"Opted In", "Custom Name"}


# --------------------------------------------------------------------------
# Import-derived discovery tests: the library set now tracks real Library
# imports (#208), covering module libraries and non-``*Keywords`` classes.
# --------------------------------------------------------------------------


def test_module_library_enumeration_matches_robot_discovery() -> None:
    """Pin module-library discovery to Robot using the real ``rfc.graders`` lib.

    ``Library rfc.graders`` is a module keyword library whose ``get_grader``
    factory the tier-0 openai-evals suite invokes as ``Get Grader``. Module
    libraries take a different Robot discovery path (``__all__``-aware, functions
    only) than class libraries, so pin it against Robot's real ``from_module``.
    """
    import rfc.graders
    from robot.running.testlibraries import TestLibrary

    robot_names = {kw.name for kw in TestLibrary.from_module(rfc.graders).keywords}
    assert _exposed_keyword_names(rfc.graders) == robot_names
    assert "Get Grader" in robot_names


def test_enumeration_matches_robot_for_no_arg_imported_libraries() -> None:
    """Every imported library Robot can build without args enumerates identically.

    Cross-checks the guard's static enumeration against Robot's own runtime
    discovery for each ``rfc.*`` library actually imported by a suite. Libraries
    whose ``__init__`` requires arguments cannot be instantiated by Robot with no
    args and are enumerated at class level only — the documented gap (#207) — so
    they are skipped here rather than masking a real mismatch.
    """
    from robot.errors import DataError
    from robot.running.testlibraries import TestLibrary

    checked = 0
    for import_path in sorted(_parse_library_imports()):
        library = _resolve_library(import_path)
        try:
            robot_lib = (
                TestLibrary.from_module(library)
                if inspect.ismodule(library)
                else TestLibrary.from_class(library)
            )
            robot_names = {kw.name for kw in robot_lib.keywords}
        except DataError:
            continue  # requires constructor arguments — class-level enumeration
        assert _exposed_keyword_names(library) == robot_names, import_path
        checked += 1
    assert checked, "no importable libraries were cross-checked against Robot"


def test_guard_fails_when_a_suite_imports_an_unsnapshotted_library(
    tmp_path: Path,
) -> None:
    """A suite importing a library absent from the snapshot must break the guard.

    This is the #208 regression: ``rfc.keywords.LLMKeywords`` was imported by
    dozens of suites yet the file-glob guard enumerated an empty surface for it
    and stayed green. Deriving the library set from the import makes the surface
    track reality, so an unsnapshotted import shows up as drift.
    """
    suite = tmp_path / "uses_llm.robot"
    suite.write_text(
        "*** Settings ***\n"
        "Library    rfc.keywords.LLMKeywords    WITH NAME    LLM\n"
        "*** Test Cases ***\n"
        "Smoke\n"
        "    Log    hi\n",
        encoding="utf-8",
    )
    derived = set(collect_keyword_surface(robot_dir=tmp_path))
    # The parser + resolver followed the import to the real library surface …
    assert {"Ask LLM", "Grade Answer"} <= derived
    # … so a snapshot missing any of those names is unequal to the derived
    # surface, i.e. the guard's comparison fails (the #208 breakage it now
    # catches but the file-glob guard did not).
    stale_snapshot = derived - {"Ask LLM"}
    assert derived != stale_snapshot


# --------------------------------------------------------------------------
# Parser-hardening tests (test-design, #253 verdict): the import parser is the
# new core of the guard (#208). These pin its contract directly so a future
# "simplification" of the regex or resolver cannot silently reopen a blind spot.
# --------------------------------------------------------------------------


def _write_suite(root: Path, name: str, body: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_parse_library_imports_strips_aliases_and_excludes_noise(
    tmp_path: Path,
) -> None:
    """Capture the ``rfc.*`` path only, from every alias/arg form, and nothing else.

    Robot accepts both ``WITH NAME`` (legacy) and ``AS`` (Robot 7) aliases and
    positional library arguments — all of which follow the import path. Robot
    standard libraries, commented-out imports, and prose that merely mentions the
    word ``Library`` must never be captured, and the same class imported from
    several files collapses to one path.
    """
    _write_suite(
        tmp_path,
        "suite.robot",
        "*** Settings ***\n"
        "Documentation     Uses Library rfc.prose.NotAnImport in its text\n"
        "Library    rfc.keywords.LLMKeywords    WITH NAME    LLM\n"
        "Library    rfc.hitl_keywords.HitlKeywords    AS    Hitl\n"
        "Library    rfc.safety_keywords.SafetyKeywords    arg1    arg2\n"
        "Library    rfc.graders    # trailing inline comment\n"
        "Library    Collections\n"
        "Library    Browser    headless=True\n"
        "# Library    rfc.commented.ShouldNotAppear\n"
        "    # Library    rfc.indented_comment.AlsoNot\n",
    )
    _write_suite(
        tmp_path,
        "shared/base.resource",
        "*** Settings ***\n"
        # same class, different file + alias — must dedupe to one path
        "Library    rfc.keywords.LLMKeywords    WITH NAME    LLM2\n",
    )
    assert _parse_library_imports(tmp_path) == {
        "rfc.keywords.LLMKeywords",
        "rfc.hitl_keywords.HitlKeywords",
        "rfc.safety_keywords.SafetyKeywords",
        "rfc.graders",
    }


def test_parse_library_imports_flags_variable_substituted_imports(
    tmp_path: Path,
) -> None:
    """A ``Library ${VAR}`` import is rejected loudly, never silently skipped (#257).

    Robot binds a variable-substituted ``Library`` path at runtime, so the guard
    cannot see which ``rfc.*`` library it loads and would under-cover its keyword
    surface — the exact #152/#208 blind-spot class the guard exists to close. No
    suite uses one today (grep is empty), so this is a latent gap; the guard raises
    rather than resolving the variable (variable resolution is deliberately out of
    scope), turning the invisible gap into a conscious decision. The error names
    each offending file and import so the fix is obvious.
    """
    import pytest

    _write_suite(
        tmp_path,
        "var.robot",
        "*** Settings ***\nLibrary    ${LIB}\nLibrary    ${PKG}.keywords.LLMKeywords\n",
    )
    with pytest.raises(ValueError, match="variable-substituted Library import") as exc:
        _parse_library_imports(tmp_path)
    message = str(exc.value)
    assert "var.robot" in message
    assert "${LIB}" in message
    assert "${PKG}.keywords.LLMKeywords" in message


def test_parse_library_imports_ignores_commented_or_prose_variable_imports(
    tmp_path: Path,
) -> None:
    """Commented-out or prose ``Library ${VAR}`` mentions must not trip the guard.

    Only a real, active variable-substituted import is a blind spot; a comment or a
    documentation string that merely contains the words is inert — exactly as for
    static imports (pinned by the alias/noise test) — so the reject path must not
    fire on them and static imports in the same file still parse.
    """
    _write_suite(
        tmp_path,
        "commented.robot",
        "*** Settings ***\n"
        "Documentation    Do not use Library ${LEGACY} here\n"
        "# Library    ${OLD_LIB}\n"
        "    # Library    ${INDENTED}\n"
        "Library    rfc.graders\n",
    )
    assert _parse_library_imports(tmp_path) == {"rfc.graders"}


def test_guard_fails_when_a_suite_uses_a_variable_substituted_import(
    tmp_path: Path,
) -> None:
    """End-to-end: the whole guard fails on a variable-substituted import (#257).

    ``collect_keyword_surface`` is the surface the CI gate compares; a variable
    ``Library`` import must break it (via the parser) rather than contribute an
    invisible, empty surface that keeps the snapshot green while a rename in the
    variable-loaded library slips through.
    """
    import pytest

    _write_suite(
        tmp_path,
        "uses_var.robot",
        "*** Settings ***\n"
        "Library    ${DYNAMIC_LIB}\n"
        "*** Test Cases ***\n"
        "Smoke\n"
        "    Log    hi\n",
    )
    with pytest.raises(ValueError, match="variable-substituted Library import"):
        collect_keyword_surface(robot_dir=tmp_path)


def test_resolve_library_raises_on_unresolvable_import() -> None:
    """An import path that does not resolve fails loudly rather than being skipped.

    Silently dropping an unresolvable ``Library`` import is the exact blind spot
    the guard exists to close (#152/#208): a typo'd or dependency-broken import
    would then contribute an empty surface and the guard would stay green. A
    missing module and a missing class must each raise.
    """
    import pytest

    with pytest.raises(ModuleNotFoundError):
        _resolve_library("rfc.no_such_module.Thing")
    with pytest.raises(AttributeError):
        _resolve_library("rfc.keywords.NoSuchClass")


def test_guard_enumerates_non_keywords_named_library_class(tmp_path: Path) -> None:
    """The #208 class-name blind spot: a ``Library`` on a non-``*Keywords`` class.

    ``rfc.computer_use_keywords.ComputerUseDispatcher`` is a real library class
    whose name does not end in ``Keywords``. The retired glob+suffix guard only
    enumerated ``*Keywords``-named classes, so its ``Dispatch`` keyword was
    invisible and a rename could silently break any suite importing it. Deriving
    the set from the actual import makes that surface visible.
    """
    assert not "ComputerUseDispatcher".endswith("Keywords")  # why old guard missed it
    _write_suite(
        tmp_path,
        "uses_dispatcher.robot",
        "*** Settings ***\n"
        "Library    rfc.computer_use_keywords.ComputerUseDispatcher\n"
        "*** Test Cases ***\n"
        "Smoke\n"
        "    Log    hi\n",
    )
    assert "Dispatch" in set(collect_keyword_surface(robot_dir=tmp_path))


if __name__ == "__main__":
    surface = collect_keyword_surface()
    _SNAPSHOT.write_text("\n".join(surface) + "\n", encoding="utf-8")
    print(f"wrote {_SNAPSHOT} ({len(surface)} keyword names)")
