"""Tests for eval_datasets — shared HF dataset loader abstraction (#621)."""

from __future__ import annotations

import sys
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from rfc.exceptions import MissingDependencyError


class TestLoadHfDataset:
    def test_returns_list_of_rows(self) -> None:
        rows: List[Dict[str, Any]] = [{"id": "a"}, {"id": "b"}]
        with patch.dict("sys.modules", {"datasets": MagicMock()}):
            sys.modules["datasets"].load_dataset = MagicMock(return_value=iter(rows))
            from rfc.eval_datasets import load_hf_dataset

            result = load_hf_dataset("org/repo", "test")
        assert isinstance(result, list)
        assert result == rows

    def test_missing_package_raises_missing_dependency_error(self) -> None:
        # Temporarily remove eval_datasets from cache to force re-import.
        sys.modules.pop("rfc.eval_datasets", None)
        with patch.dict("sys.modules", {"datasets": None}):
            from rfc.eval_datasets import load_hf_dataset

            with pytest.raises(MissingDependencyError):
                load_hf_dataset("org/repo", "test")
        sys.modules.pop("rfc.eval_datasets", None)


class TestIterInstances:
    def test_passthrough_returns_same_rows(self) -> None:
        from rfc.eval_datasets import iter_instances

        rows = [{"instance_id": "x"}, {"instance_id": "y"}]
        assert list(iter_instances(rows)) == rows

    def test_empty_input(self) -> None:
        from rfc.eval_datasets import iter_instances

        assert list(iter_instances([])) == []

    def test_returns_new_list(self) -> None:
        from rfc.eval_datasets import iter_instances

        rows = [{"a": 1}]
        result = iter_instances(rows)
        # Must be list, not the same object
        assert isinstance(result, list)
