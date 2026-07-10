"""Docker container configuration models."""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Union


def normalize_volumes(
    volumes: Optional[Union[Dict[str, Any], List[str]]],
) -> Union[Dict[str, Dict[str, str]], List[str]]:
    """Normalize a ``volumes`` spec into a shape docker-py accepts.

    docker-py's ``containers.run(volumes=...)`` accepts either:

    * the **dict** form ``{host: {"bind": "/container", "mode": "rw"}}`` — every
      value MUST be a dict, because docker-py calls ``value.get("bind")`` on it
      (``docker/models/containers.py``), or
    * the **list** form ``["host:/container:rw"]``.

    Robot Framework's ``Create Dictionary`` can only build *str* values inline,
    so suites historically produced ``{host: "/container:rw"}`` (a str value).
    That makes docker-py call ``str.get("bind")`` -> ``AttributeError: 'str'
    object has no attribute 'get'`` and no container is ever created (issue
    #189, which zeroed all execution-suite signal). Accept that str shape here
    and convert each ``"/container:mode"`` value into
    ``{"bind": "/container", "mode": ...}``; pass dict values and the list form
    through unchanged so already-valid specs are never altered.
    """
    if not volumes:
        return {}
    if isinstance(volumes, list):
        return volumes
    normalized: Dict[str, Dict[str, str]] = {}
    for host_path, spec in volumes.items():
        if isinstance(spec, dict):
            normalized[host_path] = spec
        elif isinstance(spec, str):
            bind, _, mode = spec.partition(":")
            normalized[host_path] = {"bind": bind, "mode": mode or "rw"}
        else:
            raise TypeError(
                f"Unsupported volume spec for host path {host_path!r}: "
                f"{spec!r} (expected a str '/container:mode' or a dict "
                "{'bind': '/container', 'mode': 'rw'})"
            )
    return normalized


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
        resources: Dict[str, Any] = {}

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
        config: Dict[str, Any] = {}

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
    volumes: Optional[Union[Dict[str, Any], List[str]]] = None
    env: Optional[Dict[str, str]] = None
    labels: Optional[Dict[str, str]] = None
    read_only: bool = True
    user: Optional[str] = "nobody"
    working_dir: Optional[str] = "/workspace"
    auto_remove: bool = False
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
            "volumes": normalize_volumes(self.volumes),
        }

        # Add resource limits
        config.update(self.resources.to_docker_resources())

        # Add network configuration
        config.update(self.network.to_docker_network())

        return {k: v for k, v in config.items() if v is not None}
