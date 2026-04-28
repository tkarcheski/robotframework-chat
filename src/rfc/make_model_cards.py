"""Generate Markdown model cards from test results.

Produces objective SWOT analysis model cards for every LLM in the test_runs
database, with empirical metrics (pass rates, latency, throughput) and
LLM-generated summaries.

Usage::

    uv run python -m rfc.make_model_cards
    uv run python -m rfc.make_model_cards --output custom_dir/
    uv run python -m rfc.make_model_cards --model qwen2.5:72b
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from rfc.llm_client import OllamaClient
from rfc.retry import retry_on_transient
from rfc.test_database import TestDatabase

logger = logging.getLogger(__name__)


def slugify(model_name: str) -> str:
    """Convert model name to safe filename slug.

    Examples:
        "qwen2.5:72b" -> "qwen2_5_72b"
        "llama3.2:latest" -> "llama3_2_latest"
    """
    return re.sub(r"[^a-z0-9]+", "_", model_name.lower()).strip("_")


@dataclass
class ModelMetrics:
    """Computed metrics for a single model."""

    model_name: str
    total_runs: int
    total_tests: int
    passed: int
    failed: int
    skipped: int
    pass_rate_pct: float
    pass_rate_7d_pct: Optional[float]
    pass_rate_30d_prior_pct: Optional[float]
    avg_duration_seconds: float
    p50_duration_ms: float
    p95_duration_ms: float
    p99_duration_ms: float
    avg_throughput_tokens_per_sec: float
    suite_metrics: Dict[str, Dict[str, Any]]


def get_distinct_models(db: TestDatabase) -> List[str]:
    """Query all distinct model names from test_runs.

    Works with both SQLite and PostgreSQL backends.
    """
    try:
        from sqlalchemy import text  # type: ignore[import-not-found]

        if hasattr(db._backend, "engine"):
            # SQLAlchemy backend (PostgreSQL)
            with db._backend.engine.connect() as conn:  # type: ignore[attr-defined]
                result = conn.execute(
                    text(
                        "SELECT DISTINCT model_name FROM test_runs ORDER BY model_name"
                    )
                )
                return [row[0] for row in result if row[0]]
    except ImportError:
        pass
    except Exception as e:
        logger.error(f"Failed to query distinct models via SQLAlchemy: {e}")

    # Fallback to SQLite backend (db_path)
    try:
        import sqlite3

        if hasattr(db._backend, "db_path"):
            with sqlite3.connect(db._backend.db_path) as conn:  # type: ignore[attr-defined]
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT DISTINCT model_name FROM test_runs ORDER BY model_name"
                ).fetchall()
                return [row[0] for row in rows if row[0]]
    except Exception as e:
        logger.error(f"Failed to query distinct models via SQLite: {e}")

    logger.warning("Could not query test_runs table; skipping model discovery")
    return []


def compute_metrics(model_name: str, db: TestDatabase) -> ModelMetrics:
    """Compute all metrics for a single model from test_results.

    Aggregates across all runs, computes percentiles, and breaks down by suite.
    Works with both SQLite and PostgreSQL backends.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d_prior_start = now - timedelta(days=37)
    cutoff_30d_prior_end = now - timedelta(days=7)

    rows: List[tuple] = []

    # Try SQLAlchemy backend (PostgreSQL) first
    try:
        from sqlalchemy import text  # type: ignore[import-not-found]

        if hasattr(db._backend, "engine"):
            with db._backend.engine.connect() as conn:  # type: ignore[attr-defined]
                result = conn.execute(
                    text(
                        """
                        SELECT
                            tr.id as run_id,
                            tr.test_suite,
                            tr.duration_seconds,
                            tr.timestamp,
                            test_r.test_status,
                            COALESCE(test_r.eval_count, 0) as eval_count
                        FROM test_results test_r
                        JOIN test_runs tr ON test_r.run_id = tr.id
                        WHERE tr.model_name = :model_name
                        ORDER BY tr.timestamp, tr.id
                        """
                    ),
                    {"model_name": model_name},
                )
                rows = [tuple(row) for row in result.fetchall()]
    except Exception as e:
        logger.debug(f"SQLAlchemy backend failed: {e}")

    # Fallback to SQLite backend
    if not rows:
        try:
            import sqlite3

            if hasattr(db._backend, "db_path"):
                with sqlite3.connect(db._backend.db_path) as conn:  # type: ignore[attr-defined]
                    conn.row_factory = sqlite3.Row
                    result = conn.execute(
                        """
                        SELECT
                            tr.id as run_id,
                            tr.test_suite,
                            tr.duration_seconds,
                            tr.timestamp,
                            test_r.test_status,
                            COALESCE(test_r.eval_count, 0) as eval_count
                        FROM test_results test_r
                        JOIN test_runs tr ON test_r.run_id = tr.id
                        WHERE tr.model_name = ?
                        ORDER BY tr.timestamp, tr.id
                        """,
                        (model_name,),
                    ).fetchall()
                    rows = [tuple(row) for row in result]
        except Exception as e:
            logger.debug(f"SQLite backend failed: {e}")

    if not rows:
        logger.warning(f"No test results found for model: {model_name}")
        return ModelMetrics(
            model_name=model_name,
            total_runs=0,
            total_tests=0,
            passed=0,
            failed=0,
            skipped=0,
            pass_rate_pct=0.0,
            pass_rate_7d_pct=None,
            pass_rate_30d_prior_pct=None,
            avg_duration_seconds=0.0,
            p50_duration_ms=0.0,
            p95_duration_ms=0.0,
            p99_duration_ms=0.0,
            avg_throughput_tokens_per_sec=0.0,
            suite_metrics={},
        )

    total_tests = len(rows)
    passed = sum(1 for r in rows if r[4] == "PASS")
    failed = sum(1 for r in rows if r[4] == "FAIL")
    skipped = sum(1 for r in rows if r[4] == "SKIP")

    # Get distinct run durations for latency percentiles.
    run_durations = {}
    for r in rows:
        run_id = r[0]
        if run_id not in run_durations:
            run_durations[run_id] = (r[2] or 0.0) * 1000  # Convert to ms

    durations_ms = sorted(run_durations.values())
    p50 = durations_ms[int(len(durations_ms) * 0.50)] if durations_ms else 0.0
    p95 = durations_ms[int(len(durations_ms) * 0.95)] if durations_ms else 0.0
    p99 = durations_ms[int(len(durations_ms) * 0.99)] if durations_ms else 0.0

    # Compute throughput per run, then average across runs.
    run_throughputs = {}
    for r in rows:
        run_id = r[0]
        if run_id not in run_throughputs:
            duration_s = r[2] or 1
            run_throughputs[run_id] = {"eval_count": 0, "duration_s": duration_s}
        run_throughputs[run_id]["eval_count"] += r[5] or 0

    throughputs = [
        run["eval_count"] / run["duration_s"]
        for run in run_throughputs.values()
        if run["duration_s"] > 0
    ]
    avg_throughput = sum(throughputs) / len(throughputs) if throughputs else 0.0

    rows_7d = [r for r in rows if r[3] and r[3] >= cutoff_7d]
    rows_30d_prior = [
        r
        for r in rows
        if r[3] and cutoff_30d_prior_start <= r[3] < cutoff_30d_prior_end
    ]

    pass_rate_7d = (
        (sum(1 for r in rows_7d if r[4] == "PASS") / len(rows_7d) * 100)
        if rows_7d
        else None
    )
    pass_rate_30d_prior = (
        (sum(1 for r in rows_30d_prior if r[4] == "PASS") / len(rows_30d_prior) * 100)
        if rows_30d_prior
        else None
    )

    suite_metrics: Dict[str, Dict[str, Any]] = {}
    for suite in set(r[1] for r in rows if r[1]):
        suite_rows = [r for r in rows if r[1] == suite]
        suite_passed = sum(1 for r in suite_rows if r[4] == "PASS")
        suite_tests = len(suite_rows)
        suite_pass_rate = (suite_passed / suite_tests * 100) if suite_tests else 0.0

        # Count distinct runs per suite (not result rows).
        suite_run_ids = set(r[0] for r in suite_rows)
        suite_run_count = len(suite_run_ids)

        suite_durations_ms = [
            run_durations[run_id] for run_id in suite_run_ids if run_id in run_durations
        ]
        suite_durations_ms.sort()
        suite_p95 = (
            suite_durations_ms[int(len(suite_durations_ms) * 0.95)]
            if suite_durations_ms
            else 0.0
        )
        suite_metrics[suite] = {
            "runs": suite_run_count,
            "passed": suite_passed,
            "pass_rate_pct": suite_pass_rate,
            "p95_ms": suite_p95,
        }

    # Count distinct runs from run_id.
    unique_runs = len(run_durations)

    avg_duration_seconds = (
        sum(run_durations.values()) / len(run_durations) / 1000
        if run_durations
        else 0.0
    )

    return ModelMetrics(
        model_name=model_name,
        total_runs=unique_runs,
        total_tests=total_tests,
        passed=passed,
        failed=failed,
        skipped=skipped,
        pass_rate_pct=(passed / total_tests * 100) if total_tests else 0.0,
        pass_rate_7d_pct=pass_rate_7d,
        pass_rate_30d_prior_pct=pass_rate_30d_prior,
        avg_duration_seconds=avg_duration_seconds,
        p50_duration_ms=p50,
        p95_duration_ms=p95,
        p99_duration_ms=p99,
        avg_throughput_tokens_per_sec=avg_throughput,
        suite_metrics=suite_metrics,
    )


