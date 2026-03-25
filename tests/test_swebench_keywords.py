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


def _ok_result(stdout: str = "OK") -> Dict[str, Any]:
    return {"stdout": stdout, "stderr": "", "exit_code": 0, "duration_ms": 100}


def _fail_result(stdout: str = "FAILED") -> Dict[str, Any]:
    return {"stdout": stdout, "stderr": "", "exit_code": 1, "duration_ms": 100}


class TestApplyAndTestPatch:
    @patch("rfc.swebench_keywords.ContainerManager")
    def test_apply_patch_clones_repo_at_base_commit(
        self, mock_cm_cls: MagicMock
    ) -> None:
        """Container must clone instance.repo and checkout base_commit."""
        mock_cm = MagicMock()
        mock_cm_cls.return_value = mock_cm
        mock_cm.create_container.return_value = "container-123"
        mock_cm.execute_command.return_value = _ok_result()

        kw = SWEBenchKeywords()
        instance = _make_instance()
        kw.apply_and_test_patch(instance, "diff --git a/f.py\n+fix\n")

        # Extract all shell commands executed in the container
        exec_calls = mock_cm.execute_command.call_args_list
        commands = [c.args[1] if len(c.args) > 1 else c.kwargs.get("command", "") for c in exec_calls]
        cmd_text = "\n".join(commands)

        # Must install git, clone repo, and checkout base_commit
        assert "git" in cmd_text
        assert "django/django" in cmd_text
        assert "abc123def" in cmd_text

    @patch("rfc.swebench_keywords.ContainerManager")
    def test_apply_patch_applies_test_patch(
        self, mock_cm_cls: MagicMock
    ) -> None:
        """Container must apply instance.test_patch before the LLM patch."""
        mock_cm = MagicMock()
        mock_cm_cls.return_value = mock_cm
        mock_cm.create_container.return_value = "container-123"
        mock_cm.execute_command.return_value = _ok_result()

        kw = SWEBenchKeywords()
        instance = _make_instance()
        kw.apply_and_test_patch(instance, "llm-patch-content")

        exec_calls = mock_cm.execute_command.call_args_list
        commands = [c.args[1] if len(c.args) > 1 else c.kwargs.get("command", "") for c in exec_calls]
        cmd_text = "\n".join(commands)

        # test_patch content must appear (written to container)
        assert "test_patch" in cmd_text or instance.test_patch in cmd_text

    @patch("rfc.swebench_keywords.ContainerManager")
    def test_apply_patch_returns_patch_result(
        self, mock_cm_cls: MagicMock
    ) -> None:
        mock_cm = MagicMock()
        mock_cm_cls.return_value = mock_cm
        mock_cm.create_container.return_value = "container-123"
        mock_cm.execute_command.return_value = _ok_result("OK (5 tests passed)")

        kw = SWEBenchKeywords()
        instance = _make_instance()
        result = kw.apply_and_test_patch(instance, "diff --git a/f.py\n+fix\n")

        assert isinstance(result, PatchResult)
        assert result.passed is True
        assert result.exit_code == 0
        assert "OK" in result.test_output

    @patch("rfc.swebench_keywords.ContainerManager")
    def test_apply_patch_failure(self, mock_cm_cls: MagicMock) -> None:
        """When the final test run fails, result.passed must be False."""
        mock_cm = MagicMock()
        mock_cm_cls.return_value = mock_cm
        mock_cm.create_container.return_value = "container-456"

        # All setup commands succeed, but the final test run fails
        def side_effect(cid: str, cmd: str, **kwargs: Any) -> Dict[str, Any]:
            if "pytest" in cmd:
                return _fail_result("FAILED (2 errors)")
            return _ok_result()

        mock_cm.execute_command.side_effect = side_effect

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
        mock_cm.execute_command.return_value = _ok_result()

        kw = SWEBenchKeywords()
        instance = _make_instance()
        kw.apply_and_test_patch(instance, "patch")

        mock_cm.stop_container.assert_called_once_with("container-789")

    @patch("rfc.swebench_keywords.ContainerManager")
    def test_clone_failure_returns_early(self, mock_cm_cls: MagicMock) -> None:
        """If repo clone fails, return a failed PatchResult immediately."""
        mock_cm = MagicMock()
        mock_cm_cls.return_value = mock_cm
        mock_cm.create_container.return_value = "container-err"

        def side_effect(cid: str, cmd: str, **kwargs: Any) -> Dict[str, Any]:
            if "git clone" in cmd:
                return _fail_result("fatal: repository not found")
            return _ok_result()

        mock_cm.execute_command.side_effect = side_effect

        kw = SWEBenchKeywords()
        instance = _make_instance()
        result = kw.apply_and_test_patch(instance, "patch")

        assert result.passed is False
        assert "clone" in result.test_output.lower() or "repository" in result.test_output.lower()

    @patch("rfc.swebench_keywords.ContainerManager")
    def test_test_patch_failure_returns_early(self, mock_cm_cls: MagicMock) -> None:
        """If SWE-bench test patch fails to apply, return failed PatchResult."""
        mock_cm = MagicMock()
        mock_cm_cls.return_value = mock_cm
        mock_cm.create_container.return_value = "container-tp"

        def side_effect(cid: str, cmd: str, **kwargs: Any) -> Dict[str, Any]:
            if "git apply" in cmd and "test_patch" in cmd:
                return _fail_result("error: patch does not apply")
            return _ok_result()

        mock_cm.execute_command.side_effect = side_effect

        kw = SWEBenchKeywords()
        instance = _make_instance()
        result = kw.apply_and_test_patch(instance, "patch")

        assert result.passed is False
        assert "test patch" in result.test_output.lower() or "patch" in result.test_output.lower()

    @patch("rfc.swebench_keywords.ContainerManager")
    def test_container_uses_root_user(self, mock_cm_cls: MagicMock) -> None:
        """Container must run as root for apt-get and git operations."""
        mock_cm = MagicMock()
        mock_cm_cls.return_value = mock_cm
        mock_cm.create_container.return_value = "container-root"
        mock_cm.execute_command.return_value = _ok_result()

        kw = SWEBenchKeywords()
        instance = _make_instance()
        kw.apply_and_test_patch(instance, "patch")

        config = mock_cm.create_container.call_args[0][0]
        assert config.user == "root"


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
