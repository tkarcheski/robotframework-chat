"""Tests for rfc.docker_config dataclasses."""

import pytest

from rfc.docker_config import ContainerConfig, ContainerNetwork, ContainerResources


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
        n = ContainerNetwork(
            mode="bridge", ports={"8080/tcp": "8080"}
        )
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
        assert cfg.auto_remove is True

    def test_from_dict_minimal(self):
        cfg = ContainerConfig.from_dict({"image": "python:3.12"})
        assert cfg.image == "python:3.12"

    def test_from_dict_full(self):
        cfg = ContainerConfig.from_dict({
            "image": "python:3.12",
            "name": "test-container",
            "command": "python -c 'print(1)'",
            "resources": {"memory_mb": 512},
            "network": {"mode": "bridge"},
            "env": {"FOO": "bar"},
            "read_only": False,
        })
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
