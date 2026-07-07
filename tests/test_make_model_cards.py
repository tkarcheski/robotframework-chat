"""Tests for src/rfc/make_model_cards.py — model card generation."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from rfc.make_model_cards import (
    ModelMetrics,
    fetch_model_metadata,
    generate_swot,
    get_distinct_models,
    render_benchmarks_table,
    render_card,
    render_metadata_table,
    slugify,
)
from rfc.ollama import OllamaClient


class TestSlugify:
    """Test model name -> filename slug conversion."""

    def test_qwen_with_dots_and_colon(self) -> None:
        assert slugify("qwen2.5:72b") == "qwen2_5_72b"

    def test_llama_latest(self) -> None:
        assert slugify("llama3.2:latest") == "llama3_2_latest"

    def test_lowercase_conversion(self) -> None:
        assert slugify("MISTRAL:LATEST") == "mistral_latest"

    def test_consecutive_special_chars(self) -> None:
        assert slugify("model:::test") == "model_test"

    def test_leading_trailing_underscores_stripped(self) -> None:
        assert slugify("_model_") == "model"


class TestRenderMetadataTable:
    """Test metadata table rendering."""

    def test_metadata_table_format(self) -> None:
        metadata = {
            "name": "qwen2.5:72b",
            "provider": "Qwen",
            "parameters_b": "72",
            "quantization": "Q4_K_M",
            "context_window": "32768",
        }
        table = render_metadata_table(metadata)

        assert "## Metadata" in table
        assert "| Provider | Qwen |" in table
        assert "| Parameters | 72B |" in table
        assert "| Quantization | Q4_K_M |" in table
        assert "| Context Window | 32768 |" in table

    def test_metadata_table_with_unknown(self) -> None:
        metadata = {
            "name": "unknown",
            "provider": "unknown",
            "parameters_b": "unknown",
            "quantization": "unknown",
            "context_window": "unknown",
        }
        table = render_metadata_table(metadata)

        assert "| Provider | unknown |" in table


class TestRenderBenchmarksTable:
    """Test benchmarks table rendering."""

    def test_benchmarks_table_single_suite(self) -> None:
        metrics = ModelMetrics(
            model_name="test_model",
            total_runs=10,
            total_tests=100,
            passed=85,
            failed=10,
            skipped=5,
            pass_rate_pct=85.0,
            pass_rate_7d_pct=90.0,
            pass_rate_30d_prior_pct=80.0,
            avg_duration_seconds=5.0,
            p50_duration_ms=5000.0,
            p95_duration_ms=8000.0,
            p99_duration_ms=10000.0,
            avg_throughput_tokens_per_sec=20.5,
            suite_metrics={
                "math": {
                    "runs": 5,
                    "passed": 4,
                    "pass_rate_pct": 80.0,
                    "p95_ms": 4500.0,
                }
            },
        )

        table = render_benchmarks_table(metrics)

        assert "## Benchmarks" in table
        assert "| math |" in table
        assert "| 5 |" in table
        assert "| 80.0% |" in table

    def test_benchmarks_table_multiple_suites(self) -> None:
        metrics = ModelMetrics(
            model_name="test_model",
            total_runs=10,
            total_tests=100,
            passed=85,
            failed=10,
            skipped=5,
            pass_rate_pct=85.0,
            pass_rate_7d_pct=None,
            pass_rate_30d_prior_pct=None,
            avg_duration_seconds=5.0,
            p50_duration_ms=5000.0,
            p95_duration_ms=8000.0,
            p99_duration_ms=10000.0,
            avg_throughput_tokens_per_sec=20.5,
            suite_metrics={
                "math": {
                    "runs": 5,
                    "passed": 4,
                    "pass_rate_pct": 80.0,
                    "p95_ms": 4500.0,
                },
                "docker": {
                    "runs": 5,
                    "passed": 5,
                    "pass_rate_pct": 100.0,
                    "p95_ms": 6000.0,
                },
            },
        )

        table = render_benchmarks_table(metrics)

        assert "| docker |" in table
        assert "| math |" in table


class TestRenderCard:
    """Test complete model card rendering."""

    def test_card_contains_all_sections(self) -> None:
        metrics = ModelMetrics(
            model_name="qwen2.5:72b",
            total_runs=5,
            total_tests=50,
            passed=45,
            failed=5,
            skipped=0,
            pass_rate_pct=90.0,
            pass_rate_7d_pct=92.0,
            pass_rate_30d_prior_pct=88.0,
            avg_duration_seconds=4.5,
            p50_duration_ms=4500.0,
            p95_duration_ms=7500.0,
            p99_duration_ms=9500.0,
            avg_throughput_tokens_per_sec=25.0,
            suite_metrics={
                "math": {
                    "runs": 25,
                    "passed": 23,
                    "pass_rate_pct": 92.0,
                    "p95_ms": 7000.0,
                }
            },
        )
        metadata = {
            "name": "qwen2.5:72b",
            "provider": "Qwen",
            "parameters_b": "72",
            "quantization": "Q4_K_M",
            "context_window": "32768",
        }
        swot_text = "### Strengths\n- Fast inference"
        timestamp = "2024-04-25T12:00:00Z"

        card = render_card(metrics, metadata, swot_text, timestamp)

        assert "# Model Card: qwen2.5:72b" in card
        assert "Generated: 2024-04-25T12:00:00Z" in card
        assert "## Metadata" in card
        assert "## Overall Results" in card
        assert "## SWOT Analysis" in card
        assert "### Strengths" in card
        assert "**Total Tests:** 50" in card
        assert "**Pass Rate:** 90.0%" in card
        assert "**Pass Rate Trend (7d vs 30d prior):** ↑ +4.0pp" in card

    def test_card_trend_direction_down(self) -> None:
        metrics = ModelMetrics(
            model_name="test_model",
            total_runs=5,
            total_tests=50,
            passed=40,
            failed=10,
            skipped=0,
            pass_rate_pct=80.0,
            pass_rate_7d_pct=75.0,
            pass_rate_30d_prior_pct=85.0,
            avg_duration_seconds=5.0,
            p50_duration_ms=5000.0,
            p95_duration_ms=8000.0,
            p99_duration_ms=10000.0,
            avg_throughput_tokens_per_sec=20.0,
            suite_metrics={},
        )
        metadata = {
            "name": "test_model",
            "provider": "test",
            "parameters_b": "7",
            "quantization": "q4",
            "context_window": "2048",
        }

        card = render_card(metrics, metadata, "SWOT text", "2024-04-25T12:00:00Z")

        assert "↓ -10.0pp" in card

    def test_card_trend_none_when_missing_data(self) -> None:
        metrics = ModelMetrics(
            model_name="test_model",
            total_runs=5,
            total_tests=50,
            passed=40,
            failed=10,
            skipped=0,
            pass_rate_pct=80.0,
            pass_rate_7d_pct=None,
            pass_rate_30d_prior_pct=None,
            avg_duration_seconds=5.0,
            p50_duration_ms=5000.0,
            p95_duration_ms=8000.0,
            p99_duration_ms=10000.0,
            avg_throughput_tokens_per_sec=20.0,
            suite_metrics={},
        )
        metadata = {
            "name": "test_model",
            "provider": "test",
            "parameters_b": "7",
            "quantization": "q4",
            "context_window": "2048",
        }

        card = render_card(metrics, metadata, "SWOT text", "2024-04-25T12:00:00Z")

        assert "Pass Rate Trend" not in card


class TestFetchModelMetadata:
    """Test metadata fetching (DB + Ollama fallback)."""

    def test_fetch_without_models_table(self) -> None:
        mock_db = MagicMock()
        del mock_db._models

        metadata = fetch_model_metadata("qwen2.5:72b", mock_db, ollama_client=None)

        assert metadata["name"] == "qwen2.5:72b"
        assert metadata["provider"] == "unknown"

    def test_fetch_with_ollama_fallback(self) -> None:
        mock_db = MagicMock()
        del mock_db._models
        mock_ollama = MagicMock()

        metadata = fetch_model_metadata(
            "qwen2.5:72b", mock_db, ollama_client=mock_ollama
        )

        assert metadata["name"] == "qwen2.5:72b"
        assert "Qwen" in metadata["provider"]


class TestGenerateSwot:
    """Test SWOT generation with Ollama."""

    def test_generate_swot_success(self) -> None:
        metrics = ModelMetrics(
            model_name="test_model",
            total_runs=10,
            total_tests=100,
            passed=85,
            failed=15,
            skipped=0,
            pass_rate_pct=85.0,
            pass_rate_7d_pct=90.0,
            pass_rate_30d_prior_pct=80.0,
            avg_duration_seconds=5.0,
            p50_duration_ms=5000.0,
            p95_duration_ms=8000.0,
            p99_duration_ms=10000.0,
            avg_throughput_tokens_per_sec=20.0,
            suite_metrics={"math": {"runs": 50, "passed": 42, "pass_rate_pct": 84.0}},
        )
        metadata = {
            "name": "test_model",
            "provider": "test",
            "parameters_b": "7",
            "quantization": "q4",
            "context_window": "2048",
        }

        mock_ollama = MagicMock()
        mock_ollama.generate.return_value = (
            "### Strengths\n- Fast\n### Weaknesses\n- Limited"
        )

        swot = generate_swot(metrics, metadata, mock_ollama)

        assert "### Strengths" in swot
        assert "### Weaknesses" in swot
        mock_ollama.generate.assert_called_once()

    def test_generate_swot_failure_returns_placeholder(self) -> None:
        metrics = ModelMetrics(
            model_name="test_model",
            total_runs=10,
            total_tests=100,
            passed=85,
            failed=15,
            skipped=0,
            pass_rate_pct=85.0,
            pass_rate_7d_pct=None,
            pass_rate_30d_prior_pct=None,
            avg_duration_seconds=5.0,
            p50_duration_ms=5000.0,
            p95_duration_ms=8000.0,
            p99_duration_ms=10000.0,
            avg_throughput_tokens_per_sec=20.0,
            suite_metrics={},
        )
        metadata = {
            "name": "test_model",
            "provider": "test",
            "parameters_b": "7",
            "quantization": "q4",
            "context_window": "2048",
        }

        mock_ollama = MagicMock()
        mock_ollama.generate.side_effect = Exception("Connection refused")

        swot = generate_swot(metrics, metadata, mock_ollama)

        assert "unavailable" in swot.lower()


class TestComputeMetrics:
    """Test metrics computation from test_results.

    Note: Full integration tests with real SQLAlchemy queries would require
    database fixtures; those are deferred to manual testing with real test_runs data.
    """

    def test_metrics_dataclass_fields(self) -> None:
        """Verify ModelMetrics dataclass has all expected fields."""
        metrics = ModelMetrics(
            model_name="test",
            total_runs=5,
            total_tests=50,
            passed=40,
            failed=10,
            skipped=0,
            pass_rate_pct=80.0,
            pass_rate_7d_pct=None,
            pass_rate_30d_prior_pct=None,
            avg_duration_seconds=5.0,
            p50_duration_ms=5000.0,
            p95_duration_ms=8000.0,
            p99_duration_ms=10000.0,
            avg_throughput_tokens_per_sec=20.0,
            suite_metrics={},
        )

        assert metrics.total_tests == 50
        assert metrics.pass_rate_pct == 80.0
        assert metrics.p95_duration_ms == 8000.0


class TestGetDistinctModels:
    """Test distinct model discovery.

    Note: Full integration tests with real SQLAlchemy queries would require
    database fixtures; those are deferred to manual testing with real test_runs data.
    """

    def test_get_distinct_models_no_backend(self) -> None:
        """When database has no _test_runs table, return empty list."""
        mock_db = MagicMock()
        del mock_db._test_runs

        models = get_distinct_models(mock_db)

        assert models == []


class TestMainCLI:
    """Test CLI entry point."""

    @patch("rfc.make_model_cards.TestDatabase")
    @patch("rfc.make_model_cards.create_provider")
    @patch("rfc.make_model_cards.get_distinct_models")
    @patch("rfc.make_model_cards.compute_metrics")
    @patch("rfc.make_model_cards.fetch_model_metadata")
    @patch("rfc.make_model_cards.generate_swot")
    def test_main_with_single_model(
        self,
        mock_swot: MagicMock,
        mock_metadata: MagicMock,
        mock_compute: MagicMock,
        mock_discover: MagicMock,
        mock_ollama: MagicMock,
        mock_db: MagicMock,
    ) -> None:
        mock_discover.return_value = ["test_model"]
        mock_compute.return_value = ModelMetrics(
            model_name="test_model",
            total_runs=5,
            total_tests=50,
            passed=45,
            failed=5,
            skipped=0,
            pass_rate_pct=90.0,
            pass_rate_7d_pct=None,
            pass_rate_30d_prior_pct=None,
            avg_duration_seconds=5.0,
            p50_duration_ms=5000.0,
            p95_duration_ms=8000.0,
            p99_duration_ms=10000.0,
            avg_throughput_tokens_per_sec=20.0,
            suite_metrics={},
        )
        mock_metadata.return_value = {
            "name": "test_model",
            "provider": "test",
            "parameters_b": "7",
            "quantization": "q4",
            "context_window": "2048",
        }
        mock_swot.return_value = "SWOT text"
        mock_ollama_instance = MagicMock(spec=OllamaClient)
        mock_ollama_instance.is_available.return_value = True
        mock_ollama.return_value = mock_ollama_instance

        with TemporaryDirectory() as tmpdir:
            with patch("sys.argv", ["make_model_cards", "--output", tmpdir]):
                from rfc.make_model_cards import main

                main()

            # Check that card file was created
            card_file = Path(tmpdir) / "test_model.md"
            assert card_file.exists()
            content = card_file.read_text()
            assert "# Model Card: test_model" in content


class TestBuildLLMProviderWrapperApplication:
    """The SWOT provider must be built through create_provider so the
    instrumentation wrappers apply; unwrap_provider() must still reach the
    concrete OllamaClient (#130)."""

    def test_provider_is_wrapped_and_unwraps_to_ollama(self, monkeypatch) -> None:
        from rfc.llm_client import unwrap_provider
        from rfc.make_model_cards import _build_llm_provider

        monkeypatch.setenv("LLM_CONSOLE_FEED_ENABLED", "1")
        provider = _build_llm_provider("http://localhost:11434", "test-model")

        assert not isinstance(provider, OllamaClient), (
            "provider should be wrapped, not a bare OllamaClient"
        )
        assert isinstance(unwrap_provider(provider), OllamaClient)
