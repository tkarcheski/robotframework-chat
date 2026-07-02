"""Tests for rfc.eval_datasets — the generic HuggingFace dataset loader.

Every test MOCKS ``datasets.load_dataset`` (via the module-level import shim)
so the suite never touches the network or downloads a dataset, exactly as the
swebench loader tests do (#621).
"""

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from rfc.eval_datasets import iter_instances, load_hf_dataset
from rfc.exceptions import MissingDependencyError

_ROW_A: Dict[str, Any] = {
    "instance_id": "ds__case-1",
    "problem_statement": "first",
    "answer": "alpha",
}
_ROW_B: Dict[str, Any] = {
    "instance_id": "ds__case-2",
    "problem_statement": "second",
    "answer": "beta",
}


# ---------------------------------------------------------------------------
# load_hf_dataset
# ---------------------------------------------------------------------------


class TestLoadHfDataset:
    @patch("rfc.eval_datasets._import_load_dataset")
    def test_returns_list_of_rows(self, mock_import: MagicMock) -> None:
        inner = MagicMock(return_value=[_ROW_A, _ROW_B])
        mock_import.return_value = inner
        rows = load_hf_dataset("some/repo", split="test")
        assert rows == [_ROW_A, _ROW_B]
        inner.assert_called_once()

    @patch("rfc.eval_datasets._import_load_dataset")
    def test_passes_repo_and_split(self, mock_import: MagicMock) -> None:
        inner = MagicMock(return_value=[_ROW_A])
        mock_import.return_value = inner
        load_hf_dataset("princeton-nlp/SWE-bench", split="dev")
        _, kwargs = inner.call_args
        args = inner.call_args[0]
        assert args[0] == "princeton-nlp/SWE-bench"
        assert kwargs.get("split") == "dev"

    @patch("rfc.eval_datasets._import_load_dataset")
    def test_max_instances_truncates(self, mock_import: MagicMock) -> None:
        mock_import.return_value = MagicMock(return_value=[_ROW_A] * 50)
        rows = load_hf_dataset("r", split="test", max_instances=5)
        assert len(rows) == 5

    @patch("rfc.eval_datasets._import_load_dataset")
    def test_max_instances_none_returns_all(self, mock_import: MagicMock) -> None:
        mock_import.return_value = MagicMock(return_value=[_ROW_A] * 7)
        rows = load_hf_dataset("r", split="test", max_instances=None)
        assert len(rows) == 7

    @patch("rfc.eval_datasets._import_load_dataset")
    def test_zero_max_returns_empty(self, mock_import: MagicMock) -> None:
        mock_import.return_value = MagicMock(return_value=[_ROW_A] * 10)
        rows = load_hf_dataset("r", split="test", max_instances=0)
        assert rows == []

    @patch("rfc.eval_datasets._import_load_dataset")
    def test_cache_dir_forwarded(self, mock_import: MagicMock) -> None:
        inner = MagicMock(return_value=[_ROW_A])
        mock_import.return_value = inner
        load_hf_dataset("r", split="test", cache_dir="/tmp/hf-cache")
        assert inner.call_args.kwargs.get("cache_dir") == "/tmp/hf-cache"

    @patch("rfc.eval_datasets._import_load_dataset")
    def test_no_cache_dir_not_forwarded(self, mock_import: MagicMock) -> None:
        # When no cache_dir is given we must not pass cache_dir=None, which
        # some datasets versions reject; the kwarg should be absent entirely.
        inner = MagicMock(return_value=[_ROW_A])
        mock_import.return_value = inner
        load_hf_dataset("r", split="test")
        assert "cache_dir" not in inner.call_args.kwargs

    @patch("rfc.eval_datasets._import_load_dataset")
    def test_deterministic_sampling_seed(self, mock_import: MagicMock) -> None:
        # With a seed and a smaller max than the dataset, the same seed must
        # select the same subset across calls (deterministic sampling).
        full = [
            {"instance_id": f"case-{i}", "v": i} for i in range(20)
        ]
        mock_import.return_value = MagicMock(return_value=list(full))
        first = load_hf_dataset("r", split="test", max_instances=5, seed=42)
        mock_import.return_value = MagicMock(return_value=list(full))
        second = load_hf_dataset("r", split="test", max_instances=5, seed=42)
        assert first == second
        assert len(first) == 5

    @patch("rfc.eval_datasets._import_load_dataset")
    def test_seed_subset_differs_from_head(self, mock_import: MagicMock) -> None:
        # A seeded sample should generally not equal the naive head slice,
        # proving sampling actually happens rather than truncation.
        full = [{"instance_id": f"case-{i}", "v": i} for i in range(100)]
        mock_import.return_value = MagicMock(return_value=list(full))
        sampled = load_hf_dataset("r", split="test", max_instances=10, seed=7)
        head = full[:10]
        assert sampled != head

    def test_missing_datasets_raises_skip_error(self) -> None:
        # When the optional ``datasets`` package is absent, the loader must
        # raise MissingDependencyError (an RFCSkipError) — never ImportError.
        with patch(
            "rfc.eval_datasets._import_load_dataset",
            side_effect=MissingDependencyError(package="datasets"),
        ):
            with pytest.raises(MissingDependencyError):
                load_hf_dataset("r", split="test")

    @patch("rfc.eval_datasets._import_load_dataset")
    def test_does_not_download_in_tests(self, mock_import: MagicMock) -> None:
        # Guard: the real datasets.load_dataset must never be invoked here.
        inner = MagicMock(return_value=[_ROW_A])
        mock_import.return_value = inner
        load_hf_dataset("r", split="test")
        # _import_load_dataset is the only seam; if it is mocked, no network.
        mock_import.assert_called_once()


# ---------------------------------------------------------------------------
# iter_instances
# ---------------------------------------------------------------------------


class TestIterInstances:
    def test_yields_normalized_dicts(self) -> None:
        out = list(iter_instances([_ROW_A, _ROW_B]))
        assert len(out) == 2
        assert out[0]["instance_id"] == "ds__case-1"
        assert out[1]["instance_id"] == "ds__case-2"

    def test_guarantees_instance_id_when_present(self) -> None:
        out = list(iter_instances([{"instance_id": "x", "q": "?"}]))
        assert out[0]["instance_id"] == "x"

    def test_synthesizes_instance_id_when_missing(self) -> None:
        # A row without instance_id must still get a guaranteed, stable id
        # rather than KeyError-ing downstream.
        rows: List[Dict[str, Any]] = [{"q": "no id here"}, {"q": "still none"}]
        out = list(iter_instances(rows))
        ids = [r["instance_id"] for r in out]
        assert all(i for i in ids)  # non-empty
        assert len(set(ids)) == 2  # unique

    def test_alternate_id_field(self) -> None:
        rows = [{"task_id": "t-99", "q": "?"}]
        out = list(iter_instances(rows, id_field="task_id"))
        assert out[0]["instance_id"] == "t-99"

    def test_fields_projection_keeps_only_requested(self) -> None:
        rows = [{"instance_id": "a", "keep": 1, "drop": 2}]
        out = list(iter_instances(rows, fields=("keep",)))
        assert out[0]["keep"] == 1
        assert "drop" not in out[0]
        # instance_id is always retained even if not in fields.
        assert out[0]["instance_id"] == "a"

    def test_empty_input_yields_nothing(self) -> None:
        assert list(iter_instances([])) == []
