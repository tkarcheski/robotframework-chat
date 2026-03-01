"""Tests for the host_info module — collects host identification metrics.

Each test run should record which host executed it, along with hardware
characteristics (OS, CPU, RAM, GPU) so that performance metrics can be
correlated with infrastructure.
"""

from __future__ import annotations

import platform
from unittest.mock import patch

from rfc.host_info import collect_host_info


class TestCollectHostInfo:
    """Unit tests for collect_host_info()."""

    def test_returns_dict(self) -> None:
        """collect_host_info() returns a dictionary."""
        info = collect_host_info()
        assert isinstance(info, dict)

    def test_contains_required_keys(self) -> None:
        """Result contains all mandatory identification fields."""
        info = collect_host_info()
        required = {
            "hostname",
            "os_name",
            "os_version",
            "cpu_arch",
            "cpu_count",
            "total_ram_gb",
        }
        assert required.issubset(info.keys())

    def test_hostname_is_nonempty_string(self) -> None:
        info = collect_host_info()
        assert isinstance(info["hostname"], str)
        assert len(info["hostname"]) > 0

    def test_os_name_matches_platform(self) -> None:
        info = collect_host_info()
        assert info["os_name"] == platform.system()

    def test_os_version_is_string(self) -> None:
        info = collect_host_info()
        assert isinstance(info["os_version"], str)

    def test_cpu_arch_matches_platform(self) -> None:
        info = collect_host_info()
        assert info["cpu_arch"] == platform.machine()

    def test_cpu_count_is_positive_int(self) -> None:
        info = collect_host_info()
        assert isinstance(info["cpu_count"], int)
        assert info["cpu_count"] > 0

    def test_total_ram_gb_is_positive_float(self) -> None:
        info = collect_host_info()
        assert isinstance(info["total_ram_gb"], float)
        assert info["total_ram_gb"] > 0.0

    def test_gpu_info_is_optional_string(self) -> None:
        """gpu_info may be None (no GPU) or a non-empty string."""
        info = collect_host_info()
        gpu = info.get("gpu_info")
        assert gpu is None or (isinstance(gpu, str) and len(gpu) > 0)

    @patch("rfc.host_info.platform")
    def test_uses_platform_node_for_hostname(self, mock_platform) -> None:
        mock_platform.node.return_value = "test-node-42"
        mock_platform.system.return_value = "Linux"
        mock_platform.release.return_value = "5.15.0"
        mock_platform.machine.return_value = "x86_64"
        info = collect_host_info()
        assert info["hostname"] == "test-node-42"

    def test_hostname_override_via_env(self) -> None:
        """RFC_HOSTNAME env var overrides platform.node()."""
        with patch.dict("os.environ", {"RFC_HOSTNAME": "custom-host"}):
            info = collect_host_info()
            assert info["hostname"] == "custom-host"

    def test_result_is_json_serializable(self) -> None:
        """All values must be JSON-serializable for database storage."""
        import json

        info = collect_host_info()
        # Should not raise
        json.dumps(info)
