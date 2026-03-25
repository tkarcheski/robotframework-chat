"""Unit tests for SWE-bench data models."""

import pytest

from rfc.swebench_models import PatchResult, SWEBenchInstance


# ---------------------------------------------------------------------------
# SWEBenchInstance
# ---------------------------------------------------------------------------


class TestSWEBenchInstance:
    def test_valid_creation(self) -> None:
        inst = SWEBenchInstance(
            instance_id="django__django-11099",
            repo="django/django",
            problem_statement="Fix bug in QuerySet.union()",
            patch="diff --git a/file.py b/file.py\n",
            test_patch="diff --git a/tests/test.py b/tests/test.py\n",
            base_commit="abc123",
            version="3.0",
        )
        assert inst.instance_id == "django__django-11099"
        assert inst.repo == "django/django"
        assert inst.version == "3.0"

    def test_empty_instance_id_raises(self) -> None:
        with pytest.raises(ValueError, match="instance_id"):
            SWEBenchInstance(
                instance_id="",
                repo="django/django",
                problem_statement="Fix bug",
                patch="diff",
                test_patch="diff",
                base_commit="abc",
                version="3.0",
            )

    def test_empty_repo_raises(self) -> None:
        with pytest.raises(ValueError, match="repo"):
            SWEBenchInstance(
                instance_id="django__django-11099",
                repo="",
                problem_statement="Fix bug",
                patch="diff",
                test_patch="diff",
                base_commit="abc",
                version="3.0",
            )

    def test_empty_problem_statement_raises(self) -> None:
        with pytest.raises(ValueError, match="problem_statement"):
            SWEBenchInstance(
                instance_id="django__django-11099",
                repo="django/django",
                problem_statement="",
                patch="diff",
                test_patch="diff",
                base_commit="abc",
                version="3.0",
            )

    def test_to_dict(self) -> None:
        inst = SWEBenchInstance(
            instance_id="django__django-11099",
            repo="django/django",
            problem_statement="Fix bug",
            patch="diff",
            test_patch="test_diff",
            base_commit="abc123",
            version="3.0",
        )
        d = inst.to_dict()
        assert d == {
            "instance_id": "django__django-11099",
            "repo": "django/django",
            "problem_statement": "Fix bug",
            "patch": "diff",
            "test_patch": "test_diff",
            "base_commit": "abc123",
            "version": "3.0",
        }

    def test_from_dict(self) -> None:
        d = {
            "instance_id": "django__django-11099",
            "repo": "django/django",
            "problem_statement": "Fix bug",
            "patch": "diff",
            "test_patch": "test_diff",
            "base_commit": "abc123",
            "version": "3.0",
        }
        inst = SWEBenchInstance.from_dict(d)
        assert inst.instance_id == "django__django-11099"
        assert inst.base_commit == "abc123"

    def test_from_dict_missing_field_raises(self) -> None:
        with pytest.raises(KeyError):
            SWEBenchInstance.from_dict({"instance_id": "x"})

    def test_roundtrip(self) -> None:
        inst = SWEBenchInstance(
            instance_id="django__django-11099",
            repo="django/django",
            problem_statement="Fix bug",
            patch="diff",
            test_patch="test_diff",
            base_commit="abc123",
            version="3.0",
        )
        restored = SWEBenchInstance.from_dict(inst.to_dict())
        assert restored.instance_id == inst.instance_id
        assert restored.repo == inst.repo
        assert restored.problem_statement == inst.problem_statement
        assert restored.patch == inst.patch


# ---------------------------------------------------------------------------
# PatchResult
# ---------------------------------------------------------------------------


class TestPatchResult:
    def test_valid_creation(self) -> None:
        result = PatchResult(
            passed=True,
            test_output="OK (5 tests)",
            exit_code=0,
        )
        assert result.passed is True
        assert result.exit_code == 0

    def test_failed_result(self) -> None:
        result = PatchResult(
            passed=False,
            test_output="FAILED (2 errors)",
            exit_code=1,
        )
        assert result.passed is False
        assert result.exit_code == 1

    def test_invalid_passed_type_raises(self) -> None:
        with pytest.raises(TypeError, match="passed"):
            PatchResult(
                passed="yes",  # type: ignore[arg-type]
                test_output="OK",
                exit_code=0,
            )

    def test_invalid_exit_code_type_raises(self) -> None:
        with pytest.raises(TypeError, match="exit_code"):
            PatchResult(
                passed=True,
                test_output="OK",
                exit_code="0",  # type: ignore[arg-type]
            )

    def test_to_dict(self) -> None:
        result = PatchResult(passed=True, test_output="OK", exit_code=0)
        d = result.to_dict()
        assert d == {
            "passed": True,
            "test_output": "OK",
            "exit_code": 0,
        }

    def test_from_dict(self) -> None:
        d = {"passed": False, "test_output": "FAILED", "exit_code": 1}
        result = PatchResult.from_dict(d)
        assert result.passed is False
        assert result.test_output == "FAILED"
        assert result.exit_code == 1

    def test_roundtrip(self) -> None:
        result = PatchResult(passed=True, test_output="OK (10 tests)", exit_code=0)
        restored = PatchResult.from_dict(result.to_dict())
        assert restored.passed == result.passed
        assert restored.test_output == result.test_output
        assert restored.exit_code == result.exit_code