def fetch_model_metadata(
    model_name: str, db: TestDatabase, ollama_client: Optional[OllamaClient] = None
) -> Dict[str, Any]:
    """Fetch model metadata: hybrid DB + Ollama fallback.

    Tries to find the model in the local models table first,
    then falls back to Ollama's model metadata.
    """
    metadata: Dict[str, Any] = {
        "name": model_name,
        "provider": "unknown",
        "parameters_b": "unknown",
        "quantization": "unknown",
        "context_window": "unknown",
    }

    if hasattr(db._backend, "_models"):
        try:
            from sqlalchemy import select  # type: ignore[import-not-found]

            query = select(
                db._backend._models.c.architecture,
                db._backend._models.c.family,
                db._backend._models.c.quantization,
                db._backend._models.c.context_length,
            ).where(db._backend._models.c.name == model_name)

            with db._backend.engine.connect() as conn:  # type: ignore[attr-defined]
                row = conn.execute(query).fetchone()
                if row:
                    metadata["provider"] = row[1] or "unknown"
                    metadata["quantization"] = row[2] or "unknown"
                    context_len = row[3]
                    if context_len:
                        metadata["context_window"] = f"{context_len:,}"
                    return metadata
        except Exception as e:
            logger.warning(f"Failed to query local models table: {e}")

    if ollama_client:
        try:
            metadata["provider"] = "ollama"
            if "qwen" in model_name.lower():
                metadata["provider"] = "Qwen"
            elif "llama" in model_name.lower():
                metadata["provider"] = "Meta Llama"
            elif "mistral" in model_name.lower():
                metadata["provider"] = "Mistral"
            logger.info(f"Using Ollama metadata for {model_name}")
        except Exception as e:
            logger.warning(f"Failed to fetch Ollama metadata: {e}")

    return metadata


