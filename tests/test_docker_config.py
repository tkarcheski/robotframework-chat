"""Tests for rfc.docker_config dataclasses."""

import pytest

from rfc.docker_config import (
    ContainerConfig,
    ContainerNetwork,
    ContainerResources,
    normalize_volumes,
)


class TestContainerResources:
    def test_default_values(self):
        r = ContainerResources()
        assert r.cpu_cores is None
        assert r.memory_mb is None

    def test_to_docker_resources_with_memory(self):
        r = ContainerResources(memory_mb=512)
        result = r.to_docker_resources()
        assert result["mem_limit"] == "512m"

    def test_to_docker_resources_with_cpu(self):
        r = ContainerResources(cpu_shares=512, cpu_quota=50000, cpu_period=100000)
        result = r.to_docker_resources()
        assert result["cpu_shares"] == 512
        assert result["cpu_quota"] == 50000

    def test_to_docker_resources_empty(self):
        r = ContainerResources()
        result = r.to_docker_resources()
        assert result == {}

    def test_to_docker_resources_shm(self):
        r = ContainerResources(shm_size_mb=64)
        result = r.to_docker_resources()
        assert result["shm_size"] == "64m"


class TestContainerNetwork:
    def test_default_none_mode(self):
        n = ContainerNetwork()
        result = n.to_docker_network()
        assert result["network_mode"] == "none"

    def test_host_mode(self):
        n = ContainerNetwork(mode="host")
        result = n.to_docker_network()
        assert result["network_mode"] == "host"

    def test_bridge_mode_with_ports(self):
        n = ContainerNetwork(mode="bridge", ports={"8080/tcp": "8080"})
        result = n.to_docker_network()
        assert result["ports"] == {"8080/tcp": "8080"}
        assert result.get("network_disabled") is False

    def test_bridge_mode_with_dns(self):
        n = ContainerNetwork(mode="bridge", dns=["8.8.8.8"])
        result = n.to_docker_network()
        assert result["dns"] == ["8.8.8.8"]


class TestContainerConfig:
    def test_default_values(self):
        cfg = ContainerConfig(image="python:3.12")
        assert cfg.image == "python:3.12"
        assert cfg.read_only is True
        assert cfg.user == "nobody"
        assert cfg.auto_remove is False

    def test_from_dict_minimal(self):
        cfg = ContainerConfig.from_dict({"image": "python:3.12"})
        assert cfg.image == "python:3.12"

    def test_from_dict_full(self):
        cfg = ContainerConfig.from_dict(
            {
                "image": "python:3.12",
                "name": "test-container",
                "command": "python -c 'print(1)'",
                "resources": {"memory_mb": 512},
                "network": {"mode": "bridge"},
                "env": {"FOO": "bar"},
                "read_only": False,
            }
        )
        assert cfg.name == "test-container"
        assert cfg.resources.memory_mb == 512
        assert cfg.network.mode == "bridge"
        assert cfg.env == {"FOO": "bar"}

    def test_to_docker_run_config(self):
        cfg = ContainerConfig(
            image="python:3.12",
            name="test",
            command="echo hello",
        )
        result = cfg.to_docker_run_config()
        assert result["image"] == "python:3.12"
        assert result["name"] == "test"
        assert result["command"] == "echo hello"
        assert result["read_only"] is True

    def test_to_docker_run_config_strips_none(self):
        cfg = ContainerConfig(image="python:3.12", command=None)
        result = cfg.to_docker_run_config()
        assert "command" not in result


class TestContainerResourcesMemswapZero:
    def test_memswap_zero_uses_negative_one(self):
        from rfc.docker_config import ContainerResources

        res = ContainerResources(memory_swap_mb=0)
        d = res.to_docker_resources()
        assert d["memswap_limit"] == -1

    def test_memswap_negative_uses_negative_one(self):
        from rfc.docker_config import ContainerResources

        res = ContainerResources(memory_swap_mb=-1)
        d = res.to_docker_resources()
        assert d["memswap_limit"] == -1


