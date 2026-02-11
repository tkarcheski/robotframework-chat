"""Configurable Docker keywords for Robot Framework."""

import socket
from typing import Dict, Any, Optional
from robot.api import logger
from robot.api.deco import keyword

from .docker_config import ContainerConfig, ContainerResources, ContainerNetwork
from .container_manager import ContainerManager


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
        """Check if Docker daemon is available.

        Returns:
            True if Docker is available, False otherwise
        """
        try:
            from .container_manager import ContainerManager

            ContainerManager()
            return True
        except RuntimeError:
            return False

    @keyword("Find Available Port")
    def find_available_port(
        self, start_port: int = 11434, end_port: int = 11500
    ) -> int:
        """Find an available TCP port in the given range.

        Iterates through ports from start_port to end_port (inclusive)
        and returns the first one that is not in use.

        Args:
            start_port: Starting port number (default: 11434)
            end_port: Ending port number (default: 11500)

        Returns:
            An available port number

        Raises:
            RuntimeError: If no available port is found in the range
        """
        for port in range(start_port, end_port + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                try:
                    sock.bind(("localhost", port))
                    return port
                except OSError:
                    continue

        raise RuntimeError(f"No available port found in range {start_port}-{end_port}")

    @keyword("Create Configurable Container")
    def create_configurable_container(
        self, config: Dict[str, Any], name: Optional[str] = None
    ) -> str:
        """Create a Docker container with full resource configuration.

        Config dictionary supports:
        - image (required): Docker image name
        - cpu_cores: Number of CPU cores (e.g., 0.5, 1.0, 2.0)
        - memory_mb: RAM limit in MB
        - memory_swap_mb: Swap limit in MB (-1 for unlimited)
        - scratch_mb: Ephemeral disk limit
        - network_mode: 'none', 'bridge', or 'host'
        - ports: Dict mapping host port to container port (e.g., {'8080': '8080'})
        - volumes: Dict of host paths to container mounts
        - env: Dict of environment variables
        - read_only: Boolean, default True
        - user: User to run as, default 'nobody'

        Args:
            config: Configuration dictionary
            name: Optional container name

        Returns:
            Container ID string

        Example:
            | ${config}= | Create Dictionary | image=python:3.11-slim |
            | ... | cpu_cores=0.5 | memory_mb=512 | network_mode=none |
            | ${container}= | Create Configurable Container | ${config} | my-container |
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

        # Build container config
        # Helper to convert string booleans to actual booleans
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
            auto_remove=to_bool(config.get("auto_remove"), True),
            detach=to_bool(config.get("detach"), True),
        )

        container_id = self.manager.create_container(container_config, name)
        self._container_configs[container_id] = container_config

        return container_id

    @keyword("Stop Container")
    def stop_container(self, container_id: str, timeout: int = 10) -> None:
        """Stop and remove a container.

        Args:
            container_id: ID of container to stop
            timeout: Seconds to wait for graceful shutdown
        """
        self.manager.stop_container(container_id, timeout)

    @keyword("Stop Container By Name")
    def stop_container_by_name(self, name: str, timeout: int = 10) -> None:
        """Stop and remove a container by its name.

        Args:
            name: Name of container to stop
            timeout: Seconds to wait for graceful shutdown
        """
        import docker
        from docker.errors import NotFound

        try:
            client = docker.from_env()
            container = client.containers.get(name)
            logger.info(f"Stopping container by name: {name}")
            container.stop(timeout=timeout)
            container.remove(force=True)
            logger.info(f"Container {name} stopped and removed")
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
        """Execute a command in a running container.

        Args:
            container_id: ID of container
            command: Command to execute
            timeout: Maximum execution time in seconds
            workdir: Working directory in container

        Returns:
            Dictionary with keys: stdout, stderr, exit_code, duration_ms

        Example:
            | ${result}= | Execute In Container | ${container} | ls -la | timeout=10 |
            | Should Be Equal As Integers | ${result}[exit_code] | 0 |
            | Log | ${result}[stdout] |
        """
        return self.manager.execute_command(container_id, command, timeout, workdir)

    @keyword("Wait For Container Port")
    def wait_for_container_port(
        self, container_id: str, port: int, timeout: int = 30
    ) -> bool:
        """Wait for a port to be ready in the container.

        Args:
            container_id: ID of container
            port: Port number to check
            timeout: Maximum wait time in seconds

        Returns:
            True if port is ready within timeout

        Example:
            | ${ready}= | Wait For Container Port | ${container} | 8080 | timeout=60 |
            | Should Be True | ${ready} |
        """
        return self.manager.wait_for_port(container_id, port, timeout)

    @keyword("Copy To Container")
    def copy_to_container(
        self, container_id: str, host_path: str, container_path: str
    ) -> None:
        """Copy files from host to container.

        Args:
            container_id: ID of container
            host_path: Source path on host
            container_path: Destination path in container
        """
        self.manager.copy_to_container(container_id, host_path, container_path)

    @keyword("Copy From Container")
    def copy_from_container(
        self, container_id: str, container_path: str, host_path: str
    ) -> None:
        """Copy files from container to host.

        Args:
            container_id: ID of container
            container_path: Source path in container
            host_path: Destination path on host
        """
        self.manager.copy_from_container(container_id, container_path, host_path)

    @keyword("Get Container Metrics")
    def get_container_metrics(self, container_id: str) -> Dict[str, Any]:
        """Get resource usage metrics for a container.

        Args:
            container_id: ID of container

        Returns:
            Dictionary with cpu_percent, memory_usage_mb, memory_limit_mb

        Example:
            | ${metrics}= | Get Container Metrics | ${container} |
            | Log | CPU: ${metrics}[cpu_percent]% |
            | Log | Memory: ${metrics}[memory_usage_mb] / ${metrics}[memory_limit_mb] MB |
        """
        return self.manager.get_metrics(container_id)

    @keyword("Update Container Resources")
    def update_container_resources(
        self, container_id: str, resources: Dict[str, Any]
    ) -> None:
        """Update resource limits for a running container.

        Args:
            container_id: ID of container
            resources: Dictionary with cpu_cores, memory_mb, etc.
        """
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
        """Stop and remove all containers managed by this instance."""
        self.manager.cleanup_all()
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
        """Create a pre-configured container for code execution.

        This is a convenience keyword that creates a container with
        sensible defaults for executing untrusted code.

        Args:
            image: Docker image to use
            cpu_cores: CPU cores to allocate
            memory_mb: Memory limit in MB
            network_mode: Network isolation level
            timeout: Not used (for documentation only)

        Returns:
            Container ID

        Example:
            | ${container}= | Create Code Execution Container | python:3.11-slim | 0.5 | 512 |
        """
        config = {
            "image": image,
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
        """Execute Python code in a Docker container.

        If container_id is not provided, a new temporary container will be created.

        Args:
            code: Python code to execute
            container_id: Optional existing container ID
            image: Docker image (if creating new container)
            timeout: Execution timeout in seconds

        Returns:
            Dictionary with stdout, stderr, exit_code, duration_ms

        Example:
            | ${code}= | Set Variable | print('Hello, World!') |
            | ${result}= | Execute Python In Container | ${code} | timeout=10 |
            | Should Contain | ${result}[stdout] | Hello, World! |
        """
        cleanup = False
        if container_id is None:
            # Create temporary container
            config = {
                "image": image,
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
