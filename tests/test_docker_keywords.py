"""Tests for rfc.docker_keywords.ConfigurableDockerKeywords."""

import socket
from unittest.mock import MagicMock, patch

import pytest

from rfc.docker_keywords import ConfigurableDockerKeywords


class TestDockerKeywordsInit:
    def test_initial_state(self):
        kw = ConfigurableDockerKeywords()
        assert kw._manager is None
        assert kw._container_configs == {}


class TestDockerIsAvailable:
    @patch("rfc.docker_keywords.ContainerManager")
    def test_docker_available(self, MockMgr):
        kw = ConfigurableDockerKeywords()
        assert kw.docker_is_available() is True

    @patch("rfc.docker_keywords.ContainerManager")
    def test_docker_not_available(self, MockMgr):
        MockMgr.side_effect = RuntimeError("Docker not available")
        kw = ConfigurableDockerKeywords()
        assert kw.docker_is_available() is False


class TestFindAvailablePort:
    def test_finds_port(self):
        kw = ConfigurableDockerKeywords()
        # Should find a port in a large range
        port = kw.find_available_port(start_port=49152, end_port=49200)
        assert 49152 <= port <= 49200

    def test_no_port_available(self):
        """When all ports are taken, should raise RuntimeError."""
        kw = ConfigurableDockerKeywords()
        # Bind a port then search that single-port range
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("localhost", 0))
            port = s.getsockname()[1]
            with pytest.raises(RuntimeError, match="No available port"):
                kw.find_available_port(start_port=port, end_port=port)


class TestCreateConfigurableContainer:
    @patch("rfc.docker_keywords.ContainerManager")
    def test_create_with_basic_config(self, MockMgr):
        mock_mgr = MagicMock()
        mock_mgr.create_container.return_value = "container-id-123"
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        config = {"image": "python:3.11-slim"}
        cid = kw.create_configurable_container(config, name="test")

        assert cid == "container-id-123"
        mock_mgr.create_container.assert_called_once()
        assert "container-id-123" in kw._container_configs

    @patch("rfc.docker_keywords.ContainerManager")
    def test_create_with_resources(self, MockMgr):
        mock_mgr = MagicMock()
        mock_mgr.create_container.return_value = "cid"
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        config = {
            "image": "python:3.11-slim",
            "cpu_cores": 0.5,
            "memory_mb": 256,
            "network_mode": "none",
        }
        kw.create_configurable_container(config)

        call_args = mock_mgr.create_container.call_args[0][0]
        assert call_args.resources.cpu_quota == 50000
        assert call_args.resources.memory_mb == 256
        assert call_args.network.mode == "none"

    @patch("rfc.docker_keywords.ContainerManager")
    def test_create_with_string_bool(self, MockMgr):
        mock_mgr = MagicMock()
        mock_mgr.create_container.return_value = "cid"
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        config = {
            "image": "python:3.11-slim",
            "read_only": "true",
            "auto_remove": "false",
        }
        kw.create_configurable_container(config)

        call_args = mock_mgr.create_container.call_args[0][0]
        assert call_args.read_only is True
        assert call_args.auto_remove is False


class TestStopContainer:
    @patch("rfc.docker_keywords.ContainerManager")
    def test_stop_delegates(self, MockMgr):
        mock_mgr = MagicMock()
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        kw.stop_container("cid", timeout=5)
        mock_mgr.stop_container.assert_called_once_with("cid", 5)


class TestExecuteInContainer:
    @patch("rfc.docker_keywords.ContainerManager")
    def test_execute_delegates(self, MockMgr):
        mock_mgr = MagicMock()
        mock_mgr.execute_command.return_value = {"stdout": "ok", "exit_code": 0}
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        result = kw.execute_in_container("cid", "echo ok")
        assert result["stdout"] == "ok"


class TestCleanupAll:
    @patch("rfc.docker_keywords.ContainerManager")
    def test_cleanup_clears_configs(self, MockMgr):
        mock_mgr = MagicMock()
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        kw._container_configs["c1"] = MagicMock()
        kw.cleanup_all_containers()
        mock_mgr.cleanup_all.assert_called_once()
        assert kw._container_configs == {}


class TestCreateCodeExecutionContainer:
    @patch("rfc.docker_keywords.ContainerManager")
    def test_creates_with_defaults(self, MockMgr):
        mock_mgr = MagicMock()
        mock_mgr.create_container.return_value = "exec-cid"
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        cid = kw.create_code_execution_container()
        assert cid == "exec-cid"

        call_config = mock_mgr.create_container.call_args[0][0]
        assert call_config.image == "python:3.11-slim"
        assert call_config.network.mode == "none"
        assert call_config.read_only is True