class TestNormalizeVolumes:
    """Pin the volume shapes docker-py accepts (regression guard for #189).

    docker-py's ``containers.run`` does ``value.get('bind')`` on every dict
    value, so a str-valued ``volumes`` dict raises ``AttributeError`` and no
    container is created. ``normalize_volumes`` must turn the str shape into the
    dict shape and leave already-valid shapes untouched.
    """

    def test_str_valued_dict_is_normalized_to_bind_mode_dict(self):
        # Exactly what robot/resources/environments.resource used to build.
        result = normalize_volumes({"/tmp/rfc-env/py-1": "/workspace:rw"})
        assert result == {"/tmp/rfc-env/py-1": {"bind": "/workspace", "mode": "rw"}}

    def test_str_value_without_mode_defaults_to_rw(self):
        result = normalize_volumes({"/host": "/workspace"})
        assert result == {"/host": {"bind": "/workspace", "mode": "rw"}}

    def test_dict_valued_dict_passes_through_unchanged(self):
        spec = {"/host": {"bind": "/workspace", "mode": "ro"}}
        assert normalize_volumes(spec) == spec

    def test_list_form_passes_through_unchanged(self):
        spec = ["/host:/workspace:rw"]
        assert normalize_volumes(spec) == spec

    def test_empty_and_none_return_empty_dict(self):
        assert normalize_volumes(None) == {}
        assert normalize_volumes({}) == {}

    def test_unsupported_value_type_raises_typeerror(self):
        with pytest.raises(TypeError):
            normalize_volumes({"/host": 42})

    def test_normalized_values_survive_docker_py_bind_extraction(self):
        # Replays docker/models/containers.py: [v.get('bind') for v in values].
        # Before #189's fix this raised AttributeError on the str value.
        result = normalize_volumes({"/tmp/rfc-env/py-1": "/workspace:rw"})
        binds = [v.get("bind") for v in result.values()]
        assert binds == ["/workspace"]

    def test_valid_dict_value_is_not_silently_rewritten(self):
        # A dict value must pass through as the SAME object -- normalize_volumes
        # must never inject a default mode or otherwise mutate a valid spec that
        # docker-py already accepts (guards against silent rewriting).
        inner = {"bind": "/workspace", "mode": "ro"}
        result = normalize_volumes({"/host": inner})
        assert result["/host"] is inner

    def test_dict_value_without_mode_passes_through_unchanged(self):
        # docker-py accepts a bind-only dict (defaults to rw); normalize_volumes
        # must not "helpfully" add a mode key it did not have.
        spec = {"/host": {"bind": "/workspace"}}
        assert normalize_volumes(spec) == {"/host": {"bind": "/workspace"}}

    def test_mixed_str_and_dict_values_each_handled(self):
        result = normalize_volumes(
            {"/a": "/workspace:rw", "/b": {"bind": "/w2", "mode": "ro"}}
        )
        assert result == {
            "/a": {"bind": "/workspace", "mode": "rw"},
            "/b": {"bind": "/w2", "mode": "ro"},
        }

    def test_duplicate_container_binds_are_both_preserved(self):
        result = normalize_volumes({"/a": "/workspace:rw", "/b": "/workspace:rw"})
        assert result == {
            "/a": {"bind": "/workspace", "mode": "rw"},
            "/b": {"bind": "/workspace", "mode": "rw"},
        }

    def test_none_valued_spec_raises_typeerror(self):
        # Complements the int case: any non-str, non-dict value is a hard error,
        # never a silently dropped or mis-shaped volume.
        with pytest.raises(TypeError):
            normalize_volumes({"/host": None})


class TestToDockerRunConfigVolumes:
    """#189: to_docker_run_config must never emit a str-valued volumes dict."""

    def test_str_valued_volumes_are_normalized(self):
        cfg = ContainerConfig(
            image="python:3.11-slim",
            command="sleep infinity",
            volumes={"/tmp/rfc-env/py-1": "/workspace:rw"},
        )
        result = cfg.to_docker_run_config()
        assert result["volumes"] == {
            "/tmp/rfc-env/py-1": {"bind": "/workspace", "mode": "rw"}
        }
        # Every value is a dict -> docker-py's value.get('bind') cannot raise.
        assert all(isinstance(v, dict) for v in result["volumes"].values())

    def test_no_volumes_yields_empty_dict(self):
        cfg = ContainerConfig(image="python:3.11-slim")
        assert cfg.to_docker_run_config()["volumes"] == {}
