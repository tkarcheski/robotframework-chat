"""Independent release constraints and known-bad product answer controls."""

from pathlib import Path

import pytest

from rfc.hardware_eval import load_benchmark, score_answer, build_pack
from test_hardware_eval import gold_answer

FIXTURES = (
    Path(__file__).resolve().parents[1]
    / "robot/10__tier1/hardware_engineering/fixtures/product"
)


@pytest.fixture
def benchmark():
    return load_benchmark(FIXTURES)


def test_product_oracles_and_prompt_boundary(benchmark):
    for case in benchmark["cases"].values():
        assert score_answer(case, gold_answer(case))["passed"]
        assert '"expected"' not in build_pack(case, benchmark["documents"])["prompt"]
        assert all(
            benchmark["documents"][key]["kind"] == "synthetic"
            for key in case["documents"]
        )


def test_battery_selection_straddles_required_runtime(benchmark):
    rules = benchmark["cases"]["battery-release"]["expected"]
    current = (84 * 20 + 3 * 40 + 120 * 6) / 60
    assert rules["average_ma"]["value"] == current
    assert 3000 * 0.8 * 0.9 * 0.9 / current < 48
    assert 3200 * 0.8 * 0.9 * 0.9 / current >= 48
    assert rules["selected_mah"]["value"] == 3200


def test_sensor_fails_both_independent_release_limits(benchmark):
    rules = benchmark["cases"]["sensor-release"]["expected"]
    assert rules["error_a"]["value"] > 0.100
    assert rules["power_margin_w"]["value"] < 0
    assert 4**2 * 0.020 == rules["shunt_power_w"]["value"]


def test_telemetry_distinguishes_pause_buffer_from_stability(benchmark):
    rules = benchmark["cases"]["telemetry-release"]["expected"]
    demand = 64 * 200 * (12 + 4 + 2)
    capacity = 2_000_000 / 10 * 0.975
    assert demand > capacity
    assert 0.25 * demand < 262144
    assert 169 * 64 * 18 <= capacity < 170 * 64 * 18
    assert rules["selected"]["value"] == "uart3m"
    assert 3_000_000 / 10 * 0.975 > demand


@pytest.mark.parametrize(
    "case_id,field,wrong",
    [
        ("battery-release", "old_cell_passes", True),
        ("sensor-release", "release", True),
        ("telemetry-release", "selected", "uart2m"),
        ("manufacturing-release", "selected", "B"),
    ],
)
def test_wrong_release_decisions_are_critical_failures(
    benchmark, case_id, field, wrong
):
    case = benchmark["cases"][case_id]
    answer = gold_answer(case)
    next(a for a in answer["answers"] if a["id"] == field)["value"] = wrong
    result = score_answer(case, answer)
    assert not result["passed"]
    assert result["critical_failures"] > 0
