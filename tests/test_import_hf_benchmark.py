"""Tests for scripts/import_hf_benchmark.py (hermetic — no network)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.import_hf_benchmark import (
    BENCHMARKS,
    MAX_FUNC_CHARS,
    convert_defect_detection_rows,
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


# ---------------------------------------------------------------------------
# Code review defect detection (google/code_x_glue_cc_defect_detection)
# ---------------------------------------------------------------------------

# A realistic slice of what the datasets-server returns for the Devign
# defect-detection dataset (CodeXGLUE).  target=True means vulnerable.
DEFECT_ROWS = [
    {
        "id": 1,
        "func": "int a() { return 1; }",
        "target": True,
        "project": "FFmpeg",
        "commit_id": "aaa",
    },
    {
        "id": 2,
        "func": "int b() { return 2; }",
        "target": False,
        "project": "FFmpeg",
        "commit_id": "bbb",
    },
    {
        "id": 3,
        "func": "int c() { return 3; }",
        "target": True,
        "project": "QEMU",
        "commit_id": "ccc",
    },
    {
        "id": 4,
        "func": "x" * 50_000,
        "target": False,
        "project": "QEMU",
        "commit_id": "ddd",
    },  # too long — filtered out
    {
        "id": 5,
        "func": "int e() { return 5; }",
        "target": False,
        "project": "QEMU",
        "commit_id": "eee",
    },
    {
        "id": 6,
        "func": "int f() { return 6; }",
        "target": True,
        "project": "FFmpeg",
        "commit_id": "fff",
    },
    {
        "id": 7,
        "func": "int g() { return 7; }",
        "target": False,
        "project": "QEMU",
        "commit_id": "ggg",
    },
]


class TestConvertDefectDetectionRows:
    def test_balanced_and_interleaved(self) -> None:
        items = convert_defect_detection_rows(DEFECT_ROWS, limit=4)
        labels = [item["vulnerable"] for item in items]
        # Strictly balanced and interleaved vulnerable/safe.
        assert labels == [True, False, True, False]
        assert [item["id"] for item in items] == [1, 2, 3, 5]

    def test_filters_oversized_functions(self) -> None:
        items = convert_defect_detection_rows(DEFECT_ROWS, limit=50)
        assert all(len(item["func"]) <= MAX_FUNC_CHARS for item in items)
        assert 4 not in [item["id"] for item in items]

    def test_balance_capped_by_scarcer_class(self) -> None:
        # 3 vulnerable vs 3 safe usable rows -> limit=50 yields 3 of each.
        items = convert_defect_detection_rows(DEFECT_ROWS, limit=50)
        labels = [item["vulnerable"] for item in items]
        assert labels.count(True) == labels.count(False) == 3

    def test_item_shape(self) -> None:
        item = convert_defect_detection_rows(DEFECT_ROWS, limit=2)[0]
        assert set(item) == {"id", "project", "commit_id", "func", "vulnerable"}
        assert isinstance(item["vulnerable"], bool)

    def test_respects_limit(self) -> None:
        assert len(convert_defect_detection_rows(DEFECT_ROWS, limit=2)) == 2

    def test_doubled_newlines_normalised(self) -> None:
        # Devign stores every source line followed by a blank line; the
        # converter recovers the original line structure.
        rows = [
            {
                "id": 9,
                "func": "int h() {\n\n  return 9;\n\n}",
                "target": True,
                "project": "QEMU",
                "commit_id": "hhh",
            },
            {
                "id": 10,
                "func": "int i() { return 10; }",
                "target": False,
                "project": "QEMU",
                "commit_id": "iii",
            },
        ]
        items = convert_defect_detection_rows(rows, limit=2)
        assert items[0]["func"] == "int h() {\n  return 9;\n}"


class TestDefectRegistry:
    def test_code_review_defect_registered(self) -> None:
        assert "code_review_defect" in BENCHMARKS
        spec = BENCHMARKS["code_review_defect"]
        assert spec.dataset == "google/code_x_glue_cc_defect_detection"
        assert spec.variable_name == "CODE_REVIEW_DEFECT_HF"
        assert spec.license_id == "C-UDA-1.0"
        assert str(spec.default_output) == (
            "robot/code_review/variables/defect_detection_hf.yaml"
        )
        assert spec.sampling_note  # sampling strategy documented in YAML header


class TestWriteBenchmarkYamlNote:
    def test_note_lines_rendered_as_comments(self, tmp_path: Path) -> None:
        out = tmp_path / "x.yaml"
        write_benchmark_yaml(out, "X", [], source="d/s", note="line one\nline two")
        text = out.read_text()
        assert "# line one" in text
        assert "# line two" in text
