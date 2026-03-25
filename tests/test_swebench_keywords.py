"""Tests for SWEBenchKeywords — dataset loading, patch testing, result logging.

Uses mocks for external dependencies (datasets, Docker) so tests run
without network access or Docker.
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

from rfc.swebench_keywords import SWEBenchKeywords
from rfc.swebench_models import PatchResult, SWEBenchInstance


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_DATASET_ROW: Dict[str, Any] = {
    "instance_id": "django__django-11099",
    "repo": "django/django",
    "problem_statement": "Fix QuerySet.union() with ordering.",
    "patch": "diff --git a/file.py b/file.py\n-old\n+new\n",
    "test_patch": "diff --git a/tests/test.py b/tests/test.py\n+test\n",
    "base_commit": "abc123def",
    "version": "3.0",
}


def _make_instance(**overrides: Any) -> SWEBenchInstance:
    fields = {**_SAMPLE_DATASET_ROW, **overrides}
    return SWEBenchInstance.from_dict(fields)


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestSWEBenchKeywordsInit:
    def test_instantiation_without_docker(self) -> None:
        """Keywords class must not require Docker at import/init time
        so that Robot --dryrun works."""
        kw = SWEBenchKeywords()
        assert kw is not None


# ---------------------------------------------------------------------------
# Load SWEBench Instances
# ---------------------------------------------------------------------------


class TestLoadInstances:
    @patch("rfc.swebench_keywords._load_dataset")
    def test_load_returns_swebench_instances(
        self, mock_load: MagicMock
    ) -> None:
        mock_load.return_value = [_SAMPLE_DATASET_ROW, _SAMPLE_DATASET_ROW]
        kw = SWEBenchKeywords()
        instances = kw.load_swebench_instances(split="test", max_instances=2)
        assert len(instances) == 2
        assert all(isinstance(i, SWEBenchInstance) for i in instances)
        assert instances[0].instance_id == "django__django-11099"

    @patch("rfc.swebench_keywords._load_dataset")
    def test_load_respects_max_instances(self, mock_load: MagicMock) -> None:
        mock_load.return_value = [_SAMPLE_DATASET_ROW] * 20
        kw = SWEBenchKeywords()
        instances = kw.load_swebench_instances(split="test", max_instances=5)
        assert len(instances) == 5

    @patch("rfc.swebench_keywords._load_dataset")
    def test_load_with_zero_max_returns_empty(
        self, mock_load: MagicMock
    ) -> None:
        mock_load.return_value = [_SAMPLE_DATASET_ROW] * 10
        kw = SWEBenchKeywords()
        instances = kw.load_swebench_instances(split="test", max_instances=0)
        assert instances == []


# ---------------------------------------------------------------------------
# Apply And Test Patch
# ---------------------------------------------------------------------------


class TestApplyAndTestPatch:
    @patch("rfc.swebench_keywords.ContainerManager")
    def test_apply_patch_returns_patch_result(
        self, mock_cm_cls: MagicMock
    ) -> None:
        mock_cm = MagicMock()
        mock_cm_cls.return_value = mock_cm
        mock_cm.create_container.return_value = "container-123"
        mock_cm.execute_command.return_value = {
            "stdout": "OK (5 tests passed)",
            "stderr": "",
            "exit_code": 0,
            "duration_ms": 1234,
        }

        kw = SWEBenchKeywords()
        instance = _make_instance()
        result = kw.apply_and_test_patch(instance, "diff --git a/f.py\n+fix\n")

        assert isinstance(result, PatchResult)
        assert result.passed is True
        assert result.exit_code == 0
        assert "OK" in result.test_output

    @patch("rfc.swebench_keywords.ContainerManager")
    def test_apply_patch_failure(self, mock_cm_cls: MagicMock) -> None:
        mock_cm = MagicMock()
        mock_cm_cls.return_value = mock_cm
        mock_cm.create_container.return_value = "container-456"
        mock_cm.execute_command.return_value = {
            "stdout": "FAILED (2 errors)",
            "stderr": "",
            "exit_code": 1,
            "duration_ms": 2000,
        }

        kw = SWEBenchKeywords()
        instance = _make_instance()
        result = kw.apply_and_test_patch(instance, "bad patch")

        assert isinstance(result, PatchResult)
        assert result.passed is False
        assert result.exit_code == 1

    @patch("rfc.swebench_keywords.ContainerManager")
    def test_apply_patch_cleanup(self, mock_cm_cls: MagicMock) -> None:
        """Container must be stopped after test execution."""
        mock_cm = MagicMock()
        mock_cm_cls.return_value = mock_cm
        mock_cm.create_container.return_value = "container-789"
        mock_cm.execute_command.return_value = {
            "stdout": "OK",
            "stderr": "",
            "exit_code": 0,
            "duration_ms": 100,
        }

        kw = SWEBenchKeywords()
        instance = _make_instance()
        kw.apply_and_test_patch(instance, "patch")

        mock_cm.stop_container.assert_called_once_with("container-789")


# ---------------------------------------------------------------------------
# Log SWEBench Result
# ---------------------------------------------------------------------------


class TestLogSWEBenchResult:
    @patch("rfc.swebench_keywords.emit_rfc_data")
    def test_log_emits_rfc_data(self, mock_emit: MagicMock) -> None:
        kw = SWEBenchKeywords()
        kw.log_swebench_result(
            instance_id="django__django-11099",
            score=1.0,
            patch="diff --git",
            reason="Tests pass",
        )

        calls = {c.args[0]: c.args[1] for c in mock_emit.call_args_list}
        assert calls["swebench_instance_id"] == "django__django-11099"
        assert calls["score"] == "1.0"
        assert calls["swebench_patch"] == "diff --git"
        assert calls["grading_reason"] == "Tests pass"
