"""Resource and context invariants of the native hardware runner."""

from types import SimpleNamespace

from scripts.hardware_local_eval import command, terminate


def settings():
    return SimpleNamespace(
        server="/local/llama-server", port=8892, gpu_layers=999, kv="f16"
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
