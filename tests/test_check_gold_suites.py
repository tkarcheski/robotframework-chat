"""Tests for scripts/check_gold_suites.py — the graded-pool membership guard.

Issue #702 (H6): ``gold`` / ``platinum`` shipped as convention only — 14 suite
files carry the tag and nothing under ``ai/``, ``scripts/`` or ``.github/``
mentions it, so a rename or deletion silently shrinks the gate pool. This guard
makes the ``gold:harness`` / ``platinum:harness`` pool mechanical, the way
``check_test_axes.py`` made the axis rule mechanical.
"""

from __future__ import annotations

from scripts.check_gold_suites import (
    GOLD_TAG,
    PLATINUM_TAG,
    GoldManifest,
    GradedTest,
    evaluate_gold_pool,
)

_SUITE = "robot/40__tier4/harness_matrix/harness_matrix.robot"
_OTHER = "robot/10__tier1/harness/test_harness_cli.robot"


def _test(
    name: str,
    *,
    suite: str = _SUITE,
    tags: tuple[str, ...] = (GOLD_TAG, "axis:harness", "verify:python"),
) -> GradedTest:
    return GradedTest(suite=suite, name=name, tags=frozenset(tags))


def _manifest(
    gold: tuple[tuple[str, str], ...],
    platinum: tuple[str, str],
    *,
    min_instrument_controls: int = 0,
) -> GoldManifest:
    return GoldManifest(
        gold=frozenset(gold),
        platinum=platinum,
        min_instrument_controls=min_instrument_controls,
    )


def _healthy() -> tuple[list[GradedTest], GoldManifest]:
    """A two-member pool that satisfies every rule (controls disabled)."""
    tests = [
        _test("Alpha", tags=(GOLD_TAG, PLATINUM_TAG, "axis:harness", "verify:python")),
        _test("Beta", suite=_OTHER),
    ]
    manifest = _manifest(
        gold=((_SUITE, "Alpha"), (_OTHER, "Beta")),
        platinum=(_SUITE, "Alpha"),
    )
    return tests, manifest


class TestMembershipDrift:
    def test_matching_pool_passes(self) -> None:
        tests, manifest = _healthy()
        assert evaluate_gold_pool(tests, manifest) == []

    def test_missing_gold_member_is_flagged(self) -> None:
        tests, manifest = _healthy()
        violations = evaluate_gold_pool(tests[:1], manifest)
        assert any("Beta" in v and "missing" in v.lower() for v in violations)

    def test_untracked_gold_member_is_flagged(self) -> None:
        """A newly gold-tagged test that nobody added to the manifest."""
        tests, manifest = _healthy()
        tests.append(_test("Gamma"))
        violations = evaluate_gold_pool(tests, manifest)
        assert any("Gamma" in v for v in violations)

    def test_renamed_test_reports_both_sides(self) -> None:
        """A rename is a deletion plus an addition — both must surface."""
        tests, manifest = _healthy()
        tests[1] = _test("Beta Renamed", suite=_OTHER)
        violations = evaluate_gold_pool(tests, manifest)
        joined = " ".join(violations)
        assert "Beta Renamed" in joined and "Beta" in joined

    def test_same_name_in_two_suites_is_not_confused(self) -> None:
        """Membership is keyed on (suite, name), never on name alone."""
        tests, manifest = _healthy()
        tests[1] = _test("Alpha", suite=_OTHER)
        violations = evaluate_gold_pool(tests, manifest)
        assert violations, "a gold Alpha in the wrong suite must not satisfy Beta"


class TestPlatinum:
    def test_platinum_must_be_unique(self) -> None:
        tests, manifest = _healthy()
        tests[1] = _test(
            "Beta",
            suite=_OTHER,
            tags=(GOLD_TAG, PLATINUM_TAG, "axis:harness", "verify:python"),
        )
        violations = evaluate_gold_pool(tests, manifest)
        assert any("exactly one" in v.lower() for v in violations)

    def test_missing_platinum_is_flagged(self) -> None:
        tests, manifest = _healthy()
        tests[0] = _test("Alpha")  # gold, but no platinum tag
        violations = evaluate_gold_pool(tests, manifest)
        assert any(PLATINUM_TAG in v for v in violations)

    def test_platinum_on_the_wrong_test_is_flagged(self) -> None:
        tests, manifest = _healthy()
        tests[0] = _test("Alpha")
        tests[1] = _test(
            "Beta",
            suite=_OTHER,
            tags=(GOLD_TAG, PLATINUM_TAG, "axis:harness", "verify:python"),
        )
        violations = evaluate_gold_pool(tests, manifest)
        assert any("Beta" in v for v in violations)

    def test_platinum_without_gold_is_flagged(self) -> None:
        """Platinum is the top of the gold pool, never a parallel pool."""
        tests, manifest = _healthy()
        tests[0] = _test("Alpha", tags=(PLATINUM_TAG, "axis:harness", "verify:python"))
        violations = evaluate_gold_pool(tests, manifest)
        assert any(GOLD_TAG in v for v in violations)


class TestGoldCriteria:
    def test_llm_graded_gold_test_is_flagged(self) -> None:
        """Criterion 2: judge variance is not harness variance."""
        tests, manifest = _healthy()
        tests[1] = _test(
            "Beta", suite=_OTHER, tags=(GOLD_TAG, "axis:harness", "verify:llm")
        )
        violations = evaluate_gold_pool(tests, manifest)
        assert any("verify:" in v and "Beta" in v for v in violations)

    def test_gold_test_off_the_harness_axis_is_flagged(self) -> None:
        tests, manifest = _healthy()
        tests[1] = _test(
            "Beta", suite=_OTHER, tags=(GOLD_TAG, "axis:model", "verify:python")
        )
        violations = evaluate_gold_pool(tests, manifest)
        assert any("axis:harness" in v for v in violations)

    def test_too_few_instrument_controls_is_flagged(self) -> None:
        """H7 set-level rule: a pool with no negative controls is unverified."""
        tests, manifest = _healthy()
        manifest = _manifest(
            gold=tuple(manifest.gold),
            platinum=manifest.platinum,
            min_instrument_controls=2,
        )
        violations = evaluate_gold_pool(tests, manifest)
        assert any("control:instrument" in v for v in violations)

    def test_enough_instrument_controls_passes(self) -> None:
        tests, manifest = _healthy()
        tests[0] = _test(
            "Alpha",
            tags=(
                GOLD_TAG,
                PLATINUM_TAG,
                "axis:harness",
                "verify:python",
                "control:instrument",
            ),
        )
        tests[1] = _test(
            "Beta",
            suite=_OTHER,
            tags=(GOLD_TAG, "axis:harness", "verify:python", "control:instrument"),
        )
        manifest = _manifest(
            gold=tuple(manifest.gold),
            platinum=manifest.platinum,
            min_instrument_controls=2,
        )
        assert evaluate_gold_pool(tests, manifest) == []


class TestRepoPool:
    """The real ``robot/`` tree must satisfy its own manifest."""

    def test_repo_gold_pool_is_clean(self) -> None:
        from scripts.check_gold_suites import collect_graded_tests, load_manifest

        manifest = load_manifest()
        tests = collect_graded_tests()
        assert evaluate_gold_pool(tests, manifest) == []

    def test_manifest_pins_ten_gold_tests(self) -> None:
        from scripts.check_gold_suites import load_manifest

        assert len(load_manifest().gold) == 10
