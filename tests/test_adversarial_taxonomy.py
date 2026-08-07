"""Tests for rfc.adversarial_taxonomy (the attack-space vocabulary)."""

from __future__ import annotations

import pytest

from rfc.adversarial_taxonomy import (
    AttackVector,
    Objective,
    Severity,
    Surface,
    Technique,
    axis_for_surface,
    severity_rank,
)


def test_every_surface_maps_to_an_axis() -> None:
    for surface in Surface:
        axis = axis_for_surface(surface)
        assert axis in {"axis:model", "axis:harness"}


def test_coding_harness_is_the_only_harness_axis() -> None:
    harness = [s for s in Surface if axis_for_surface(s) == "axis:harness"]
    assert harness == [Surface.CODING_HARNESS]


def test_severity_rank_is_total_and_ordered() -> None:
    ranks = [severity_rank(s) for s in Severity]
    assert ranks == sorted(ranks)
    assert severity_rank(Severity.CRITICAL) > severity_rank(Severity.LOW)
    assert len(set(ranks)) == len(list(Severity))


def test_attack_vector_slug_is_stable_and_parseable() -> None:
    vector = AttackVector(
        surface=Surface.CODING_HARNESS,
        technique=Technique.MULTI_STEP_CHAIN,
        objective=Objective.SECRET_EXFILTRATION,
    )
    assert vector.slug == "coding_harness/multi_step_chain/secret_exfiltration"
    surface, technique, objective = vector.slug.split("/")
    assert Surface(surface) is Surface.CODING_HARNESS
    assert Technique(technique) is Technique.MULTI_STEP_CHAIN
    assert Objective(objective) is Objective.SECRET_EXFILTRATION


def test_attack_vector_axis_follows_surface() -> None:
    harness_vector = AttackVector(
        Surface.CODING_HARNESS, Technique.OBFUSCATION, Objective.GUARDRAIL_BYPASS
    )
    model_vector = AttackVector(
        Surface.MODEL_UNDER_TEST,
        Technique.ROLEPLAY_JAILBREAK,
        Objective.GUARDRAIL_BYPASS,
    )
    assert harness_vector.axis == "axis:harness"
    assert model_vector.axis == "axis:model"


def test_attack_vector_is_hashable_and_value_equal() -> None:
    a = AttackVector(
        Surface.MULTI_AGENT, Technique.DELEGATION_ABUSE, Objective.TASK_HIJACK
    )
    b = AttackVector(
        Surface.MULTI_AGENT, Technique.DELEGATION_ABUSE, Objective.TASK_HIJACK
    )
    assert a == b
    assert len({a, b}) == 1


@pytest.mark.parametrize("enum_cls", [Surface, Technique, Objective, Severity])
def test_enum_values_are_lowercase_snake(enum_cls: type) -> None:
    for member in enum_cls:
        assert member.value == member.value.lower()
        assert " " not in member.value
