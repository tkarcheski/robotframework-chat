"""Pre-flight checks for the CI pipeline configuration.

These tests validate that config/test_suites.yaml is internally consistent
and that all referenced paths, listeners, and structures are valid *before*
any Robot Framework tests or pipeline generation runs.

If these tests fail, the pipeline would also fail — but these catch the
problem in seconds rather than after a full CI build.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

# Project root: tests/ -> ..
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "test_suites.yaml"


def _load_raw_config() -> dict[str, Any]:
    """Load test_suites.yaml without suite_config.py caching or env overrides."""
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Config file existence and structure
# ---------------------------------------------------------------------------


class TestConfigExists:
    def test_config_file_exists(self) -> None:
        assert _CONFIG_PATH.is_file(), f"Missing config: {_CONFIG_PATH}"

    def test_config_is_valid_yaml(self) -> None:
        cfg = _load_raw_config()
        assert isinstance(cfg, dict), "Config root must be a YAML mapping"


class TestConfigRequiredSections:
    """Every required top-level key must be present."""

    REQUIRED_KEYS = [
        "defaults",
        "nodes",
        "master_models",
        "test_suites",
        "run_all",
        "iq_levels",
        "container_profiles",
        "ci",
        "monitoring",
    ]

    def test_all_required_sections_present(self) -> None:
        cfg = _load_raw_config()
        missing = [k for k in self.REQUIRED_KEYS if k not in cfg]
        assert not missing, f"Missing config sections: {missing}"


class TestDefaultsSection:
    def test_defaults_has_model(self) -> None:
        cfg = _load_raw_config()
        assert "model" in cfg["defaults"], "defaults.model is required"

    def test_defaults_model_is_string(self) -> None:
        cfg = _load_raw_config()
        assert isinstance(cfg["defaults"]["model"], str)

    def test_defaults_has_ollama_endpoint(self) -> None:
        cfg = _load_raw_config()
        assert "ollama_endpoint" in cfg["defaults"]

    def test_defaults_endpoint_looks_like_url(self) -> None:
        cfg = _load_raw_config()
        ep = cfg["defaults"]["ollama_endpoint"]
        assert ep.startswith("http://") or ep.startswith("https://"), (
            f"ollama_endpoint should be a URL, got: {ep}"
        )


# ---------------------------------------------------------------------------
# CI section: listeners and job groups
# ---------------------------------------------------------------------------


class TestCIListeners:
    """Listeners referenced in ci.listeners must be importable."""

    def test_listeners_is_list(self) -> None:
        cfg = _load_raw_config()
        assert isinstance(cfg["ci"]["listeners"], list)

    def test_each_listener_is_importable(self) -> None:
        cfg = _load_raw_config()
        for listener_path in cfg["ci"]["listeners"]:
            module_path, class_name = listener_path.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            assert hasattr(mod, class_name), (
                f"Listener class {class_name} not found in {module_path}"
            )

    def test_each_listener_has_api_version(self) -> None:
        cfg = _load_raw_config()
        for listener_path in cfg["ci"]["listeners"]:
            module_path, class_name = listener_path.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            assert hasattr(cls, "ROBOT_LISTENER_API_VERSION"), (
                f"{listener_path} missing ROBOT_LISTENER_API_VERSION"
            )


class TestCIJobGroups:
    """Every ci.job_groups entry must point to a real directory with .robot files."""

    def test_job_groups_is_dict(self) -> None:
        cfg = _load_raw_config()
        assert isinstance(cfg["ci"]["job_groups"], dict)

    def test_each_job_group_has_path(self) -> None:
        cfg = _load_raw_config()
        for name, defn in cfg["ci"]["job_groups"].items():
            assert "path" in defn, f"Job group '{name}' missing 'path'"

    def test_each_job_group_path_exists(self) -> None:
        cfg = _load_raw_config()
        for name, defn in cfg["ci"]["job_groups"].items():
            full = _PROJECT_ROOT / defn["path"]
            assert full.exists(), f"Job group '{name}' path does not exist: {full}"

    def test_each_job_group_path_contains_robot_files(self) -> None:
        cfg = _load_raw_config()
        for name, defn in cfg["ci"]["job_groups"].items():
            full = _PROJECT_ROOT / defn["path"]
            robot_files = list(full.rglob("*.robot"))
            assert robot_files, f"Job group '{name}' path {full} has no .robot files"

    def test_each_job_group_has_output_dir(self) -> None:
        cfg = _load_raw_config()
        for name, defn in cfg["ci"]["job_groups"].items():
            assert "output_dir" in defn, f"Job group '{name}' missing 'output_dir'"

    def test_job_group_names_are_slug_safe(self) -> None:
        """Job names become CI job IDs — they should not contain spaces or weird chars."""
        cfg = _load_raw_config()
        import re

        for name in cfg["ci"]["job_groups"]:
            assert re.match(r"^[a-z0-9][a-z0-9._-]*$", name), (
                f"Job group name '{name}' is not slug-safe for CI"
            )


# ---------------------------------------------------------------------------
# Test suites section
# ---------------------------------------------------------------------------


class TestSuitesSection:
    """test_suites entries must reference valid Robot Framework paths."""

    def test_test_suites_is_dict(self) -> None:
        cfg = _load_raw_config()
        assert isinstance(cfg["test_suites"], dict)

    def test_each_suite_has_label(self) -> None:
        cfg = _load_raw_config()
        for sid, defn in cfg["test_suites"].items():
            assert "label" in defn, f"Suite '{sid}' missing 'label'"

    def test_each_suite_has_path(self) -> None:
        cfg = _load_raw_config()
        for sid, defn in cfg["test_suites"].items():
            assert "path" in defn, f"Suite '{sid}' missing 'path'"

    def test_each_suite_path_exists(self) -> None:
        cfg = _load_raw_config()
        for sid, defn in cfg["test_suites"].items():
            full = _PROJECT_ROOT / defn["path"]
            assert full.exists(), f"Suite '{sid}' path does not exist: {full}"

    def test_run_all_path_exists(self) -> None:
        cfg = _load_raw_config()
        full = _PROJECT_ROOT / cfg["run_all"]["path"]
        assert full.exists(), f"run_all path does not exist: {full}"


# ---------------------------------------------------------------------------
# Nodes and models
# ---------------------------------------------------------------------------


class TestNodesSection:
    def test_nodes_is_list(self) -> None:
        cfg = _load_raw_config()
        assert isinstance(cfg["nodes"], list)

    def test_each_node_has_hostname(self) -> None:
        cfg = _load_raw_config()
        for i, node in enumerate(cfg["nodes"]):
            assert "hostname" in node, f"Node {i} missing 'hostname'"

    def test_each_node_has_port(self) -> None:
        cfg = _load_raw_config()
        for i, node in enumerate(cfg["nodes"]):
            assert "port" in node, f"Node {i} missing 'port'"
            assert isinstance(node["port"], int), (
                f"Node {i} port must be int, got {type(node['port']).__name__}"
            )


class TestMasterModels:
    def test_master_models_is_list(self) -> None:
        cfg = _load_raw_config()
        assert isinstance(cfg["master_models"], list)

    def test_master_models_not_empty(self) -> None:
        cfg = _load_raw_config()
        assert len(cfg["master_models"]) > 0, "master_models must not be empty"

    def test_master_models_are_strings(self) -> None:
        cfg = _load_raw_config()
        for model in cfg["master_models"]:
            assert isinstance(model, str), f"Model name must be str, got {model!r}"


# ---------------------------------------------------------------------------
# Pipeline generation with real config
# ---------------------------------------------------------------------------


class TestRegularPipelineFromRealConfig:
    """generate_regular() with the real config produces a valid pipeline."""

    def test_pipeline_has_stages(self) -> None:
        from scripts.generate_pipeline import generate_regular

        cfg = _load_raw_config()
        pipeline = generate_regular(cfg)
        assert "stages" in pipeline
        assert "test" in pipeline["stages"]
        assert "report" in pipeline["stages"]

    def test_pipeline_has_one_job_per_group(self) -> None:
        from scripts.generate_pipeline import generate_regular

        cfg = _load_raw_config()
        pipeline = generate_regular(cfg)
        for group_name in cfg["ci"]["job_groups"]:
            assert group_name in pipeline, (
                f"Job group '{group_name}' not in generated pipeline"
            )

    def test_pipeline_jobs_have_required_fields(self) -> None:
        from scripts.generate_pipeline import generate_regular

        cfg = _load_raw_config()
        pipeline = generate_regular(cfg)
        reserved = {"stages", "aggregate-results"}
        for key, job in pipeline.items():
            if key in reserved:
                continue
            assert "stage" in job, f"Job '{key}' missing 'stage'"
            assert "script" in job, f"Job '{key}' missing 'script'"
            assert "variables" in job, f"Job '{key}' missing 'variables'"
            assert "DEFAULT_MODEL" in job["variables"], (
                f"Job '{key}' missing DEFAULT_MODEL variable"
            )

    def test_pipeline_has_aggregate_results(self) -> None:
        from scripts.generate_pipeline import generate_regular

        cfg = _load_raw_config()
        pipeline = generate_regular(cfg)
        assert "aggregate-results" in pipeline
        assert pipeline["aggregate-results"]["stage"] == "report"

    def test_pipeline_serializes_to_valid_yaml(self) -> None:
        from scripts.generate_pipeline import generate_regular

        cfg = _load_raw_config()
        pipeline = generate_regular(cfg)
        output = yaml.dump(pipeline, default_flow_style=False)
        roundtrip = yaml.safe_load(output)
        assert roundtrip == pipeline, "YAML round-trip failed"


class TestDynamicPipelineNoNodes:
    """generate_dynamic() with no discoverable nodes still produces valid YAML."""

    def test_no_nodes_produces_notice_job(self) -> None:
        from scripts.generate_pipeline import generate_dynamic

        cfg = _load_raw_config()
        with patch("scripts.generate_pipeline.discover_nodes", return_value=[]):
            pipeline = generate_dynamic(cfg)
        assert "no-ollama-nodes-found" in pipeline

    def test_no_nodes_pipeline_serializes(self) -> None:
        from scripts.generate_pipeline import generate_dynamic

        cfg = _load_raw_config()
        with patch("scripts.generate_pipeline.discover_nodes", return_value=[]):
            pipeline = generate_dynamic(cfg)
        output = yaml.dump(pipeline, default_flow_style=False)
        roundtrip = yaml.safe_load(output)
        assert roundtrip == pipeline


class TestDynamicPipelineWithNodes:
    """generate_dynamic() with mocked nodes creates jobs for each combination."""

    MOCK_NODES = [
        {"endpoint": "http://host1:11434", "models": ["llama3", "mistral"]},
    ]

    def test_creates_jobs_per_node_model_group(self) -> None:
        from scripts.generate_pipeline import generate_dynamic

        cfg = _load_raw_config()
        with patch(
            "scripts.generate_pipeline.discover_nodes",
            return_value=self.MOCK_NODES,
        ):
            pipeline = generate_dynamic(cfg)
        reserved = {"stages", "aggregate-results"}
        job_keys = [k for k in pipeline if k not in reserved]
        num_groups = len(cfg["ci"]["job_groups"])
        num_models = sum(len(n["models"]) for n in self.MOCK_NODES)
        expected = num_groups * num_models
        assert len(job_keys) == expected, (
            f"Expected {expected} dynamic jobs "
            f"({num_groups} groups * {num_models} models), got {len(job_keys)}"
        )

    def test_dynamic_jobs_have_endpoint_and_model_vars(self) -> None:
        from scripts.generate_pipeline import generate_dynamic

        cfg = _load_raw_config()
        with patch(
            "scripts.generate_pipeline.discover_nodes",
            return_value=self.MOCK_NODES,
        ):
            pipeline = generate_dynamic(cfg)
        reserved = {"stages", "aggregate-results"}
        for key, job in pipeline.items():
            if key in reserved:
                continue
            assert "OLLAMA_ENDPOINT" in job["variables"], (
                f"Dynamic job '{key}' missing OLLAMA_ENDPOINT"
            )
            assert "DEFAULT_MODEL" in job["variables"], (
                f"Dynamic job '{key}' missing DEFAULT_MODEL"
            )


# ---------------------------------------------------------------------------
# suite_config.py accessor smoke tests (with real config, no env overrides)
# ---------------------------------------------------------------------------


class TestSuiteConfigAccessors:
    """Verify suite_config convenience functions return correct types."""

    def setup_method(self) -> None:
        from rfc.suite_config import load_config

        load_config.cache_clear()

    def teardown_method(self) -> None:
        from rfc.suite_config import load_config

        load_config.cache_clear()

    def test_load_config_returns_dict(self) -> None:
        from rfc.suite_config import load_config

        cfg = load_config()
        assert isinstance(cfg, dict)

    def test_defaults_returns_dict(self) -> None:
        from rfc.suite_config import defaults

        assert isinstance(defaults(), dict)

    def test_test_suites_returns_dict(self) -> None:
        from rfc.suite_config import test_suites

        assert isinstance(test_suites(), dict)

    def test_ci_config_returns_dict(self) -> None:
        from rfc.suite_config import ci_config

        assert isinstance(ci_config(), dict)

    def test_iq_levels_returns_list_of_strings(self) -> None:
        from rfc.suite_config import iq_levels

        levels = iq_levels()
        assert isinstance(levels, list)
        assert all(isinstance(v, str) for v in levels)

    def test_nodes_returns_list(self) -> None:
        from rfc.suite_config import nodes

        assert isinstance(nodes(), list)

    def test_master_models_returns_list(self) -> None:
        from rfc.suite_config import master_models

        assert isinstance(master_models(), list)

    def test_default_model_returns_string(self) -> None:
        from rfc.suite_config import default_model

        assert isinstance(default_model(), str)

    def test_container_profiles_returns_dict(self) -> None:
        from rfc.suite_config import container_profiles

        profiles = container_profiles()
        assert isinstance(profiles, dict)
        for pid, info in profiles.items():
            assert "label" in info, f"Profile '{pid}' missing 'label'"
            assert "cpu" in info, f"Profile '{pid}' missing 'cpu'"
            assert "memory_mb" in info, f"Profile '{pid}' missing 'memory_mb'"
