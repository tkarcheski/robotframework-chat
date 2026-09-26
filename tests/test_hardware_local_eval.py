"""Resource and context invariants of the native hardware runner."""

from types import SimpleNamespace
import io
import json

import pytest

from scripts.hardware_local_eval import (
    allocated_context,
    command,
    expected_coordinates,
    managed_environment,
    terminate,
    verify_coverage,
    verify_gpu_headroom,
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


@pytest.mark.parametrize(
    "snapshot",
    ["", "100, 23000, 0\n23000, 100, 90", "0, N/A, 0", "0, nan, 0", "0"],
)
def test_gpu_guard_rejects_busy_later_device_or_unknown_headroom(snapshot):
    with pytest.raises(RuntimeError):
        verify_gpu_headroom(snapshot, 20000)


def test_gpu_guard_accepts_headroom_on_every_reported_device():
    verify_gpu_headroom("100, 23000, 0\n200, 22000, 0\n", 20000)


def test_cpu_sampling_never_invokes_nvidia_tooling(monkeypatch):
    import os
    from scripts import hardware_local_eval as runner

    monkeypatch.setattr(runner, "capture", lambda command: pytest.fail("GPU probe"))
    state = runner.sample(os.getpid(), include_gpu=False)
    assert state["gpu"] is None
    assert state["available_ram"] > 0
    assert "process_status" in state


def test_cpu_only_cell_starts_without_gpu_probes(tmp_path, monkeypatch):
    from scripts import hardware_local_eval as runner

    args = settings()
    args.gpu_layers = 0
    args.output = tmp_path
    args.min_ram_gib = 0
    args.min_free_gpu_mib = 20000
    args.unified_memory = False
    args.trials = 1
    args.output_tokens = 2048
    args.reference_tokenizer = tmp_path / "tokenizer.json"
    args.cases = "all"
    args.positions = "spread"
    args.timeout = 60
    args.suites = []  # Exercise startup/attestation without submitting inference.
    model = dict(
        name="base",
        id="base",
        path="base.gguf",
        native_context=262144,
        sha256="a" * 64,
        quant="Q4_K_M",
        tokenizer="tokenizer.json",
    )

    class FreePort:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def connect_ex(self, address):
            return 1

    class Server:
        pid = 12345

        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout):
            return 0

    def capture(command):
        assert command[0] == "git", "CPU launch must not probe NVIDIA tooling"
        return "test-revision"

    def launch(command, **kwargs):
        assert command[command.index("--device") + 1] == "none"
        assert "--no-kv-offload" in command
        return Server()

    monkeypatch.setattr(runner.socket, "socket", lambda: FreePort())
    monkeypatch.setattr(runner, "capture", capture)
    monkeypatch.setattr(runner.subprocess, "Popen", launch)
    monkeypatch.setattr(
        runner,
        "api",
        lambda base, route: {
            "/health": {"status": "ok"},
            "/v1/models": {"data": [{"id": "base"}]},
            "/props": {"default_generation_settings": {"n_ctx": 4096}},
        }[route],
    )
    runner.run_cell(args, model, 4096, "test-version")
    manifest = json.loads((tmp_path / "base-4096/manifest.json").read_text())
    assert manifest["status"] == "completed"
    assert manifest["baseline"]["gpu"] is None
    assert manifest["gpu_processes"] is None
    assert manifest["runtime"]["kv_placement"] == "cpu"
    assert manifest["gpu_allocation_verification"] == "not performed: gpu_layers=0"


@pytest.mark.parametrize("busy_second_gpu", [False, True])
def test_owned_launch_overrides_adapter_and_checks_all_gpus(
    tmp_path, monkeypatch, busy_second_gpu
):
    from scripts import hardware_local_eval as runner

    args = settings()
    args.output = tmp_path
    args.min_ram_gib = 1
    args.min_free_gpu_mib = 20000
    args.unified_memory = False
    args.trials = 1
    args.output_tokens = 2048
    args.reference_tokenizer = tmp_path / "tokenizer.json"
    args.cases = "all"
    args.positions = "spread"
    args.timeout = 60
    model = dict(
        name="base",
        id="base",
        path="base.gguf",
        native_context=262144,
        sha256="a" * 64,
        quant="Q4_K_M",
        tokenizer="tokenizer.json",
    )

    class FreePort:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def connect_ex(self, address):
            return 1

    monkeypatch.setattr(runner.socket, "socket", lambda: FreePort())
    monkeypatch.setattr(
        runner,
        "sample",
        lambda **kwargs: {
            "available_ram": 10 * 1024**3,
            "gpu": "100, 23000, 0\n200, "
            + ("100" if busy_second_gpu else "22000")
            + ", 0",
        },
    )
    monkeypatch.setattr(runner, "capture", lambda command: "test-revision")
    monkeypatch.setenv("HW_ADAPTER_ID", "unrelated-inherited-adapter")
    launched = []

    def launch(command, **kwargs):
        launched.append(kwargs["env"])
        assert kwargs["env"]["HW_ADAPTER_ID"] == "none"
        raise RuntimeError("test launch boundary")

    monkeypatch.setattr(runner.subprocess, "Popen", launch)
    with pytest.raises(
        RuntimeError, match="GPU 1" if busy_second_gpu else "test launch boundary"
    ):
        runner.run_cell(args, model, 4096, "test-version")
    assert len(launched) == (0 if busy_second_gpu else 1)


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


