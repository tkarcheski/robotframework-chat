"""Tests for dashboard.core.docker_network utilities."""

import socket
from unittest.mock import patch

from dashboard.core.docker_network import (
    _host_docker_internal_resolves,
    docker_aware_nodes,
    resolve_node_hostname,
    running_in_docker,
)


# ---------------------------------------------------------------------------
# running_in_docker
# ---------------------------------------------------------------------------


class TestRunningInDocker:
    def setup_method(self):
        running_in_docker.cache_clear()

    def teardown_method(self):
        running_in_docker.cache_clear()

    @patch("dashboard.core.docker_network.Path")
    def test_false_when_no_dockerenv(self, mock_path_cls):
        mock_path_cls.return_value.exists.return_value = False
        assert running_in_docker() is False

    @patch("dashboard.core.docker_network.Path")
    def test_true_when_dockerenv_exists(self, mock_path_cls):
        mock_path_cls.return_value.exists.return_value = True
        assert running_in_docker() is True


# ---------------------------------------------------------------------------
# resolve_node_hostname
# ---------------------------------------------------------------------------


class TestResolveNodeHostname:
    def setup_method(self):
        running_in_docker.cache_clear()
        _host_docker_internal_resolves.cache_clear()

    def teardown_method(self):
        running_in_docker.cache_clear()
        _host_docker_internal_resolves.cache_clear()

    @patch(
        "dashboard.core.docker_network.running_in_docker", return_value=False
    )
    def test_noop_outside_docker(self, _mock):
        _host_docker_internal_resolves.cache_clear()
        assert resolve_node_hostname("localhost") == "localhost"
        assert resolve_node_hostname("127.0.0.1") == "127.0.0.1"

    @patch(
        "dashboard.core.docker_network.running_in_docker", return_value=True
    )
    @patch("dashboard.core.docker_network.socket.getaddrinfo")
    def test_rewrites_localhost_in_bridge_docker(self, mock_dns, _mock):
        mock_dns.return_value = [
            (None, None, None, None, ("192.168.65.2", 0))
        ]
        _host_docker_internal_resolves.cache_clear()
        assert resolve_node_hostname("localhost") == "host.docker.internal"
        assert resolve_node_hostname("127.0.0.1") == "host.docker.internal"

    def test_noop_for_non_localhost(self):
        assert resolve_node_hostname("mini1") == "mini1"
        assert resolve_node_hostname("ai1") == "ai1"
        assert resolve_node_hostname("192.168.1.100") == "192.168.1.100"

    @patch(
        "dashboard.core.docker_network.running_in_docker", return_value=True
    )
    @patch(
        "dashboard.core.docker_network.socket.getaddrinfo",
        side_effect=socket.gaierror("Name not resolved"),
    )
    def test_noop_in_host_networking(self, _mock_dns, _mock_docker):
        """host.docker.internal does not resolve under network_mode: host."""
        _host_docker_internal_resolves.cache_clear()
        assert resolve_node_hostname("localhost") == "localhost"


# ---------------------------------------------------------------------------
# docker_aware_nodes
# ---------------------------------------------------------------------------


class TestDockerAwareNodes:
    def setup_method(self):
        running_in_docker.cache_clear()
        _host_docker_internal_resolves.cache_clear()

    def teardown_method(self):
        running_in_docker.cache_clear()
        _host_docker_internal_resolves.cache_clear()

    @patch(
        "dashboard.core.docker_network._host_docker_internal_resolves",
        return_value=True,
    )
    def test_does_not_mutate_input(self, _mock):
        original = [{"hostname": "localhost", "port": 11434}]
        result = docker_aware_nodes(original)
        assert original[0]["hostname"] == "localhost"  # not mutated
        assert result[0]["hostname"] == "host.docker.internal"

    def test_preserves_non_localhost_nodes(self):
        nodes = [
            {"hostname": "mini1", "port": 11434},
            {"hostname": "ai1", "port": 11434},
        ]
        result = docker_aware_nodes(nodes)
        assert result[0]["hostname"] == "mini1"
        assert result[1]["hostname"] == "ai1"

    @patch(
        "dashboard.core.docker_network._host_docker_internal_resolves",
        return_value=True,
    )
    def test_rewrites_only_localhost_nodes(self, _mock):
        nodes = [
            {"hostname": "localhost", "port": 11434},
            {"hostname": "mini1", "port": 11434},
            {"hostname": "127.0.0.1", "port": 11434},
        ]
        result = docker_aware_nodes(nodes)
        assert result[0]["hostname"] == "host.docker.internal"
        assert result[1]["hostname"] == "mini1"
        assert result[2]["hostname"] == "host.docker.internal"

    @patch(
        "dashboard.core.docker_network._host_docker_internal_resolves",
        return_value=False,
    )
    def test_no_rewrite_outside_docker(self, _mock):
        nodes = [
            {"hostname": "localhost", "port": 11434},
            {"hostname": "mini1", "port": 11434},
        ]
        result = docker_aware_nodes(nodes)
        assert result[0]["hostname"] == "localhost"
        assert result[1]["hostname"] == "mini1"
