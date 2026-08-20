#!/usr/bin/env python3
"""CI guard: the graded ``gold:harness`` / ``platinum:harness`` pool is intact.

Issue #702 (H6). The ``axis:model`` side of the scoreboard has carried a graded
quality standard since ``0f95f75``: 14 suites tagged ``gold``, one ``platinum``,
and a gate that runs ``--include gold --exclude stress``. That standard was
convention only: the tag appeared in no document and no checker, so renaming or
deleting a member silently shrank the gate pool with no signal anywhere. A gate
whose membership can change by accident is not a gate.

This guard makes the harness-side pool mechanical, a sibling to
``check_test_axes.py`` (axis tags), ``check_battery_scenarios.py`` and
``check_agent_signoffs.py``: "prompts request, checks enforce" (ai/GIT.md).

Two pools, deliberately namespaced (#702 Part 2). The bare ``gold`` /
``platinum`` tags stay owned by the ``axis:model`` RSI gate; reusing them for
harness suites would make the existing ``--include gold`` filter silently pull
harness suites into the model gate. So the harness pool is:

  * ``gold:harness``     -- the trusted harness set (exactly the manifest).
  * ``platinum:harness`` -- the single highest-signal harness test, always run.

Five checks, all decidable from the Robot source (no live model, no DB):

  1. **Membership matches the manifest.** ``config/gold_harness.yaml`` pins the
     pool by ``(suite, test)``. A member that vanished (rename, deletion) and a
     test that acquired the tag without being added both fail. Keying on the
     pair, never the bare name, keeps two same-named tests in different suites
     from satisfying each other.
  2. **Platinum is unique, pinned, and inside gold.** Exactly one test carries
     ``platinum:harness``; it is the manifest's; and it also carries
     ``gold:harness``. Platinum is the top of the gold pool, not a parallel one.
  3. **Deterministic grading.** Every gold member is ``verify:robot`` or
     ``verify:python``. An LLM judge in the gate path puts judge variance into a
     harness number (#702 gold criterion 2).
  4. **On the harness axis.** Every gold member carries ``axis:harness``.
  5. **Negative controls present.** At least ``min_instrument_controls`` members
     carry ``control:instrument``: tests that assert the instrument goes RED on
     a planted defect (#702 H7). A green scoreboard cell means nothing if the
     instrument cannot fail.

Enforce is the default: unlike ``check_test_axes.py``'s A1 report posture, this
pool ships already populated, so there is no backfill window to be lenient for.

Usage:
  python scripts/check_gold_suites.py            # enforce (exit 1 on violation)
  python scripts/check_gold_suites.py --report   # list the pool, always exit 0
  python scripts/check_gold_suites.py --root robot --manifest config/gold_harness.yaml
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml
from robot.api import TestSuite

#: Repo root. This file lives at ``scripts/``.
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROBOT_ROOT = REPO_ROOT / "robot"
DEFAULT_MANIFEST = REPO_ROOT / "config" / "gold_harness.yaml"

GOLD_TAG = "gold:harness"
PLATINUM_TAG = "platinum:harness"
AXIS_TAG = "axis:harness"
CONTROL_TAG = "control:instrument"

#: Grading styles a gold member may use (#702 gold criterion 2). ``verify:llm``
#: and ``verify:llms`` are excluded on purpose: a judge panel's variance would
#: read as harness variance on the scoreboard.
DETERMINISTIC_VERIFY_TAGS: frozenset[str] = frozenset({"verify:robot", "verify:python"})

#: A (suite, test) pair. ``suite`` is repo-relative and POSIX-separated so the
#: manifest reads the same on every platform.
TestKey = tuple[str, str]


@dataclass(frozen=True)
class GradedTest:
    """One Robot test case's graded-pool facts, tags fully resolved.

    ``tags`` includes everything Robot itself resolves: per-test ``[Tags]``
    plus ``Test Tags`` / ``Force Tags`` / ``Default Tags`` cascaded from the
    suite and from any ancestor ``__init__.robot``.
    """

    suite: str
    name: str
    tags: frozenset[str]

    @property
    def key(self) -> TestKey:
        return (self.suite, self.name)

    def __str__(self) -> str:
        return f"{self.suite}::{self.name}"


@dataclass(frozen=True)
class GoldManifest:
    """The pinned pool: what membership is *supposed* to be."""

    gold: frozenset[TestKey]
    platinum: TestKey
    min_instrument_controls: int = 0


def _fmt(key: TestKey) -> str:
    return f"{key[0]}::{key[1]}"


# --- collection ---------------------------------------------------------------


def collect_graded_tests(root: Path | str = DEFAULT_ROBOT_ROOT) -> list[GradedTest]:
    """Return every test under ``root`` that carries a graded harness tag.

    Robot's own model resolves tag inheritance, so a ``Test Tags`` line on an
    ancestor ``__init__.robot`` is seen here exactly as it will be at run time,
    the guard can never disagree with ``--include`` about who is in the pool.
    """
    root = Path(root)
    suite = TestSuite.from_file_system(root)
    graded: list[GradedTest] = []
    for test in suite.all_tests:
        tags = frozenset(str(tag) for tag in test.tags)
        if not (tags & {GOLD_TAG, PLATINUM_TAG}):
            continue
        source = Path(test.source) if test.source else root
        rel = source.resolve().relative_to(REPO_ROOT).as_posix()
        graded.append(GradedTest(suite=rel, name=str(test.name), tags=tags))
    return graded


def load_manifest(path: Path | str = DEFAULT_MANIFEST) -> GoldManifest:
    """Load the pinned pool from ``config/gold_harness.yaml``."""
    raw = yaml.safe_load(Path(path).read_text()) or {}
    gold = frozenset(
        (str(entry["suite"]), str(entry["test"])) for entry in raw.get("gold", [])
    )
    platinum_raw = raw.get("platinum") or {}
    platinum: TestKey = (
        str(platinum_raw.get("suite", "")),
        str(platinum_raw.get("test", "")),
    )
    return GoldManifest(
        gold=gold,
        platinum=platinum,
        min_instrument_controls=int(raw.get("min_instrument_controls", 0)),
    )


# --- evaluation (pure) --------------------------------------------------------


def evaluate_gold_pool(tests: list[GradedTest], manifest: GoldManifest) -> list[str]:
    """Return one human-readable violation per broken rule; ``[]`` when clean.

    Pure: takes the collected facts and the pinned manifest, touches no
    filesystem. Every check runs, so one sweep reports every problem rather
    than stopping at the first.
    """
    violations: list[str] = []
    by_key = {t.key: t for t in tests}
    gold_tests = [t for t in tests if GOLD_TAG in t.tags]
    gold_keys = {t.key for t in gold_tests}

    # 1. Membership drift, both directions.
    for missing in sorted(manifest.gold - gold_keys):
        violations.append(
            f"{_fmt(missing)}: pinned in the manifest but missing the "
            f"{GOLD_TAG!r} tag (renamed, deleted, or untagged?)"
        )
    for extra in sorted(gold_keys - manifest.gold):
        violations.append(
            f"{_fmt(extra)}: carries {GOLD_TAG!r} but is not pinned in the "
            "manifest. Add it (with a rationale) or drop the tag"
        )

    # 2. Platinum: unique, pinned, and a gold member.
    platinum_tests = [t for t in tests if PLATINUM_TAG in t.tags]
    if len(platinum_tests) != 1:
        found = ", ".join(sorted(str(t) for t in platinum_tests)) or "none"
        violations.append(
            f"expected exactly one {PLATINUM_TAG!r} test, found "
            f"{len(platinum_tests)}: {found}"
        )
    for test in platinum_tests:
        if test.key != manifest.platinum:
            violations.append(
                f"{test}: carries {PLATINUM_TAG!r} but the manifest pins "
                f"{_fmt(manifest.platinum)}"
            )
        if GOLD_TAG not in test.tags:
            violations.append(
                f"{test}: carries {PLATINUM_TAG!r} without {GOLD_TAG!r}. "
                "Platinum is the top of the gold pool, not a parallel pool"
            )
    if not platinum_tests and manifest.platinum in by_key:
        violations.append(
            f"{_fmt(manifest.platinum)}: pinned as platinum but missing the "
            f"{PLATINUM_TAG!r} tag"
        )

    # 3-4. Per-member criteria.
    for test in sorted(gold_tests, key=lambda t: t.key):
        if not (test.tags & DETERMINISTIC_VERIFY_TAGS):
            styles = sorted(t for t in test.tags if t.startswith("verify:")) or ["none"]
            violations.append(
                f"{test}: gold requires deterministic grading "
                f"({' or '.join(sorted(DETERMINISTIC_VERIFY_TAGS))}), found "
                f"{', '.join(styles)}. Judge variance is not harness variance"
            )
        if AXIS_TAG not in test.tags:
            violations.append(f"{test}: gold harness members must carry {AXIS_TAG!r}")

    # 5. Negative controls (#702 H7).
    controls = [t for t in gold_tests if CONTROL_TAG in t.tags]
    if len(controls) < manifest.min_instrument_controls:
        violations.append(
            f"gold pool carries {len(controls)} {CONTROL_TAG!r} test(s), "
            f"expected at least {manifest.min_instrument_controls}. Without "
            "negative controls, a green pool never proves the instrument can go red"
        )

    return violations


# --- CLI ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(DEFAULT_ROBOT_ROOT))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument(
        "--report",
        action="store_true",
        help="list the pool and any violations, but always exit 0",
    )
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    tests = collect_graded_tests(args.root)
    violations = evaluate_gold_pool(tests, manifest)

    gold_tests = sorted((t for t in tests if GOLD_TAG in t.tags), key=lambda t: t.key)
    print(f"Graded harness pool: {len(gold_tests)} {GOLD_TAG} test(s)")
    for test in gold_tests:
        marks = []
        if PLATINUM_TAG in test.tags:
            marks.append("PLATINUM")
        if CONTROL_TAG in test.tags:
            marks.append("control")
        suffix = f"  [{', '.join(marks)}]" if marks else ""
        print(f"  - {test}{suffix}")

    if not violations:
        print("\nOK: the graded pool matches its manifest.")
        return 0

    print(f"\n{len(violations)} violation(s):", file=sys.stderr)
    for violation in violations:
        print(f"  - {violation}", file=sys.stderr)
    return 0 if args.report else 1


if __name__ == "__main__":
    raise SystemExit(main())
