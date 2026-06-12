"""Tests for scripts/import_hf_benchmark.py (hermetic — no network)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.import_hf_benchmark import (
    BENCHMARKS,
    convert_ifeval_rows,
    fetch_rows,
    write_benchmark_yaml,
)

# A realistic slice of what the HF datasets-server /rows endpoint returns
# for google/IFEval (kwargs is a struct, so unused keys come back as None).
SAMPLE_ROWS = [
    {
        "key": 1000,
        "prompt": "Write a riddle without commas.",
        "instruction_id_list": ["punctuation:no_comma"],
        "kwargs": [{"num_words": None, "relation": None}],
    },
    {
        "key": 1001,
        "prompt": "Write at least 300 words about cats.",
        "instruction_id_list": ["length_constraints:number_words"],
        "kwargs": [{"num_words": 300, "relation": "at least", "letter": None}],
    },
    {
        "key": 1002,
        "prompt": "Unsupported instruction example.",
        "instruction_id_list": ["language:response_language"],
        "kwargs": [{"language": "fr"}],
    },
    {
        "key": 1003,
        "prompt": "Mixed: one supported, one not.",
        "instruction_id_list": [
            "punctuation:no_comma",
            "language:response_language",
        ],
        "kwargs": [{}, {"language": "de"}],
    },
]


class TestConvertIfevalRows:
    def test_filters_unsupported_instructions(self) -> None:
        items = convert_ifeval_rows(SAMPLE_ROWS, limit=50)
        keys = [item["key"] for item in items]
        # 1002 has an unsupported id; 1003 mixes supported + unsupported.
        assert keys == [1000, 1001]

    def test_strips_none_kwargs(self) -> None:
        items = convert_ifeval_rows(SAMPLE_ROWS, limit=50)
        assert items[0]["instructions"][0]["kwargs"] == {}
        assert items[1]["instructions"][0]["kwargs"] == {
            "num_words": 300,
            "relation": "at least",
        }

    def test_respects_limit(self) -> None:
        items = convert_ifeval_rows(SAMPLE_ROWS, limit=1)
        assert len(items) == 1
        assert items[0]["key"] == 1000

    def test_supported_set_matches_keyword_library(self) -> None:
        # The importer must never commit items the verifier cannot grade.
        from rfc.ifeval_keywords import SUPPORTED_INSTRUCTIONS

        spec = BENCHMARKS["ifeval"]
        assert spec.supported_instructions == SUPPORTED_INSTRUCTIONS


class TestWriteBenchmarkYaml:
    def test_round_trip(self, tmp_path: Path) -> None:
        items = convert_ifeval_rows(SAMPLE_ROWS, limit=50)
        out = tmp_path / "ifeval_hf.yaml"
        write_benchmark_yaml(out, "IFEVAL_HF", items, source="google/IFEval")
        loaded = yaml.safe_load(out.read_text())
        assert loaded["IFEVAL_HF"] == items

    def test_header_mentions_source_and_generation(self, tmp_path: Path) -> None:
        out = tmp_path / "ifeval_hf.yaml"
        write_benchmark_yaml(out, "IFEVAL_HF", [], source="google/IFEval")
        text = out.read_text()
        assert "google/IFEval" in text
        assert "Auto-generated" in text


class TestFetchRows:
    @patch("scripts.import_hf_benchmark.PAGE_SIZE", 4)
    @patch("scripts.import_hf_benchmark.requests.get")
    def test_paginates_until_enough_rows(self, mock_get: MagicMock) -> None:
        page = {"rows": [{"row": r} for r in SAMPLE_ROWS]}
        resp = MagicMock()
        resp.json.return_value = page
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        rows = fetch_rows("google/IFEval", "default", "train", max_rows=6)
        assert len(rows) == 6
        assert mock_get.call_count == 2

    @patch("scripts.import_hf_benchmark.requests.get")
    def test_stops_on_short_page(self, mock_get: MagicMock) -> None:
        resp = MagicMock()
        resp.json.return_value = {"rows": [{"row": SAMPLE_ROWS[0]}]}
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        rows = fetch_rows("google/IFEval", "default", "train", max_rows=500)
        assert len(rows) == 1
        assert mock_get.call_count == 1


class TestRegistry:
    def test_ifeval_registered(self) -> None:
        assert "ifeval" in BENCHMARKS
        spec = BENCHMARKS["ifeval"]
        assert spec.dataset == "google/IFEval"
        assert spec.variable_name == "IFEVAL_HF"
        assert spec.license_id == "Apache-2.0"

    def test_unknown_benchmark_is_an_error(self) -> None:
        with pytest.raises(KeyError):
            BENCHMARKS["swebench-lite"]
