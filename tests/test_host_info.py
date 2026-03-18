"""Tests for the host_info module — collects host identification metrics.

Covers all platform-specific branches (Linux, Darwin, Windows) for RAM
detection and GPU detection using monkeypatch instead of mock.patch.
"""

from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path

import pytest

from rfc.host_info import _detect_gpu, _read_total_ram_gb, collect_host_info


class TestCollectHostInfo:
    """Unit tests for collect_host_info()."""

    def test_returns_dict(self) -> None:
        info = collect_host_info()
        assert isinstance(info, dict)

    def test_contains_required_keys(self) -> None:
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
        info = collect_host_info()
        gpu = info.get("gpu_info")
        assert gpu is None or (isinstance(gpu, str) and len(gpu) > 0)

    def test_hostname_override_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RFC_HOSTNAME", "custom-host")
        info = collect_host_info()
        assert info["hostname"] == "custom-host"

    def test_uses_platform_node_for_hostname(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("RFC_HOSTNAME", raising=False)
        monkeypatch.setattr("rfc.host_info.platform.node", lambda: "test-node-42")
        info = collect_host_info()
        assert info["hostname"] == "test-node-42"

    def test_result_is_json_serializable(self) -> None:
        info = collect_host_info()
        json.dumps(info)


# ---------------------------------------------------------------------------
# _read_total_ram_gb — platform-specific branches
# ---------------------------------------------------------------------------


class TestReadTotalRamGb:
    def test_linux_reads_proc_meminfo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rfc.host_info.platform.system", lambda: "Linux")
        meminfo = tmp_path / "meminfo"
        meminfo.write_text("MemTotal:       16384000 kB\nMemFree:        8000000 kB\n")

        import builtins

        _real_open = builtins.open

        def patched_open(path: object, *a: object, **kw: object) -> object:
            if str(path) == "/proc/meminfo":
                return _real_open(str(meminfo), *a, **kw)  # type: ignore[call-overload]
            return _real_open(path, *a, **kw)  # type: ignore[call-overload]

        monkeypatch.setattr("builtins.open", patched_open)
        result = _read_total_ram_gb()
        assert result == round(16384000 / (1024 * 1024), 2)

    def test_linux_meminfo_missing_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rfc.host_info.platform.system", lambda: "Linux")

        import builtins

        _real_open = builtins.open

        def patched_open(path: object, *a: object, **kw: object) -> object:
            if str(path) == "/proc/meminfo":
                raise OSError("not found")
            return _real_open(path, *a, **kw)  # type: ignore[call-overload]

        monkeypatch.setattr("builtins.open", patched_open)
        assert _read_total_ram_gb() == 0.0

    def test_darwin_sysctl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rfc.host_info.platform.system", lambda: "Darwin")
        mem_bytes = 17179869184  # 16 GB

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if cmd == ["sysctl", "-n", "hw.memsize"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=str(mem_bytes), stderr=""
                )
            # Fallback for nvidia-smi calls from _detect_gpu path
            raise FileNotFoundError()

        monkeypatch.setattr("rfc.host_info.subprocess.run", fake_run)
        result = _read_total_ram_gb()
        assert result == round(mem_bytes / (1024**3), 2)

    def test_darwin_sysctl_fails_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rfc.host_info.platform.system", lambda: "Darwin")

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError()

        monkeypatch.setattr("rfc.host_info.subprocess.run", fake_run)
        assert _read_total_ram_gb() == 0.0

    def test_windows_wmic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rfc.host_info.platform.system", lambda: "Windows")
        mem_bytes = 17179869184  # 16 GB

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if cmd[0] == "wmic":
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=f"TotalPhysicalMemory\n{mem_bytes}\n", stderr=""
                )
            raise FileNotFoundError()

        monkeypatch.setattr("rfc.host_info.subprocess.run", fake_run)
        result = _read_total_ram_gb()
        assert result == round(mem_bytes / (1024**3), 2)

    def test_windows_wmic_fails_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rfc.host_info.platform.system", lambda: "Windows")

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError()

        monkeypatch.setattr("rfc.host_info.subprocess.run", fake_run)
        assert _read_total_ram_gb() == 0.0

    def test_windows_wmic_nonzero_rc_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rfc.host_info.platform.system", lambda: "Windows")

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="error")

        monkeypatch.setattr("rfc.host_info.subprocess.run", fake_run)
        assert _read_total_ram_gb() == 0.0

    def test_unknown_platform_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rfc.host_info.platform.system", lambda: "FreeBSD")
        assert _read_total_ram_gb() == 0.0


# ---------------------------------------------------------------------------
# _detect_gpu
# ---------------------------------------------------------------------------


class TestDetectGpu:
    def test_nvidia_smi_returns_gpu_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if "nvidia-smi" in cmd:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="NVIDIA RTX 4090, 24576 MiB", stderr=""
                )
            raise FileNotFoundError()

        monkeypatch.setattr("rfc.host_info.subprocess.run", fake_run)
        result = _detect_gpu()
        assert result is not None
        assert "RTX 4090" in result

    def test_nvidia_smi_not_found_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rfc.host_info.platform.system", lambda: "Linux")

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError()

        monkeypatch.setattr("rfc.host_info.subprocess.run", fake_run)
        assert _detect_gpu() is None

    def test_macos_system_profiler(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rfc.host_info.platform.system", lambda: "Darwin")

        call_count = 0

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            if "nvidia-smi" in cmd:
                raise FileNotFoundError()
            if "system_profiler" in cmd:
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout="      Chipset Model: Apple M2 Max\n      Total VRAM: 96 GB\n",
                    stderr="",
                )
            raise FileNotFoundError()

        monkeypatch.setattr("rfc.host_info.subprocess.run", fake_run)
        result = _detect_gpu()
        assert result is not None
        assert "Apple M2 Max" in result

    def test_macos_chip_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rfc.host_info.platform.system", lambda: "Darwin")

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if "nvidia-smi" in cmd:
                raise FileNotFoundError()
            if "system_profiler" in cmd:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="      Chip: Apple M1\n", stderr=""
                )
            raise FileNotFoundError()

        monkeypatch.setattr("rfc.host_info.subprocess.run", fake_run)
        result = _detect_gpu()
        assert result == "Apple M1"

    def test_macos_system_profiler_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rfc.host_info.platform.system", lambda: "Darwin")

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError()

        monkeypatch.setattr("rfc.host_info.subprocess.run", fake_run)
        assert _detect_gpu() is None

    def test_nvidia_smi_empty_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rfc.host_info.platform.system", lambda: "Linux")

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if "nvidia-smi" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            raise FileNotFoundError()

        monkeypatch.setattr("rfc.host_info.subprocess.run", fake_run)
        assert _detect_gpu() is None

    def test_nvidia_smi_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rfc.host_info.platform.system", lambda: "Linux")

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(cmd, 10)

        monkeypatch.setattr("rfc.host_info.subprocess.run", fake_run)
        assert _detect_gpu() is None
