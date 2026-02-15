"""Container lifecycle management for Docker-based code execution."""

import time
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
from robot.api import logger
import docker
from docker.errors import DockerException, NotFound

from .docker_config import ContainerConfig, ContainerResources


class ContainerManager:
    """Manages Docker container lifecycle with resource constraints."""

    def __init__(self):
        try:
            self.client = docker.from_env()
            self.client.ping()
        except DockerException as e:
            raise RuntimeError(
                "Docker is not available. Please ensure Docker is installed and running."
            ) from e

        self._active_containers: Dict[str, Any] = {}
        self._temp_dirs: Dict[str, Path] = {}

    def create_container(
        self, config: ContainerConfig, name: Optional[str] = None
    ) -> str:
        """Create and start a container with the given configuration.

        Args:
            config: ContainerConfig with image, resources, network settings
            name: Optional container name override

        Returns:
            Container ID string
        """
        if name:
            config.name = name

        run_config = config.to_docker_run_config()
        logger.info(f"Creating container with config: {run_config}")

        try:
            container = self.client.containers.run(**run_config)
            self._active_containers[container.id] = container
            logger.info(f"Container {container.id[:12]} started successfully")
            return container.id
        except DockerException as e:
            raise RuntimeError(f"Failed to create container: {e}") from e

    def stop_container(self, container_id: str, timeout: int = 10) -> None:
        """Stop and remove a container.

        Handles containers that have already been stopped or auto-removed
        by Docker (auto_remove=True) without raising warnings.

        Args:
            container_id: ID of container to stop
            timeout: Seconds to wait for graceful shutdown
        """
        try:
            container = self.client.containers.get(container_id)
            logger.info(f"Stopping container {container_id[:12]}")
            container.stop(timeout=timeout)
            try:
                container.remove(force=True)
            except NotFound:
                # Container was auto-removed after stop, this is expected
                pass

            logger.info(f"Container {container_id[:12]} stopped and removed")

        except NotFound:
            # Container already gone (auto-removed or manually stopped)
            logger.info(f"Container {container_id[:12]} already removed")
        except DockerException as e:
            logger.error(f"Error stopping container {container_id[:12]}: {e}")
        finally:
            # Always clean up internal tracking regardless of outcome
            self._active_containers.pop(container_id, None)

    def execute_command(
        self,
        container_id: str,
        command: str,
        timeout: int = 30,
        workdir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a command in a running container.

        Args:
            container_id: ID of container
            command: Command to execute
            timeout: Maximum execution time in seconds
            workdir: Working directory in container

        Returns:
            Dict with stdout, stderr, exit_code, duration_ms
        """
        try:
            container = self.client.containers.get(container_id)
        except NotFound:
            raise RuntimeError(f"Container {container_id[:12]} not found")

        exec_config = {
            "cmd": ["sh", "-c", command],
            "stdout": True,
            "stderr": True,
            "tty": False,
        }

        if workdir:
            exec_config["workdir"] = workdir

        start_time = time.time()

        try:
            logger.info(f"Executing in {container_id[:12]}: {command[:100]}...")
            result = container.exec_run(**exec_config)
            duration_ms = int((time.time() - start_time) * 1000)

            return {
                "stdout": result.output.decode("utf-8", errors="replace")
                if result.output
                else "",
                "stderr": "",  # exec_run combines stdout/stderr
                "exit_code": result.exit_code,
                "duration_ms": duration_ms,
            }
        except DockerException as e:
            raise RuntimeError(f"Command execution failed: {e}") from e

    def wait_for_port(self, container_id: str, port: int, timeout: int = 30) -> bool:
        """Wait for a port to be ready in the container.

        Args:
            container_id: ID of container
            port: Port number to check
            timeout: Maximum wait time in seconds

        Returns:
            True if port is ready, False if timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                container = self.client.containers.get(container_id)
                # Try to execute a command that checks if port is listening
                result = container.exec_run(
                    cmd=[
                        "sh",
                        "-c",
                        f'cat /proc/net/tcp | grep ":{port:04X}" || nc -z localhost {port}',
                    ],
                    stdout=True,
                    stderr=True,
                )
                if result.exit_code == 0:
                    logger.info(
                        f"Port {port} is ready on container {container_id[:12]}"
                    )
                    return True
            except Exception:
                pass

            time.sleep(1)

        logger.warn(f"Timeout waiting for port {port} on container {container_id[:12]}")
        return False

    def copy_to_container(
        self, container_id: str, host_path: str, container_path: str
    ) -> None:
        """Copy files from host to container.

        Args:
            container_id: ID of container
            host_path: Source path on host
            container_path: Destination path in container
        """
        import tarfile
        import io

        try:
            container = self.client.containers.get(container_id)
            host_path_obj = Path(host_path)

            # Create tar archive
            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
                if host_path_obj.is_file():
                    tar.add(host_path_obj, arcname=host_path_obj.name)
                else:
                    tar.add(host_path_obj, arcname=".")

            tar_buffer.seek(0)
            container.put_archive(container_path, tar_buffer.read())
            logger.info(f"Copied {host_path} to {container_id[:12]}:{container_path}")

        except Exception as e:
            raise RuntimeError(f"Failed to copy to container: {e}") from e

    def copy_from_container(
        self, container_id: str, container_path: str, host_path: str
    ) -> None:
        """Copy files from container to host.

        Args:
            container_id: ID of container
            container_path: Source path in container
            host_path: Destination path on host
        """
        try:
            container = self.client.containers.get(container_id)
            host_path_obj = Path(host_path)
            host_path_obj.parent.mkdir(parents=True, exist_ok=True)

            stream, stat = container.get_archive(container_path)

            # Extract tar stream to host path
            import tarfile
            import io

            tar_buffer = io.BytesIO()
            for chunk in stream:
                tar_buffer.write(chunk)
            tar_buffer.seek(0)

            with tarfile.open(fileobj=tar_buffer, mode="r") as tar:
                tar.extractall(path=host_path_obj)

            logger.info(
                f"Copied {container_id[:12]}:{container_path} to {host_path_obj}"
            )

        except Exception as e:
            raise RuntimeError(f"Failed to copy from container: {e}") from e

    def get_metrics(self, container_id: str) -> Dict[str, Any]:
        """Get resource usage metrics for a container.

        Args:
            container_id: ID of container

        Returns:
            Dict with cpu_percent, memory_usage_mb, etc.
        """
        try:
            container = self.client.containers.get(container_id)
            stats_result = container.stats(stream=False)

            # Handle both dict (stream=False) and iterator cases
            if isinstance(stats_result, dict):
                stats: Dict[str, Any] = stats_result
            else:
                # It's an iterator, get the first item
                stats = next(stats_result)

            # Calculate CPU percentage
            cpu_delta = (
                stats["cpu_stats"]["cpu_usage"]["total_usage"]
                - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            system_delta = (
                stats["cpu_stats"]["system_cpu_usage"]
                - stats["precpu_stats"]["system_cpu_usage"]
            )
            cpu_percent = 0.0
            if system_delta > 0:
                cpu_percent = (cpu_delta / system_delta) * 100

            # Memory usage (with safe access)
            memory_stats = stats.get("memory_stats", {})
            memory_usage = memory_stats.get("usage", 0)
            memory_limit = memory_stats.get("limit", 1)

            memory_usage_mb = memory_usage / (1024 * 1024)
            memory_limit_mb = memory_limit / (1024 * 1024)
            memory_percent = (
                (memory_usage_mb / memory_limit_mb * 100) if memory_limit_mb > 0 else 0
            )

            return {
                "cpu_percent": round(cpu_percent, 2),
                "memory_usage_mb": round(memory_usage_mb, 2),
                "memory_limit_mb": round(memory_limit_mb, 2),
                "memory_percent": round(memory_percent, 2),
            }

        except Exception as e:
            logger.warn(f"Failed to get metrics for {container_id[:12]}: {e}")
            return {}

    def update_resources(
        self, container_id: str, resources: ContainerResources
    ) -> None:
        """Update resource limits for a running container.

        Args:
            container_id: ID of container
            resources: New resource limits
        """
        try:
            container = self.client.containers.get(container_id)
            docker_resources = resources.to_docker_resources()
            container.update(**docker_resources)
            logger.info(f"Updated resources for {container_id[:12]}")
        except DockerException as e:
            raise RuntimeError(f"Failed to update resources: {e}") from e

    def cleanup_all(self) -> None:
        """Stop and remove all containers managed by this instance."""
        logger.info(f"Cleaning up {len(self._active_containers)} containers")

        for container_id in list(self._active_containers.keys()):
            self.stop_container(container_id)

        # Cleanup temp directories
        for temp_dir in self._temp_dirs.values():
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                logger.info(f"Cleaned up temp directory: {temp_dir}")

    def create_temp_volume(
        self, container_id: str, size_mb: Optional[int] = None
    ) -> Path:
        """Create a temporary directory for container use.

        Args:
            container_id: Container ID this volume is for
            size_mb: Optional size limit (not enforced, just tracked)

        Returns:
            Path to temp directory
        """
        temp_dir = Path(tempfile.mkdtemp(prefix=f"rfc-{container_id[:8]}-"))
        self._temp_dirs[container_id] = temp_dir
        logger.info(f"Created temp volume: {temp_dir}")
        return temp_dir