class TestExecutePythonInContainer:
    @patch("rfc.docker_keywords.ContainerManager")
    def test_execute_python_creates_temp_container(self, MockMgr):
        mock_mgr = MagicMock()
        mock_mgr.create_container.return_value = "temp-cid"
        mock_mgr.execute_command.return_value = {
            "stdout": "Hello\n",
            "exit_code": 0,
            "stderr": "",
            "duration_ms": 100,
        }
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        result = kw.execute_python_in_container("print('Hello')")

        assert result["stdout"] == "Hello\n"
        # stop_container is called via the keyword which passes default timeout=10
        mock_mgr.stop_container.assert_called_once_with("temp-cid", 10)

    @patch("rfc.docker_keywords.ContainerManager")
    def test_execute_python_reuses_container(self, MockMgr):
        mock_mgr = MagicMock()
        mock_mgr.execute_command.return_value = {
            "stdout": "42\n",
            "exit_code": 0,
            "stderr": "",
            "duration_ms": 50,
        }
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        result = kw.execute_python_in_container("print(42)", container_id="existing")

        assert result["stdout"] == "42\n"
        mock_mgr.stop_container.assert_not_called()


class TestStopContainerByName:
    @patch("rfc.docker_keywords.ContainerManager")
    def test_stop_by_name(self, MockMgr):
        mock_mgr = MagicMock()
        mock_container = MagicMock()
        mock_container.id = "resolved-id"
        mock_mgr.client.containers.get.return_value = mock_container
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        kw.stop_container_by_name("my-container")
        mock_mgr.stop_container.assert_called_once_with("resolved-id", 10)

    @patch("rfc.docker_keywords.ContainerManager")
    def test_stop_by_name_not_found(self, MockMgr):
        from docker.errors import NotFound

        mock_mgr = MagicMock()
        mock_mgr.client.containers.get.side_effect = NotFound("gone")
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        kw.stop_container_by_name("missing")  # should not raise

    @patch("rfc.docker_keywords.ContainerManager")
    def test_stop_by_name_error(self, MockMgr):
        mock_mgr = MagicMock()
        mock_mgr.client.containers.get.side_effect = Exception("unexpected")
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        kw.stop_container_by_name("broken")  # should not raise


class TestWaitForContainerPort:
    @patch("rfc.docker_keywords.ContainerManager")
    def test_wait_delegates(self, MockMgr):
        mock_mgr = MagicMock()
        mock_mgr.wait_for_port.return_value = True
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        assert kw.wait_for_container_port("cid", 8080) is True
        mock_mgr.wait_for_port.assert_called_once_with("cid", 8080, 30)


class TestCopyKeywords:
    @patch("rfc.docker_keywords.ContainerManager")
    def test_copy_to_delegates(self, MockMgr):
        mock_mgr = MagicMock()
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        kw.copy_to_container("cid", "/host/path", "/container/path")
        mock_mgr.copy_to_container.assert_called_once_with(
            "cid", "/host/path", "/container/path"
        )

    @patch("rfc.docker_keywords.ContainerManager")
    def test_copy_from_delegates(self, MockMgr):
        mock_mgr = MagicMock()
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        kw.copy_from_container("cid", "/container/path", "/host/path")
        mock_mgr.copy_from_container.assert_called_once_with(
            "cid", "/container/path", "/host/path"
        )


class TestGetContainerMetrics:
    @patch("rfc.docker_keywords.ContainerManager")
    def test_metrics_delegates(self, MockMgr):
        mock_mgr = MagicMock()
        mock_mgr.get_metrics.return_value = {"cpu_percent": 5.0}
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        result = kw.get_container_metrics("cid")
        assert result["cpu_percent"] == 5.0


class TestUpdateContainerResources:
    @patch("rfc.docker_keywords.ContainerManager")
    def test_update_delegates(self, MockMgr):
        mock_mgr = MagicMock()
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        kw.update_container_resources("cid", {"cpu_cores": 2.0, "memory_mb": 1024})
        mock_mgr.update_resources.assert_called_once()

        resources = mock_mgr.update_resources.call_args[0][1]
        assert resources.cpu_quota == 200000
        assert resources.memory_mb == 1024


class TestCreateWithAllOptions:
    @patch("rfc.docker_keywords.ContainerManager")
    def test_all_resource_options(self, MockMgr):
        mock_mgr = MagicMock()
        mock_mgr.create_container.return_value = "cid"
        MockMgr.return_value = mock_mgr

        kw = ConfigurableDockerKeywords()
        config = {
            "image": "python:3.11-slim",
            "cpu_cores": 1.0,
            "cpu_shares": 512,
            "memory_mb": 256,
            "memory_swap_mb": 512,
            "scratch_mb": 100,
            "shm_size_mb": 64,
            "network_mode": "bridge",
            "ports": {"8080": "8080"},
            "dns": ["8.8.8.8"],
            "command": "sleep 10",
            "volumes": {"/host": "/container"},
            "env": {"FOO": "bar"},
            "labels": {"app": "test"},
            "user": "root",
            "working_dir": "/app",
        }
        kw.create_configurable_container(config)

        call_config = mock_mgr.create_container.call_args[0][0]
        assert call_config.resources.cpu_quota == 100000
        assert call_config.resources.cpu_shares == 512
        assert call_config.resources.memory_swap_mb == 512
        assert call_config.resources.scratch_mb == 100
        assert call_config.resources.shm_size_mb == 64
        assert call_config.network.ports == {"8080": "8080"}
        assert call_config.network.dns == ["8.8.8.8"]
        assert call_config.command == "sleep 10"
        assert call_config.user == "root"
