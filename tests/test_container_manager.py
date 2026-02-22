"""Tests for rfc.container_manager.ContainerManager.

All Docker calls are mocked — these tests verify logic without a Docker daemon.
"""

from unittest.mock import MagicMock, patch

import pytest
from docker.errors import DockerException, NotFound

from rfc.docker_config import ContainerConfig


class TestContainerManagerInit:
    @patch("rfc.container_manager.docker")
    def test_successful_init(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        mock_client.ping.assert_called_once()
        assert mgr._active_containers == {}

    @patch("rfc.container_manager.docker")
    def test_init_fails_without_docker(self, mock_docker):
        mock_docker.from_env.side_effect = DockerException("not running")

        from rfc.container_manager import ContainerManager

        with pytest.raises(RuntimeError, match="Docker is not available"):
            ContainerManager()


class TestContainerManagerCreate:
    @patch("rfc.container_manager.docker")
    def test_create_container(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_container.id = "abc123def456"
        mock_client.containers.run.return_value = mock_container

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        config = ContainerConfig(image="python:3.11-slim")
        cid = mgr.create_container(config)

        assert cid == "abc123def456"
        assert "abc123def456" in mgr._active_containers

    @patch("rfc.container_manager.docker")
    def test_create_container_with_name(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_container.id = "xyz789"
        mock_client.containers.run.return_value = mock_container

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        config = ContainerConfig(image="python:3.11-slim")
        mgr.create_container(config, name="test-container")
        assert config.name == "test-container"

    @patch("rfc.container_manager.docker")
    def test_create_container_docker_error(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_client.containers.run.side_effect = DockerException("image not found")

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        config = ContainerConfig(image="nonexistent:latest")

        with pytest.raises(RuntimeError, match="Failed to create container"):
            mgr.create_container(config)


class TestContainerManagerStop:
    @patch("rfc.container_manager.docker")
    def test_stop_container(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_client.containers.get.return_value = mock_container

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        mgr._active_containers["abc123"] = mock_container
        mgr.stop_container("abc123")

        mock_container.stop.assert_called_once_with(timeout=10)
        assert "abc123" not in mgr._active_containers

    @patch("rfc.container_manager.docker")
    def test_stop_already_removed_container(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_client.containers.get.side_effect = NotFound("gone")

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        mgr._active_containers["abc123"] = MagicMock()
        mgr.stop_container("abc123")  # should not raise
        assert "abc123" not in mgr._active_containers

    @patch("rfc.container_manager.docker")
    def test_stop_auto_removed_container(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_container.remove.side_effect = NotFound("auto-removed")
        mock_client.containers.get.return_value = mock_container

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        mgr.stop_container("abc123")  # should not raise


class TestContainerManagerExecute:
    @patch("rfc.container_manager.docker")
    def test_execute_command(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_result = MagicMock()
        mock_result.output = b"hello world\n"
        mock_result.exit_code = 0
        mock_container.exec_run.return_value = mock_result
        mock_client.containers.get.return_value = mock_container

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        result = mgr.execute_command("abc123", "echo hello")

        assert result["stdout"] == "hello world\n"
        assert result["exit_code"] == 0
        assert "duration_ms" in result

    @patch("rfc.container_manager.docker")
    def test_execute_command_not_found(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_client.containers.get.side_effect = NotFound("gone")

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        with pytest.raises(RuntimeError, match="not found"):
            mgr.execute_command("abc123", "ls")

    @patch("rfc.container_manager.docker")
    def test_execute_command_with_workdir(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_result = MagicMock()
        mock_result.output = b""
        mock_result.exit_code = 0
        mock_container.exec_run.return_value = mock_result
        mock_client.containers.get.return_value = mock_container

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        mgr.execute_command("abc123", "ls", workdir="/workspace")

        call_kwargs = mock_container.exec_run.call_args[1]
        assert call_kwargs["workdir"] == "/workspace"

    @patch("rfc.container_manager.docker")
    def test_execute_command_none_output(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_result = MagicMock()
        mock_result.output = None
        mock_result.exit_code = 0
        mock_container.exec_run.return_value = mock_result
        mock_client.containers.get.return_value = mock_container

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        result = mgr.execute_command("abc123", "true")
        assert result["stdout"] == ""


class TestContainerManagerCleanup:
    @patch("rfc.container_manager.docker")
    def test_cleanup_all(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container1 = MagicMock()
        mock_container2 = MagicMock()
        mock_client.containers.get.return_value = mock_container1

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        mgr._active_containers = {"c1": mock_container1, "c2": mock_container2}
        mgr.cleanup_all()

        assert mgr._active_containers == {}

    @patch("rfc.container_manager.docker")
    def test_create_temp_volume(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        path = mgr.create_temp_volume("abc12345")
        assert path.exists()
        assert "rfc-abc12345" in str(path)
        # cleanup
        import shutil

        shutil.rmtree(path)


class TestContainerManagerMetrics:
    @patch("rfc.container_manager.docker")
    def test_get_metrics(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200},
                "system_cpu_usage": 1000,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 500,
            },
            "memory_stats": {
                "usage": 104857600,  # 100 MB
                "limit": 536870912,  # 512 MB
            },
        }
        mock_client.containers.get.return_value = mock_container

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        metrics = mgr.get_metrics("abc123")

        assert "cpu_percent" in metrics
        assert "memory_usage_mb" in metrics
        assert metrics["memory_usage_mb"] == 100.0
        assert metrics["memory_limit_mb"] == 512.0

    @patch("rfc.container_manager.docker")
    def test_get_metrics_error(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_client.containers.get.side_effect = NotFound("gone")

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        metrics = mgr.get_metrics("abc123")
        assert metrics == {}

    @patch("rfc.container_manager.docker")
    def test_get_metrics_zero_system_delta(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 500,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 500,
            },
            "memory_stats": {"usage": 0, "limit": 1},
        }
        mock_client.containers.get.return_value = mock_container

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        metrics = mgr.get_metrics("abc123")
        assert metrics["cpu_percent"] == 0.0


class TestContainerManagerWaitForPort:
    @patch("rfc.container_manager.time")
    @patch("rfc.container_manager.docker")
    def test_port_ready_immediately(self, mock_docker, mock_time):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_container.exec_run.return_value = mock_result
        mock_client.containers.get.return_value = mock_container
        mock_time.time.side_effect = [0, 0.1]

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        assert mgr.wait_for_port("abc123", 8080) is True

    @patch("rfc.container_manager.time")
    @patch("rfc.container_manager.docker")
    def test_port_timeout(self, mock_docker, mock_time):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_result = MagicMock()
        mock_result.exit_code = 1
        mock_container.exec_run.return_value = mock_result
        mock_client.containers.get.return_value = mock_container
        # First call returns 0, second returns 31 (past timeout of 30)
        mock_time.time.side_effect = [0, 31]

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        assert mgr.wait_for_port("abc123", 8080, timeout=30) is False


class TestContainerManagerCopy:
    @patch("rfc.container_manager.docker")
    def test_copy_to_container(self, mock_docker, tmp_path):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_client.containers.get.return_value = mock_container

        # Create a temp file to copy
        src = tmp_path / "test.txt"
        src.write_text("hello")

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        mgr.copy_to_container("abc123", str(src), "/workspace")
        mock_container.put_archive.assert_called_once()

    @patch("rfc.container_manager.docker")
    def test_copy_to_container_directory(self, mock_docker, tmp_path):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_client.containers.get.return_value = mock_container

        src_dir = tmp_path / "mydir"
        src_dir.mkdir()
        (src_dir / "file.txt").write_text("content")

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        mgr.copy_to_container("abc123", str(src_dir), "/workspace")
        mock_container.put_archive.assert_called_once()

    @patch("rfc.container_manager.docker")
    def test_copy_to_container_error(self, mock_docker, tmp_path):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_client.containers.get.side_effect = NotFound("gone")

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        with pytest.raises(RuntimeError, match="Failed to copy to container"):
            mgr.copy_to_container("abc123", str(tmp_path), "/workspace")

    @patch("rfc.container_manager.docker")
    def test_copy_from_container(self, mock_docker, tmp_path):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()

        # Create a minimal tar stream
        import io
        import tarfile

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            data = b"file content"
            info = tarfile.TarInfo(name="test.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        buf.seek(0)

        mock_container.get_archive.return_value = (iter([buf.read()]), {})
        mock_client.containers.get.return_value = mock_container

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        dest = tmp_path / "output"
        mgr.copy_from_container("abc123", "/workspace/test.txt", str(dest))

    @patch("rfc.container_manager.docker")
    def test_copy_from_container_error(self, mock_docker, tmp_path):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_client.containers.get.side_effect = NotFound("gone")

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        with pytest.raises(RuntimeError, match="Failed to copy from container"):
            mgr.copy_from_container("abc123", "/src", str(tmp_path / "out"))


class TestContainerManagerUpdateResources:
    @patch("rfc.container_manager.docker")
    def test_update_resources(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_client.containers.get.return_value = mock_container

        from rfc.container_manager import ContainerManager
        from rfc.docker_config import ContainerResources

        mgr = ContainerManager()
        resources = ContainerResources(memory_mb=1024)
        mgr.update_resources("abc123", resources)
        mock_container.update.assert_called_once()

    @patch("rfc.container_manager.docker")
    def test_update_resources_error(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_container.update.side_effect = DockerException("update failed")
        mock_client.containers.get.return_value = mock_container

        from rfc.container_manager import ContainerManager
        from rfc.docker_config import ContainerResources

        mgr = ContainerManager()
        with pytest.raises(RuntimeError, match="Failed to update resources"):
            mgr.update_resources("abc123", ContainerResources())


class TestContainerManagerExecuteError:
    @patch("rfc.container_manager.docker")
    def test_execute_docker_exception(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_container.exec_run.side_effect = DockerException("exec failed")
        mock_client.containers.get.return_value = mock_container

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        with pytest.raises(RuntimeError, match="Command execution failed"):
            mgr.execute_command("abc123", "bad_command")


class TestContainerManagerStopDockerError:
    @patch("rfc.container_manager.docker")
    def test_stop_docker_exception(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_container.stop.side_effect = DockerException("stop failed")
        mock_client.containers.get.return_value = mock_container

        from rfc.container_manager import ContainerManager

        mgr = ContainerManager()
        mgr._active_containers["abc123"] = mock_container
        mgr.stop_container("abc123")  # should not raise
        assert "abc123" not in mgr._active_containers
