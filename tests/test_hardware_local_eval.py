"""Resource and context invariants of the native hardware runner."""

from types import SimpleNamespace
import io
import json

import pytest

from scripts.hardware_local_eval import (
    allocated_context,
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
        constrain_json=False,
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


def test_decimal_million_budget_has_explicit_native_allocation_padding():
    cmd = command(
        settings(),
        {"path": "/weights/model.gguf", "id": "model", "native_context": 262144},
        1000000,
    )
    assert allocated_context(1000000) == 1000192
    assert allocated_context(262144) == 262144
    assert cmd[cmd.index("--ctx-size") + 1] == "1000192"


def test_json_constraint_does_not_apply_prefix_incompatible_server_grammar():
    args = settings()
    model = {"path": "/weights/model.gguf", "id": "model", "native_context": 262144}
    assert "--json-schema" not in command(args, model, 4096)
    args.constrain_json = True
    cmd = command(args, model, 4096)
    assert "--json-schema" not in cmd


@pytest.mark.parametrize(
    "content,finish,valid",
    [
        ("{}", "stop", True),
        ("READY", "stop", False),
        ("[]", "stop", False),
        ("{}", "length", False),
    ],
)
def test_constraint_probe_retains_failure_evidence(
    tmp_path, monkeypatch, content, finish, valid
):
    from scripts.hardware_local_eval import probe_json_constraint

    response = {"choices": [{"message": {"content": content}, "finish_reason": finish}]}

    def respond(request, timeout):
        payload = json.loads(request.data)
        assert payload["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": {"type": "object"}},
        }
        return io.StringIO(json.dumps(response))

    monkeypatch.setattr("urllib.request.urlopen", respond)
    artifact = tmp_path / "probe.json"
    if valid:
        assert probe_json_constraint("http://127.0.0.1", "model", artifact) == response
    else:
        with pytest.raises((RuntimeError, ValueError)):
            probe_json_constraint("http://127.0.0.1", "model", artifact)
    assert json.loads(artifact.read_text()) == response


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


def test_unsupported_context_coordinate_is_rejected_before_model_load():
    args = SimpleNamespace(trials=1, cases="fire-pinmux-change", positions="spread")
    with pytest.raises(ValueError, match="Unsupported context-suite level: 12288"):
        expected_coordinates(args, "context", 12288)
    assert len(expected_coordinates(args, "short", 12288)) == 18


def test_invalid_cli_context_never_touches_server_or_output(tmp_path, monkeypatch):
    from scripts import hardware_local_eval as runner

    models = tmp_path / "models.json"
    models.write_text("[]")
    output = tmp_path / "results"
    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--models",
            str(models),
            "--server",
            "/missing/server",
            "--reference-tokenizer",
            "/missing/tokenizer",
            "--contexts",
            "12288",
            "--suites",
            "context",
            "--output",
            str(output),
            "--execute",
        ],
    )
    monkeypatch.setattr(
        runner, "capture", lambda command: pytest.fail("Server must not be probed")
    )
    with pytest.raises(ValueError, match="Unsupported context-suite level"):
        runner.main()
    assert not output.exists()


@pytest.mark.parametrize(
    "duplicate", [["--contexts", "4096", "4096"], ["--suites", "short", "short"]]
)
def test_duplicate_cli_matrix_never_touches_server_or_output(
    tmp_path, monkeypatch, duplicate
):
    from scripts import hardware_local_eval as runner

    output = tmp_path / "results"
    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--models",
            "/missing/models",
            "--server",
            "/missing/server",
            "--reference-tokenizer",
            "/missing/tokenizer",
            "--output",
            str(output),
            "--execute",
            *duplicate,
        ],
    )
    monkeypatch.setattr(
        runner, "capture", lambda command: pytest.fail("Server must not be probed")
    )
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2
    assert not output.exists()


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
