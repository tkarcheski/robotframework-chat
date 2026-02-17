"""Tests for scripts/query_results.py — database query commands."""

from unittest.mock import MagicMock

from scripts.query_results import (
    cmd_compare,
    cmd_export,
    cmd_history,
    cmd_performance,
    cmd_recent,
    print_table,
)


class TestPrintTable:
    def test_basic_table(self, capsys):
        print_table(["Name", "Value"], [["a", "1"], ["bb", "22"]])
        out = capsys.readouterr().out
        assert "Name" in out
        assert "Value" in out
        assert "a" in out
        assert "22" in out

    def test_empty_rows(self, capsys):
        print_table(["A", "B"], [])
        out = capsys.readouterr().out
        assert "A" in out
        assert "---" in out

    def test_column_width_adapts(self, capsys):
        print_table(["X"], [["very long cell content"]])
        out = capsys.readouterr().out
        assert "very long cell content" in out


class TestCmdPerformance:
    def test_no_data(self, capsys):
        db = MagicMock()
        db.get_model_performance.return_value = []
        args = MagicMock()
        args.model = None
        cmd_performance(db, args)
        assert "No test data found" in capsys.readouterr().out

    def test_with_data(self, capsys):
        db = MagicMock()
        db.get_model_performance.return_value = [
            {
                "model_name": "llama3",
                "total_runs": 5,
                "avg_pass_rate": 85.0,
                "total_passed": 42,
                "total_failed": 8,
                "avg_duration": 120.5,
            }
        ]
        args = MagicMock()
        args.model = "llama3"
        cmd_performance(db, args)
        out = capsys.readouterr().out
        assert "llama3" in out
        assert "85.0%" in out


class TestCmdRecent:
    def test_no_runs(self, capsys):
        db = MagicMock()
        db.get_recent_runs.return_value = []
        args = MagicMock()
        args.limit = 10
        cmd_recent(db, args)
        assert "No test runs found" in capsys.readouterr().out

    def test_with_runs(self, capsys):
        db = MagicMock()
        db.get_recent_runs.return_value = [
            {
                "id": 1,
                "timestamp": "2024-01-01T12:00:00.000",
                "model_name": "llama3",
                "test_suite": "math",
                "passed": 8,
                "failed": 2,
                "skipped": 0,
                "git_commit": "abc12345",
            }
        ]
        args = MagicMock()
        args.limit = 10
        cmd_recent(db, args)
        out = capsys.readouterr().out
        assert "llama3" in out
        assert "math" in out


class TestCmdHistory:
    def test_no_history(self, capsys):
        db = MagicMock()
        db.get_test_history.return_value = []
        args = MagicMock()
        args.test_name = "my_test"
        cmd_history(db, args)
        assert "No history found" in capsys.readouterr().out

    def test_with_history(self, capsys):
        db = MagicMock()
        db.get_test_history.return_value = [
            {
                "timestamp": "2024-01-01T12:00:00.000",
                "model_name": "llama3",
                "test_status": "PASS",
                "score": 0.95,
            }
        ]
        args = MagicMock()
        args.test_name = "addition"
        cmd_history(db, args)
        out = capsys.readouterr().out
        assert "addition" in out
        assert "PASS" in out

    def test_history_null_score(self, capsys):
        db = MagicMock()
        db.get_test_history.return_value = [
            {
                "timestamp": "2024-01-01T12:00:00.000",
                "model_name": "llama3",
                "test_status": "FAIL",
                "score": None,
            }
        ]
        args = MagicMock()
        args.test_name = "test1"
        cmd_history(db, args)
        assert "N/A" in capsys.readouterr().out


class TestCmdCompare:
    def test_fewer_than_two_models(self, capsys):
        db = MagicMock()
        db.get_model_performance.return_value = [
            {"model_name": "llama3", "avg_pass_rate": 90}
        ]
        args = MagicMock()
        cmd_compare(db, args)
        assert "Need at least 2 models" in capsys.readouterr().out

    def test_comparison(self, capsys):
        db = MagicMock()
        db.get_model_performance.return_value = [
            {
                "model_name": "llama3",
                "avg_pass_rate": 90.0,
                "total_passed": 45,
                "total_failed": 5,
            },
            {
                "model_name": "mistral",
                "avg_pass_rate": 80.0,
                "total_passed": 40,
                "total_failed": 10,
            },
        ]
        args = MagicMock()
        cmd_compare(db, args)
        out = capsys.readouterr().out
        assert "Best Performing: llama3" in out
        assert "mistral" in out


class TestCmdExport:
    def test_export(self, capsys):
        db = MagicMock()
        args = MagicMock()
        args.output = "/tmp/test_export.json"
        cmd_export(db, args)
        db.export_to_json.assert_called_once_with("/tmp/test_export.json")
        assert "Exported" in capsys.readouterr().out