def render_metadata_table(metadata: Dict[str, Any]) -> str:
    """Render metadata as a markdown table."""
    return f"""## Metadata

| Field | Value |
|---|---|
| Provider | {metadata.get("provider", "unknown")} |
| Parameters | {metadata.get("parameters_b", "unknown")}B |
| Quantization | {metadata.get("quantization", "unknown")} |
| Context Window | {metadata.get("context_window", "unknown")} |
"""


def render_benchmarks_table(metrics: ModelMetrics) -> str:
    """Render benchmarks by suite as a markdown table."""
    lines = [
        "",
        "## Benchmarks",
        "",
        "| Suite | Runs | Pass % | p95 ms | tok/s |",
        "|---|---|---|---|---|",
    ]

    for suite_name in sorted(metrics.suite_metrics.keys()):
        suite = metrics.suite_metrics[suite_name]
        lines.append(
            f"| {suite_name} | {suite['runs']} | {suite['pass_rate_pct']:.1f}% | "
            f"{suite['p95_ms']:.0f} | {metrics.avg_throughput_tokens_per_sec:.1f} |"
        )

    lines.append("")
    return "\n".join(lines)


def generate_swot(
    metrics: ModelMetrics, metadata: Dict[str, Any], ollama_client: OllamaClient
) -> str:
    """Generate SWOT analysis via LLM with retry.

    Returns the SWOT markdown section (Strengths, Weaknesses, Opportunities, Threats).
    On failure, returns a placeholder noting LLM unavailable.
    """
    payload = {
        "model_name": metrics.model_name,
        "total_runs": metrics.total_runs,
        "total_tests": metrics.total_tests,
        "pass_rate_pct": round(metrics.pass_rate_pct, 1),
        "pass_rate_7d_vs_30d_prior": None,
        "avg_latency_ms": round(metrics.p50_duration_ms, 0),
        "p95_latency_ms": round(metrics.p95_duration_ms, 0),
        "throughput_tokens_per_sec": round(metrics.avg_throughput_tokens_per_sec, 1),
        "provider": metadata.get("provider", "unknown"),
        "quantization": metadata.get("quantization", "unknown"),
        "suite_breakdown": {
            k: {
                "runs": v["runs"],
                "pass_rate_pct": round(v["pass_rate_pct"], 1),
            }
            for k, v in metrics.suite_metrics.items()
        },
    }

    if (
        metrics.pass_rate_7d_pct is not None
        and metrics.pass_rate_30d_prior_pct is not None
    ):
        payload["pass_rate_7d_vs_30d_prior"] = round(
            metrics.pass_rate_7d_pct - metrics.pass_rate_30d_prior_pct, 1
        )

    system_prompt = (
        "You are a senior ML evaluation analyst. Given empirical test metrics for one LLM, "
        "produce an objective Markdown SWOT analysis with sections: Strengths, Weaknesses, "
        "Opportunities, Threats. Cite metric values inline. Do not invent data. "
        "Format each section as a list of 2-4 bullet points. Keep the total response under 1000 tokens."
    )

    user_prompt = f"Model: {metrics.model_name}\n\nMetrics (JSON):\n{json.dumps(payload, indent=2)}"

    def _generate_swot() -> str:
        return ollama_client.generate(
            f"{system_prompt}\n\n{user_prompt}",
        )

    try:
        logger.info(f"Generating SWOT for {metrics.model_name}...")
        swot_text = retry_on_transient(_generate_swot, max_retries=3)
        return swot_text
    except Exception as e:
        logger.warning(
            f"SWOT generation failed for {metrics.model_name}: {e} (skipping)"
        )
        return (
            "_SWOT analysis unavailable — LLM service temporarily unavailable. "
            "Rerun the command when Ollama is accessible._"
        )


