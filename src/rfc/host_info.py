"""Host identification metrics collection.

Collects hardware and OS information for the machine executing tests
so that performance metrics can be correlated with infrastructure.
Uses only the Python standard library — no external dependencies.

The ``RFC_HOSTNAME`` environment variable overrides ``platform.node()``
for cases where the system hostname is unhelpful (e.g. containerised
CI runners with random hostnames).
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Any, Dict, Optional


def _read_total_ram_gb() -> float:
    """Return total physical RAM in gigabytes.

    Uses ``/proc/meminfo`` on Linux and ``sysctl hw.memsize`` on macOS.
    Returns ``0.0`` if detection fails.
    """
    system = platform.system()

    if system == "Linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        # MemTotal: 16384000 kB
                        kb = int(line.split()[1])
                        return round(kb / (1024 * 1024), 2)
        except (OSError, ValueError, IndexError):
            pass

    elif system == "Darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                mem_bytes = int(result.stdout.strip())
                return round(mem_bytes / (1024**3), 2)
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, OSError):
            pass

    elif system == "Windows":
        try:
            result = subprocess.run(
                ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines():
                    line = line.strip()
                    if line.isdigit():
                        return round(int(line) / (1024**3), 2)
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, OSError):
            pass

    return 0.0


def _detect_gpu() -> Optional[str]:
    """Detect GPU information if available.

    Tries ``nvidia-smi`` for NVIDIA GPUs first, then
    ``system_profiler`` on macOS for Apple Silicon / discrete GPUs.
    Returns ``None`` when no GPU is detected or tools are unavailable.
    """
    # Try NVIDIA
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # Try macOS system_profiler
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("Chipset Model:") or stripped.startswith(
                        "Chip:"
                    ):
                        return stripped.split(":", 1)[1].strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    return None


def collect_host_info() -> Dict[str, Any]:
    """Collect host identification metrics.

    Returns a dictionary with the following keys:

    - ``hostname`` — machine name (overridable via ``RFC_HOSTNAME``)
    - ``os_name`` — operating system (e.g. ``Linux``, ``Darwin``, ``Windows``)
    - ``os_version`` — OS kernel/release version string
    - ``cpu_arch`` — CPU architecture (e.g. ``x86_64``, ``arm64``)
    - ``cpu_count`` — number of logical CPU cores
    - ``total_ram_gb`` — total physical RAM in gigabytes
    - ``gpu_info`` — GPU description or ``None`` if undetected

    All values are JSON-serializable.
    """
    hostname = os.environ.get("RFC_HOSTNAME") or platform.node()
    cpu_count = os.cpu_count() or 1

    info: Dict[str, Any] = {
        "hostname": hostname,
        "os_name": platform.system(),
        "os_version": platform.release(),
        "cpu_arch": platform.machine(),
        "cpu_count": cpu_count,
        "total_ram_gb": _read_total_ram_gb(),
        "gpu_info": _detect_gpu(),
    }
    return info
