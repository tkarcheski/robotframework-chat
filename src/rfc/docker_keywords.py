"""Configurable Docker keywords for Robot Framework."""

import shutil
import socket
from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .container_manager import ContainerManager
from .docker_config import ContainerConfig, ContainerNetwork, ContainerResources


class ConfigurableDockerKeywords:
    """Keywords for configurable Docker container management."""

    def __init__(self):
        self._manager: Optional[ContainerManager] = None
        self._container_configs: Dict[str, ContainerConfig] = {}

    @property
    def manager(self) -> ContainerManager:
        """Lazy initialization of container manager."""
        if self._manager is None:
            self._manager = ContainerManager()
        return self._manager

    @keyword("Docker Is Available")
    def docker_is_available(self) -> bool:
        """Check if Docker daemon is available."""
        try:
            _ = self.manager  # triggers lazy init, which pings Docker
            return True
        except RuntimeError:
            return False

    @keyword("Check Docker Setup")
    def check_docker_setup(self, raise_on_failure: bool = False) -> Dict[str, Any]:
        """Check that Docker is installed and the daemon is running."""
        errors: List[str] = []
        result: Dict[str, Any] = {
            "docker_cli": False,
            "docker_cli_path": "",
            "daemon_running": False,
            "docker_version": "",
            "api_version": "",
            "errors": errors,
        }

        # Check 1: Docker CLI on PATH
        docker_path = shutil.which("docker")
        if docker_path:
            result["docker_cli"] = True
            result["docker_cli_path"] = docker_path
            logger.info(f"Docker CLI found at {docker_path}")
        else:
            errors.append(
                "Docker CLI not found on PATH. "
                "Please install Docker: https://docs.docker.com/get-docker/"
            )
            logger.warn("Docker CLI not installed or not on PATH")

        # Check 2 & 3: Daemon connectivity and version
        try:
            mgr = self.manager  # triggers lazy init, pings daemon
            version_info = mgr.client.version()
            result["daemon_running"] = True
            result["docker_version"] = version_info.get("Version", "")
            result["api_version"] = version_info.get("ApiVersion", "")
            logger.info(
                f"Docker daemon running: v{result['docker_version']} "
                f"(API v{result['api_version']})"
            )
        except RuntimeError:
            result["daemon_running"] = False
            errors.append(
                "Docker daemon is not running. Please start Docker and try again."
            )
            logger.warn("Docker daemon is not running or not accessible")

        if errors and raise_on_failure:
            msg = "Docker setup check failed:\n" + "\n".join(f"  - {e}" for e in errors)
            raise RuntimeError(msg)

        return result

    @keyword("Find Available Port")
    def find_available_port(
        self, start_port: int = 11434, end_port: int = 11500
    ) -> int:
        """Find an available TCP port in the given range (raises PortAllocationError if none)."""
        for port in range(start_port, end_port + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                try:
                    sock.bind(("localhost", port))
                    return port
                except OSError:
                    continue

        from rfc.exceptions import PortAllocationError

        raise PortAllocationError(start_port=start_port, end_port=end_port)

    @keyword("Create Configurable Container")
    def create_configurable_container(
        self, config: Dict[str, Any], name: Optional[str] = None
    ) -> str:
        """Create a Docker container with full resource configuration.

        ``config`` is a dict whose recognized keys are enumerated by the
        parsing below; ``image`` is required, the rest optional.
        """
        # Parse nested resource config
        resources = ContainerResources()
        if "cpu_cores" in config:
            resources.cpu_quota = int(float(config["cpu_cores"]) * 100000)
        if "cpu_shares" in config:
            resources.cpu_shares = config["cpu_shares"]
        if "memory_mb" in config:
            resources.memory_mb = config["memory_mb"]
        if "memory_swap_mb" in config:
            resources.memory_swap_mb = config["memory_swap_mb"]
        if "scratch_mb" in config:
            resources.scratch_mb = config["scratch_mb"]
        if "shm_size_mb" in config:
            resources.shm_size_mb = config["shm_size_mb"]

        # Parse network config
        network = ContainerNetwork(mode=config.get("network_mode", "none"))
        if "ports" in config:
            network.ports = config["ports"]
        if "dns" in config:
            network.dns = config["dns"]

        def to_bool(value, default=True):
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes", "on")
            return default

        container_config = ContainerConfig(
            image=config["image"],
            name=name,
            command=config.get("command"),
            resources=resources,
            network=network,
            volumes=config.get("volumes", {}),
            env=config.get("env", {}),
            labels=config.get("labels", {}),
            read_only=to_bool(config.get("read_only"), True),
            user=config.get("user", "nobody"),
            working_dir=config.get("working_dir", "/workspace"),
            auto_remove=to_bool(config.get("auto_remove"), False),
            detach=to_bool(config.get("detach"), True),
        )

        container_id = self.manager.create_container(container_config, name)
        self._container_configs[container_id] = container_config

        return container_id

    @keyword("Stop Container")
    def stop_container(self, container_id: str, timeout: int = 10) -> None:
        """Stop and remove a container."""
        self.manager.stop_container(container_id, timeout)

    @keyword("Stop Container By Name")
    def stop_container_by_name(self, name: str, timeout: int = 10) -> None:
        """Stop and remove a container by its name."""
        from docker.errors import NotFound

        try:
            container = self.manager.client.containers.get(name)
            self.manager.stop_container(container.id, timeout)
        except NotFound:
            logger.warn(f"Container {name} not found, may already be stopped")
        except Exception as e:
            logger.error(f"Error stopping container {name}: {e}")

    @keyword("Execute In Container")
    def execute_in_container(
        self,
        container_id: str,
        command: str,
        timeout: int = 30,
        workdir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a command in a running container."""
        return self.manager.execute_command(container_id, command, timeout, workdir)

    @keyword("Wait For Container Port")
    def wait_for_container_port(
        self, container_id: str, port: int, timeout: int = 30
    ) -> bool:
        """Wait for a port to be ready in the container."""
        return self.manager.wait_for_port(container_id, port, timeout)

    @keyword("Copy To Container")
    def copy_to_container(
        self, container_id: str, host_path: str, container_path: str
    ) -> None:
        """Copy files from host to container."""
        self.manager.copy_to_container(container_id, host_path, container_path)

    @keyword("Copy From Container")
    def copy_from_container(
        self, container_id: str, container_path: str, host_path: str
    ) -> None:
        """Copy files from container to host."""
        self.manager.copy_from_container(container_id, container_path, host_path)

    @keyword("Get Container Metrics")
    def get_container_metrics(self, container_id: str) -> Dict[str, Any]:
        """Get resource usage metrics for a container."""
        return self.manager.get_metrics(container_id)

    @keyword("Update Container Resources")
    def update_container_resources(
        self, container_id: str, resources: Dict[str, Any]
    ) -> None:
        """Update resource limits for a running container."""
        res = ContainerResources()
        if "cpu_cores" in resources:
            res.cpu_quota = int(resources["cpu_cores"] * 100000)
        if "memory_mb" in resources:
            res.memory_mb = resources["memory_mb"]
        if "memory_swap_mb" in resources:
            res.memory_swap_mb = resources["memory_swap_mb"]

        self.manager.update_resources(container_id, res)

    @keyword("Cleanup All Containers")
    def cleanup_all_containers(self) -> None:
        """Stop and remove all containers managed by this instance and orphaned rfc-* containers."""
        self.manager.cleanup_all()
        self.manager.cleanup_orphaned()
        self._container_configs.clear()

    @keyword("Create Code Execution Container")
    def create_code_execution_container(
        self,
        image: str = "python:3.11-slim",
        cpu_cores: float = 0.5,
        memory_mb: int = 512,
        network_mode: str = "none",
        timeout: int = 30,
    ) -> str:
        """Create a pre-configured container with sensible defaults for untrusted code."""
        config = {
            "image": image,
            "command": "sleep infinity",
            "cpu_cores": cpu_cores,
            "memory_mb": memory_mb,
            "network_mode": network_mode,
            "read_only": True,
            "user": "nobody",
            "working_dir": "/workspace",
        }
        return self.create_configurable_container(config)

    @keyword("Execute Python In Container")
    def execute_python_in_container(
        self,
        code: str,
        container_id: Optional[str] = None,
        image: str = "python:3.11-slim",
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Execute Python code in a Docker container (creates a temporary one if none given)."""
        cleanup = False
        if container_id is None:
            config = {
                "image": image,
                "command": "sleep infinity",
                "cpu_cores": 0.5,
                "memory_mb": 512,
                "network_mode": "none",
            }
            container_id = self.create_configurable_container(config)
            cleanup = True

        try:
            # Escape the code for shell execution
            escaped_code = code.replace("'", "'\"'\"'")
            command = f"python3 -c '{escaped_code}'"

            result = self.execute_in_container(container_id, command, timeout)
            return result
        finally:
            if cleanup:
                self.stop_container(container_id)
