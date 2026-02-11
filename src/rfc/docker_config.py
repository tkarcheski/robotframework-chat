"""Docker container configuration models."""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any


@dataclass
class ContainerResources:
    """Container resource limits."""

    cpu_cores: Optional[float] = None
    cpu_shares: Optional[int] = None
    cpu_quota: Optional[int] = None
    cpu_period: Optional[int] = 100000
    memory_mb: Optional[int] = None
    memory_swap_mb: Optional[int] = None
    scratch_mb: Optional[int] = None
    shm_size_mb: Optional[int] = None

    def to_docker_resources(self) -> Dict[str, Any]:
        """Convert to Docker SDK resources format."""
        resources = {}

        if self.memory_mb:
            resources["mem_limit"] = f"{self.memory_mb}m"
        if self.memory_swap_mb is not None:
            resources["memswap_limit"] = (
                f"{self.memory_swap_mb}m" if self.memory_swap_mb > 0 else -1
            )
        if self.cpu_shares:
            resources["cpu_shares"] = self.cpu_shares
        if self.cpu_quota and self.cpu_period:
            resources["cpu_quota"] = self.cpu_quota
            resources["cpu_period"] = self.cpu_period
        if self.shm_size_mb:
            resources["shm_size"] = f"{self.shm_size_mb}m"

        return resources


@dataclass
class ContainerNetwork:
    """Network configuration."""

    mode: str = "none"
    ports: Optional[Dict[str, str]] = None
    dns: Optional[List[str]] = None
    aliases: Optional[List[str]] = None

    def to_docker_network(self) -> Dict[str, Any]:
        """Convert to Docker SDK network format."""
        config = {}

        if self.mode == "none":
            config["network_mode"] = "none"
        elif self.mode == "host":
            config["network_mode"] = "host"
        elif self.mode == "bridge":
            config["network_disabled"] = False
            if self.ports:
                config["ports"] = self.ports
            if self.dns:
                config["dns"] = self.dns

        return config


@dataclass
class ContainerConfig:
    """Complete container configuration."""

    image: str
    name: Optional[str] = None
    command: Optional[str] = None
    resources: ContainerResources = field(default_factory=ContainerResources)
    network: ContainerNetwork = field(default_factory=ContainerNetwork)
    volumes: Optional[Dict[str, Dict]] = None
    env: Optional[Dict[str, str]] = None
    labels: Optional[Dict[str, str]] = None
    read_only: bool = True
    user: Optional[str] = "nobody"
    working_dir: Optional[str] = "/workspace"
    auto_remove: bool = True
    detach: bool = True

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "ContainerConfig":
        """Create ContainerConfig from dictionary."""
        resources_dict = config_dict.pop("resources", {})
        network_dict = config_dict.pop("network", {})

        resources = (
            ContainerResources(**resources_dict)
            if resources_dict
            else ContainerResources()
        )
        network = (
            ContainerNetwork(**network_dict) if network_dict else ContainerNetwork()
        )

        return cls(resources=resources, network=network, **config_dict)

    def to_docker_run_config(self) -> Dict[str, Any]:
        """Convert to Docker SDK run configuration."""
        config = {
            "image": self.image,
            "command": self.command,
            "name": self.name,
            "read_only": self.read_only,
            "user": self.user,
            "working_dir": self.working_dir,
            "auto_remove": self.auto_remove,
            "detach": self.detach,
            "environment": self.env or {},
            "labels": self.labels or {},
            "volumes": self.volumes or {},
        }

        # Add resource limits
        config.update(self.resources.to_docker_resources())

        # Add network configuration
        config.update(self.network.to_docker_network())

        return {k: v for k, v in config.items() if v is not None}
