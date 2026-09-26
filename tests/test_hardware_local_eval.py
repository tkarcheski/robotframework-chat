"""Resource and context invariants of the native hardware runner."""

from types import SimpleNamespace

import pytest

from scripts.hardware_local_eval import (
    command,
    expected_coordinates,
    terminate,
    verify_coverage,
)


def settings():
    return SimpleNamespace(
        server="/local/llama-server",
        port=8892,
        gpu_layers=999,
        kv="f16",
        kv_placement="gpu",
        cpu_ffn_layers=0,
        cpu_moe_layers=0,
    )


def test_native_command_preserves_requested_context_and_disables_eviction():
    cmd = command(
        settings(),
        {"path": "/weights/model.gguf", "id": "pinned-model", "native_context": 262144},
        4096,
    )
    assert cmd[cmd.index("--ctx-size") + 1] == "4096"
    assert cmd[cmd.index("--fit") + 1] == "off"
    assert "--no-context-shift" in cmd
    assert cmd[cmd.index("--parallel") + 1] == "1"
    assert cmd[cmd.index("--reasoning") + 1] == "off"
    assert "--rope-scaling" not in cmd


def test_context_extension_is_explicit_and_recordable():
    cmd = command(
        settings(),
        {"path": "/weights/model.gguf", "id": "pinned-model", "native_context": 262144},
        524288,
    )
    assert cmd[cmd.index("--rope-scaling") + 1] == "yarn"
    assert cmd[cmd.index("--rope-scale") + 1] == "2.0"
    assert cmd[cmd.index("--yarn-orig-ctx") + 1] == "262144"


def test_cleanup_leaves_already_finished_process_alone():
    class Finished:
        def poll(self):
            return 0

        def terminate(self):
            raise AssertionError("Already finished process should not be signalled")

    terminate(Finished())


def test_host_placement_is_explicit_and_does_not_enable_fit():
    args = settings()
    args.kv_placement = "cpu"
    args.cpu_ffn_layers = 64
    args.cpu_moe_layers = 48
    cmd = command(
        args,
        {"path": "/weights/model.gguf", "id": "model", "native_context": 262144},
        1000000,
    )
    assert "--no-kv-offload" in cmd
    assert cmd[cmd.index("--n-cpu-ffn") + 1] == "64"
    assert cmd[cmd.index("--n-cpu-moe") + 1] == "48"
    assert cmd[cmd.index("--rope-scale") + 1] == "4.0"
    assert cmd[cmd.index("--fit") + 1] == "off"


def test_partial_success_cannot_complete_requested_suite():
    required = {("valid", 16384, "spread", 0), ("missing", 16384, "spread", 0)}
    rows = [
        dict(
            case_id="valid",
            context_tokens=16384,
            position="spread",
            trial=0,
            status="completed",
        )
    ]
    with pytest.raises(RuntimeError, match="coverage"):
        verify_coverage(rows, required)
    with pytest.raises(RuntimeError, match="coverage"):
        verify_coverage(rows * 2, {("valid", 16384, "spread", 0)})
    verify_coverage(rows, {("valid", 16384, "spread", 0)})


def test_mistyped_context_case_is_rejected_before_model_load():
    args = SimpleNamespace(
        trials=1, cases="fire-pinmux-change,typo", positions="spread"
    )
    with pytest.raises(ValueError, match="Unknown"):
        expected_coordinates(args, "context", 16384)


@pytest.mark.parametrize(
    "suite, expected",
    [("short", 54), ("product", 12), ("browser", 12), ("context", 36)],
)
def test_coverage_comes_from_profile_and_requested_matrix(suite, expected):
    args = SimpleNamespace(
        trials=3,
        cases="fire-pinmux-change,mixed-voltage-review,fire-gateware-resources",
        positions="start,middle,end,spread",
    )
    assert len(expected_coordinates(args, suite, 16384)) == expected