def test_managed_memory_is_explicit_and_never_mutates_parent_environment():
    inherited = {"GGML_CUDA_ENABLE_UNIFIED_MEMORY": "1", "EXAMPLE": "retained"}
    plain = managed_environment(False, inherited)
    managed = managed_environment(True, {"EXAMPLE": "retained"})
    assert "GGML_CUDA_ENABLE_UNIFIED_MEMORY" not in plain
    assert managed["GGML_CUDA_ENABLE_UNIFIED_MEMORY"] == "1"
    assert plain["EXAMPLE"] == managed["EXAMPLE"] == "retained"
    assert inherited["GGML_CUDA_ENABLE_UNIFIED_MEMORY"] == "1"


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
    models.write_text('[{"name":"test"}]')
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


@pytest.mark.parametrize("context,scale", [(1000000, "2.0"), (2000000, "3.0")])
def test_rope_covers_padded_allocation(context, scale):
    cmd = command(
        settings(),
        {"path": "/model", "id": "model", "native_context": 1000000},
        context,
    )
    assert cmd[cmd.index("--rope-scale") + 1] == scale


@pytest.mark.parametrize(
    "models",
    [
        [],
        {},
        [{"name": ""}],
        [{"name": "../bad"}],
        [{"name": "same"}, {"name": "same"}],
    ],
)
def test_invalid_models_fail_before_output_or_server(tmp_path, monkeypatch, models):
    from scripts import hardware_local_eval as runner

    manifest = tmp_path / "models.json"
    manifest.write_text(json.dumps(models))
    output = tmp_path / "output"
    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--models",
            str(manifest),
            "--server",
            "/missing",
            "--reference-tokenizer",
            "/missing",
            "--output",
            str(output),
            "--execute",
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
    "managed,processes,log,expected",
    [
        (False, "42, 446", "", False),
        (False, "42, 17000", "", True),
        (
            True,
            "42, 446",
            "offloaded 66/66 layers to GPU\nCUDA0 model buffer size = 14674.45 MiB",
            True,
        ),
        (
            True,
            "43, 17000",
            "offloaded 66/66 layers to GPU\nCUDA0 model buffer size = 14674.45 MiB",
            False,
        ),
        (
            True,
            "42, 446",
            "offloaded 0/66 layers to GPU\nCPU model buffer size = 14674.45 MiB",
            False,
        ),
        (True, "42, 446", "", False),
    ],
)
def test_managed_gpu_verification_requires_owned_process_and_native_buffers(
    managed, processes, log, expected
):
    from scripts.hardware_local_eval import gpu_allocation_established

    assert gpu_allocation_established(processes, 42, managed, log) is expected


def asset_manifest(tmp_path):
    weights = tmp_path / "model.gguf"
    weights.write_bytes(b"test weights")
    tokenizer = tmp_path / "tokenizer.json"
    tokenizer.write_text(
        json.dumps(
            {
                "version": "1.0",
                "truncation": None,
                "padding": None,
                "added_tokens": [],
                "normalizer": None,
                "pre_tokenizer": None,
                "post_processor": None,
                "decoder": None,
                "model": {
                    "type": "WordLevel",
                    "vocab": {"unknown": 0},
                    "unk_token": "unknown",
                },
            }
        )
    )
    return {
        "name": "model",
        "id": "local/model",
        "path": str(weights),
        "sha256": "a" * 64,
        "quant": "Q4_K_M",
        "tokenizer": str(tokenizer),
        "revision": "pinned-local",
        "native_context": 262144,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", None),
        ("path", None),
        ("sha256", "not-sha256"),
        ("quant", " "),
        ("tokenizer", None),
        ("revision", ""),
        ("native_context", 0),
        ("native_context", True),
        ("native_context", 1.5),
    ],
)
def test_incomplete_model_manifest_fails_before_output_or_server(
    tmp_path, monkeypatch, field, value
):
    from scripts import hardware_local_eval as runner

    model = asset_manifest(tmp_path)
    model[field] = value
    manifest = tmp_path / "models.json"
    manifest.write_text(json.dumps([model]))
    output = tmp_path / "output"
    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--models",
            str(manifest),
            "--server",
            "/missing",
            "--reference-tokenizer",
            str(tmp_path / "tokenizer.json"),
            "--output",
            str(output),
            "--execute",
        ],
    )
    monkeypatch.setattr(
        runner, "capture", lambda command: pytest.fail("Server must not be probed")
    )
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2
    assert not output.exists()


def test_all_model_assets_and_reference_tokenizer_are_checked(tmp_path):
    pytest.importorskip("tokenizers")
    from scripts.hardware_local_eval import validate_model_assets
    import copy

    model = asset_manifest(tmp_path)
    ref = tmp_path / "tokenizer.json"
    validate_model_assets([model], ref, True)
    for field in ["path", "tokenizer"]:
        invalid = copy.deepcopy(model)
        invalid[field] = str(tmp_path / "missing")
        with pytest.raises(ValueError, match="missing"):
            validate_model_assets([model, invalid], ref, True)
    with pytest.raises(ValueError, match="Missing tokenizer"):
        validate_model_assets([model], tmp_path / "missing", True)
    ref.write_text("not a tokenizer")
    with pytest.raises(ValueError, match="Invalid tokenizer"):
        validate_model_assets([model], ref, True)