def render_card(
    metrics: ModelMetrics,
    metadata: Dict[str, Any],
    swot_text: str,
    timestamp: str,
) -> str:
    """Render complete model card markdown.

    Args:
        metrics: Computed metrics dataclass.
        metadata: Model metadata dict.
        swot_text: LLM-generated SWOT section.
        timestamp: ISO timestamp for generation time.

    Returns:
        Complete markdown model card.
    """
    card_lines = [
        f"# Model Card: {metrics.model_name}",
        f"_Generated: {timestamp} — Source: test_runs (n={metrics.total_runs})_",
        "",
    ]

    # Metadata table
    card_lines.append(render_metadata_table(metadata).strip())
    card_lines.append("")

    card_lines.append(render_benchmarks_table(metrics).strip())
    card_lines.append("")

    card_lines.extend(
        [
            "## Overall Results",
            "",
            f"- **Total Tests:** {metrics.total_tests}",
            f"- **Pass Rate:** {metrics.pass_rate_pct:.1f}%",
            f"- **Median Latency:** {metrics.p50_duration_ms:.0f} ms",
            f"- **p95 Latency:** {metrics.p95_duration_ms:.0f} ms",
            f"- **Throughput:** {metrics.avg_throughput_tokens_per_sec:.1f} tok/s",
        ]
    )

    if (
        metrics.pass_rate_7d_pct is not None
        and metrics.pass_rate_30d_prior_pct is not None
    ):
        delta = metrics.pass_rate_7d_pct - metrics.pass_rate_30d_prior_pct
        direction = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        card_lines.append(
            f"- **Pass Rate Trend (7d vs 30d prior):** {direction} {delta:+.1f}pp "
            f"({metrics.pass_rate_7d_pct:.1f}% → {metrics.pass_rate_30d_prior_pct:.1f}%)"
        )

    card_lines.extend(
        [
            "",
            "## SWOT Analysis",
            "",
            swot_text,
            "",
        ]
    )

    return "\n".join(card_lines)


