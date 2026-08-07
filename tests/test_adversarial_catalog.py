"""Tests for rfc.adversarial_catalog (the scenario source of truth)."""

from __future__ import annotations

from rfc.adversarial_catalog import (
    CATALOG,
    ScenarioSpec,
    ScenarioStatus,
    all_specs,
    covered_vectors,
    find,
    implemented_specs,
    intended_vectors,
    next_candidates,
    proposed_specs,
    uncovered_vectors,
    validate_catalog,
)
from rfc.adversarial_taxonomy import (
    AttackVector,
    Objective,
    Severity,
    Surface,
    Technique,
    severity_rank,
)


def test_catalog_is_structurally_valid() -> None:
    assert validate_catalog() == []


def test_scenario_ids_are_unique() -> None:
    ids = [s.scenario_id for s in CATALOG]
    assert len(ids) == len(set(ids))


def test_implemented_and_proposed_partition_the_catalog() -> None:
    impl = implemented_specs()
    prop = proposed_specs()
    assert len(impl) + len(prop) == len(all_specs())
    assert not ({s.scenario_id for s in impl} & {s.scenario_id for s in prop})


def test_every_implemented_spec_names_an_artifact() -> None:
    for spec in implemented_specs():
        assert spec.artifact, f"{spec.scenario_id} implemented but no artifact"


def test_multi_step_chains_declare_their_steps() -> None:
    for spec in CATALOG:
        if spec.vector.technique is Technique.MULTI_STEP_CHAIN:
            assert len(spec.kill_chain) >= 2, spec.scenario_id


def test_covered_is_subset_of_intended() -> None:
    assert covered_vectors() <= intended_vectors()


def test_uncovered_vectors_have_no_implementation() -> None:
    covered = covered_vectors()
    for vector in uncovered_vectors():
        assert vector not in covered


def test_uncovered_vectors_sorted_most_severe_first() -> None:
    uncovered = uncovered_vectors()
    # Map each uncovered vector back to the worst severity among its proposals.
    worst: dict[AttackVector, int] = {}
    for spec in proposed_specs():
        if spec.vector in set(uncovered):
            worst[spec.vector] = max(
                worst.get(spec.vector, -1), severity_rank(spec.severity)
            )
    ranks = [worst[v] for v in uncovered]
    assert ranks == sorted(ranks, reverse=True)


def test_next_candidates_are_all_proposed_and_severity_ranked() -> None:
    candidates = next_candidates()
    assert candidates == proposed_specs() or set(candidates) == set(proposed_specs())
    for spec in candidates:
        assert spec.status is ScenarioStatus.PROPOSED
    ranks = [severity_rank(s.severity) for s in candidates]
    assert ranks == sorted(ranks, reverse=True)


def test_next_candidates_respects_limit() -> None:
    assert len(next_candidates(limit=2)) == 2
    assert len(next_candidates(limit=0)) == 0


def test_find_returns_spec_or_none() -> None:
    assert find("nope_does_not_exist") is None
    spec = find("exfil_secret_via_test_output")
    assert isinstance(spec, ScenarioSpec)
    assert spec.vector.surface is Surface.CODING_HARNESS


def test_new_batch_opens_previously_uncovered_ground() -> None:
    # The program cycle must reach the multi_agent surface and the
    # supply_chain objective -- neither existed before.
    surfaces = {s.vector.surface for s in CATALOG}
    objectives = {s.vector.objective for s in CATALOG}
    assert Surface.MULTI_AGENT in surfaces
    assert Objective.SUPPLY_CHAIN in objectives


def test_problems_flags_a_bad_spec() -> None:
    bad = ScenarioSpec(
        scenario_id="Bad Id",
        title="x",
        vector=AttackVector(
            Surface.MODEL_UNDER_TEST,
            Technique.MULTI_STEP_CHAIN,
            Objective.TASK_HIJACK,
        ),
        severity=Severity.LOW,
        status=ScenarioStatus.IMPLEMENTED,
        summary="x",
        grading="",
    )
    problems = bad.problems()
    # bad id, missing grading, implemented-without-artifact, short kill_chain.
    assert len(problems) == 4
