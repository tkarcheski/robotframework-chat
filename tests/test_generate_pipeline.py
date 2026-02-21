"""Tests for scripts/generate_pipeline.py — CI pipeline YAML generation."""

from unittest.mock import patch

from scripts.generate_pipeline import (
    _listener_flags,
    _slug,
    generate_regular,
    generate_dynamic,
)


class TestSlug:
    def test_simple_text(self):
        assert _slug("Math Tests") == "math-tests"

    def test_special_chars(self):
        assert _slug("robot/math/tests") == "robot-math-tests"

    def test_leading_trailing_stripped(self):
        assert _slug("  hello world!  ") == "hello-world"

    def test_consecutive_special(self):
        assert _slug("a---b___c") == "a-b-c"


class TestListenerFlags:
    def test_no_listeners(self):
        assert _listener_flags([]) == ""

    def test_one_listener(self):
        assert _listener_flags(["rfc.db_listener.DbListener"]) == (
            "--listener rfc.db_listener.DbListener"
        )

    def test_multiple_listeners(self):
        result = _listener_flags(["Listener1", "Listener2"])
        assert result == "--listener Listener1 --listener Listener2"


class TestGenerateRegular:
    def test_basic_pipeline_structure(self):
        config = {
            "ci": {
                "listeners": ["rfc.db_listener.DbListener"],
                "job_groups": {
                    "math-tests": {
                        "path": "robot/math/tests",
                        "output_dir": "results/math",
                        "tags": ["ollama"],
                    },
                },
            },
            "defaults": {
                "model": "llama3",
                "ollama_endpoint": "http://localhost:11434",
            },
        }
        pipeline = generate_regular(config)

        assert "stages" in pipeline
        assert "test" in pipeline["stages"]
        assert "report" in pipeline["stages"]
        assert "math-tests" in pipeline
        assert pipeline["math-tests"]["stage"] == "test"
        assert pipeline["math-tests"]["variables"]["DEFAULT_MODEL"] == "llama3"

    def test_aggregate_results_job(self):
        config = {
            "ci": {
                "listeners": [],
                "job_groups": {
                    "suite-a": {
                        "path": "robot/a",
                        "output_dir": "results/a",
                    },
                },
            },
            "defaults": {"model": "llama3"},
        }
        pipeline = generate_regular(config)
        assert "aggregate-results" in pipeline
        assert pipeline["aggregate-results"]["stage"] == "report"

    def test_empty_job_groups(self):
        config = {
            "ci": {"listeners": [], "job_groups": {}},
            "defaults": {"model": "llama3"},
        }
        pipeline = generate_regular(config)
        assert "stages" in pipeline
        assert "aggregate-results" in pipeline


class TestGenerateDynamic:
    @patch("scripts.generate_pipeline.discover_nodes", return_value=[])
    def test_no_nodes_returns_notice(self, mock_discover):
        config = {"ci": {"listeners": [], "job_groups": {}}}
        pipeline = generate_dynamic(config)
        assert "no-ollama-nodes-found" in pipeline

    @patch(
        "scripts.generate_pipeline.discover_nodes",
        return_value=[
            {"endpoint": "http://host1:11434", "models": ["llama3"]},
        ],
    )
    def test_generates_jobs_per_node_model(self, mock_discover):
        config = {
            "ci": {
                "listeners": [],
                "job_groups": {
                    "math": {"path": "robot/math", "tags": ["ollama"]},
                },
            },
        }
        pipeline = generate_dynamic(config)

        # Should have at least one dynamic job
        job_keys = [k for k in pipeline if k != "stages"]
        assert len(job_keys) >= 1

        # Check job properties
        job = pipeline[job_keys[0]]
        assert job["stage"] == "test"
        assert job["variables"]["OLLAMA_ENDPOINT"] == "http://host1:11434"
        assert job["variables"]["DEFAULT_MODEL"] == "llama3"

    @patch(
        "scripts.generate_pipeline.discover_nodes",
        return_value=[
            {
                "endpoint": "http://host1:11434",
                "models": ["llama3", "mistral"],
            },
        ],
    )
    def test_multiple_models_per_node(self, mock_discover):
        config = {
            "ci": {
                "listeners": [],
                "job_groups": {
                    "math": {"path": "robot/math", "tags": ["ollama"]},
                },
            },
        }
        pipeline = generate_dynamic(config)
        reserved = {"stages", "aggregate-results"}
        job_keys = [k for k in pipeline if k not in reserved]
        # 2 models * 1 group = 2 test jobs (plus aggregate-results)
        assert len(job_keys) == 2
