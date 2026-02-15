"""Shared pytest fixtures for the robotframework-chat test suite."""

import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch


@pytest.fixture(scope="session", autouse=True)
def _load_dotenv():
    """Load .env as default env vars (won't override existing vars or test patches)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.is_file():
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)


@pytest.fixture
def mock_suite_config():
    """Patch suite_config.load_config to avoid needing config/test_suites.yaml."""
    config_data = {
        "defaults": {
            "model": "llama3",
            "iq_levels": ["100", "110"],
            "profile": "STANDARD",
        },
        "test_suites": {
            "math": {"label": "Math Tests", "path": "robot/math/tests"},
        },
        "iq_levels": ["100", "110", "120"],
        "container_profiles": {
            "STANDARD": {"label": "Standard", "cpu": 0.5, "memory_mb": 512},
        },
        "nodes": [{"hostname": "localhost", "port": 11434}],
        "master_models": ["llama3"],
        "run_all": {"label": "Run All", "path": "robot"},
        "ci": {"listeners": []},
        "monitoring": {"poll_interval_seconds": 30, "history_hours": 24},
    }
    with patch("rfc.suite_config.load_config") as mock_load:
        mock_load.return_value = config_data
        from rfc.suite_config import load_config

        load_config.cache_clear()
        yield mock_load
        load_config.cache_clear()


@pytest.fixture
def mock_ollama_client():
    """Pre-configured mock OllamaClient."""
    client = MagicMock()
    client.generate.return_value = "mocked response"
    client.list_models.return_value = ["llama3", "mistral"]
    client.list_models_detailed.return_value = [
        {
            "name": "llama3",
            "size": 1000,
            "modified_at": "2024-01-01",
            "digest": "abc123",
        }
    ]
    client.is_available.return_value = True
    client.is_busy.return_value = False
    client.running_models.return_value = []
    return client


@pytest.fixture
def fresh_session_manager():
    """Return a fresh SessionManager with no sessions, patching suite_config."""
    from dashboard.core.session_manager import SessionManager

    with (
        patch(
            "dashboard.core.session_manager.test_suites",
            return_value={"math": {"path": "robot/math/tests"}},
        ),
        patch(
            "dashboard.core.session_manager.default_iq_levels",
            return_value=["100"],
        ),
        patch(
            "dashboard.core.session_manager.default_model",
            return_value="llama3",
        ),
        patch(
            "dashboard.core.session_manager.default_profile",
            return_value="STANDARD",
        ),
    ):
        yield SessionManager()


@pytest.fixture
def sample_session(fresh_session_manager):
    """A SessionManager with one pre-created session."""
    session = fresh_session_manager.create_session()
    return fresh_session_manager, session


@pytest.fixture
def tmp_db(tmp_path):
    """SQLite TestDatabase in a temporary directory."""
    from rfc.test_database import TestDatabase

    db_path = str(tmp_path / "test.db")
    return TestDatabase(db_path=db_path)


@pytest.fixture
def sample_test_run():
    """A valid TestRun dataclass instance for testing."""
    from rfc.test_database import TestRun

    return TestRun(
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        model_name="llama3",
        model_release_date="2024-01-01",
        model_parameters="8B",
        test_suite="math",
        git_commit="abc123",
        git_branch="main",
        pipeline_url="",
        runner_id="",
        runner_tags="",
        total_tests=10,
        passed=8,
        failed=2,
        skipped=0,
        duration_seconds=120.5,
    )