def main() -> None:
    """CLI entry point for model card generation."""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Generate Markdown model cards from test results"
    )
    parser.add_argument(
        "--output",
        "-o",
        default="model_cards",
        help="Output directory for model cards (default: model_cards/)",
    )
    parser.add_argument(
        "--model",
        help="Generate card for a single model (default: all models)",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", "sqlite:///data/test_history.db"),
        help="Database URL (default: $DATABASE_URL or sqlite:///data/test_history.db)",
    )
    parser.add_argument(
        "--ollama-endpoint",
        default=os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434"),
        help="Ollama endpoint (default: $OLLAMA_ENDPOINT or http://localhost:11434)",
    )
    parser.add_argument(
        "--llm-model",
        default=os.getenv("MODEL_CARD_LLM", "qwen2.5:72b"),
        help="LLM for SWOT analysis (default: $MODEL_CARD_LLM or qwen2.5:72b)",
    )

    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    db = TestDatabase(database_url=args.database_url)

    try:
        ollama_client = OllamaClient(
            base_url=args.ollama_endpoint,
            model=args.llm_model,
            temperature=0.2,
            max_tokens=2048,
            timeout=300,
        )
    except Exception as e:
        logger.warning(f"Failed to initialize Ollama client: {e}")
        ollama_client = None

    if args.model:
        model_names = [args.model]
    else:
        model_names = get_distinct_models(db)

    if not model_names:
        logger.warning("No models found in database; exiting")
        return

    timestamp = (
        datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
        + "Z"
    )
    skipped_models: Dict[str, str] = {}
    generated_cards = 0

    for model_name in model_names:
        try:
            logger.info(f"Processing {model_name}...")

            metrics = compute_metrics(model_name, db)
            if metrics.total_tests == 0:
                logger.warning(f"Skipping {model_name}: no test results")
                skipped_models[model_name] = "no test results"
                continue

            metadata = fetch_model_metadata(model_name, db, ollama_client)

            if ollama_client and ollama_client.is_available():
                swot_text = generate_swot(metrics, metadata, ollama_client)
            else:
                logger.warning(
                    f"Ollama unavailable for {model_name}; SWOT will be skipped"
                )
                swot_text = (
                    "_SWOT analysis unavailable — Ollama endpoint not accessible. "
                    "Rerun when Ollama is available._"
                )

            card = render_card(metrics, metadata, swot_text, timestamp)
            card_file = output_dir / f"{slugify(model_name)}.md"
            card_file.write_text(card)

            logger.info(f"Generated {card_file}")
            generated_cards += 1

        except Exception as e:
            logger.error(f"Failed to generate card for {model_name}: {e}")
            skipped_models[model_name] = str(e)

    print(f"\n{'=' * 60}")
    print(f"Generated {generated_cards} model card(s) in {output_dir}/")
    if skipped_models:
        print(f"\nSkipped {len(skipped_models)} model(s):")
        for model_name, reason in skipped_models.items():
            print(f"  - {model_name}: {reason}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
