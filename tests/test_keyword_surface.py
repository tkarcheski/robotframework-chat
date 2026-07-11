"""Keyword-surface snapshot guard.

Robot keyword names are this project's PUBLIC API: Robot suites here and in the
public mirror invoke keywords by these exact names, so a rename, removal, or
addition is a breaking or surface-widening change.

Robot Framework auto-exposes **every public method** of a keyword-library class
as a keyword unless the class sets ``ROBOT_AUTO_KEYWORDS = False``. The
``@keyword`` decorator is therefore optional: it only *renames* a keyword, or —
with auto-keywords switched off — opts a single method in. Snapshotting only the
``@keyword``-decorated methods (the previous AST approach) was structurally blind
to that auto-exposed surface: an undecorated public method — or an entire
undecorated library such as ``AgenticCodingKeywords`` — was a live keyword that
tier-4 suites invoke, yet invisible to the guard, so a rename could silently
break those suites (#152).

This guard imports each ``src/rfc/*_keywords.py`` library class and enumerates the
exact keyword names Robot exposes at runtime, applying Robot's own discovery
rules — ``ROBOT_AUTO_KEYWORDS``, ``@keyword`` renames (``robot_name``),
``@not_keyword`` exclusions, private ``_``-prefixed methods, property/non-routine
exclusion, and inherited methods — together with Robot's own ``printable_name``
formatter. Enumeration runs at the *class* level (never instantiating the
library) so libraries whose ``__init__`` requires arguments (a model, a database
URL) are still covered. ``test_enumeration_matches_robot_discovery`` pins this
replication to Robot's real ``TestLibrary`` discovery so it cannot silently drift.

Regenerate the snapshot after an *intentional* surface change with::

    uv run python core/tests/test_keyword_surface.py
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Iterator
from functools import cached_property, partial
from pathlib import Path

from robot.api.deco import keyword, not_keyword
from robot.utils import printable_name

_RFC_DIR = Path(__file__).resolve().parent.parent / "src" / "rfc"
_SNAPSHOT = Path(__file__).resolve().parent / "keyword_surface_snapshot.txt"


def _exposed_keyword_names(library: type) -> set[str]:
    """Return the Robot keyword names ``library`` exposes at runtime.

    Mirrors ``robot.running.testlibraries.StaticKeywordCreator`` (Robot 7): a
    class attribute becomes a keyword when it is a public routine — or is
    explicitly opted in with ``@keyword`` while ``ROBOT_AUTO_KEYWORDS`` is off —
    and is neither marked ``@not_keyword`` nor a property. The keyword name is
    the ``@keyword("...")`` override when given, else ``printable_name`` of the
    method name. Operates on the class, not an instance, so libraries with
    required constructor arguments are covered without being instantiated.
    """
    auto_keywords = getattr(library, "ROBOT_AUTO_KEYWORDS", True)
    names: set[str] = set()
    for attr_name in dir(library):
        try:
            attr = inspect.getattr_static(library, attr_name)
        except AttributeError:  # dynamically provided attribute — not a method
            continue
        func = attr.__func__ if isinstance(attr, (classmethod, staticmethod)) else attr
        # Inclusion: any public attribute under auto-keywords, or a method that
        # opted in with @keyword (which sets ``robot_name``) when auto is off.
        explicitly_included = hasattr(func, "robot_name")
        included = (
            auto_keywords and not attr_name.startswith("_")
        ) or explicitly_included
        if not included:
            continue
        # Exclusion: properties / non-routines are not keywords, and @not_keyword
        # opts a public method back out.
        if isinstance(attr, cached_property):
            continue
        if not (inspect.isroutine(func) or isinstance(func, partial)):
            continue
        if getattr(func, "robot_not_keyword", False):
            continue
        robot_name = getattr(func, "robot_name", None)
        names.add(robot_name or printable_name(attr_name, code_style=True))
    return names


def _iter_library_classes(rfc_dir: Path = _RFC_DIR) -> Iterator[type]:
    """Yield every Robot keyword-library class in ``src/rfc/*_keywords.py``.

    A library class is one defined in the module whose name ends in ``Keywords``
    (helper dataclasses like ``ToolCall`` are skipped). Import failures are
    deliberately not swallowed: a library that will not import has no discoverable
    surface, and silently dropping it would reintroduce the exact blind spot this
    guard exists to close.
    """
    for path in sorted(rfc_dir.glob("*_keywords.py")):
        module_name = f"rfc.{path.stem}"
        module = importlib.import_module(module_name)
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ == module_name and obj.__name__.endswith("Keywords"):
                yield obj


def collect_keyword_surface(rfc_dir: Path = _RFC_DIR) -> list[str]:
    """Return the sorted, de-duplicated Robot keyword surface of the tree."""
    names: set[str] = set()
    for library in _iter_library_classes(rfc_dir):
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


if __name__ == "__main__":
    surface = collect_keyword_surface()
    _SNAPSHOT.write_text("\n".join(surface) + "\n", encoding="utf-8")
    print(f"wrote {_SNAPSHOT} ({len(surface)} keyword names)")
