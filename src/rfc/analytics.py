"""Analytics metadata layer for Robot Framework test results.

Computes derived metrics from raw test data to surface trends,
anomalies, and comparative insights. Works with both SQLite and
PostgreSQL backends via raw SQL.

Analytics tables:
- analytics_model_trends: Rolling pass-rate and duration trends
- analytics_test_stability: Flaky/stable/broken test classification
- analytics_model_comparison: Pairwise model comparison matrix
- analytics_regression_alerts: Anomaly detection events
- analytics_performance_fingerprints: Speed profiles per test/model/host

Usage::

    uv run python -m rfc.analytics --refresh-all
    uv run python -m rfc.analytics --detect-regressions
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Schema DDL ───────────────────────────────────────────────────────

ANALYTICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS analytics_model_trends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    test_suite TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    run_count INTEGER,
    avg_pass_rate REAL,
    pass_rate_delta REAL,
    avg_duration REAL,
    duration_delta REAL,
    trend_direction TEXT,
    computed_at TEXT NOT NULL,
    UNIQUE(model_name, test_suite)
);

CREATE TABLE IF NOT EXISTS analytics_test_stability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_name TEXT NOT NULL,
    model_name TEXT NOT NULL,
    window_runs INTEGER,
    pass_count INTEGER,
    fail_count INTEGER,
    flip_count INTEGER,
    stability_score REAL,
    classification TEXT,
    last_status TEXT,
    computed_at TEXT NOT NULL,
    UNIQUE(test_name, model_name)
);

CREATE TABLE IF NOT EXISTS analytics_model_comparison (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_suite TEXT NOT NULL,
    model_a TEXT NOT NULL,
    model_b TEXT NOT NULL,
    pass_rate_a REAL,
    pass_rate_b REAL,
    pass_rate_diff REAL,
    duration_a REAL,
    duration_b REAL,
    speed_ratio REAL,
    winner TEXT,
    computed_at TEXT NOT NULL,
    UNIQUE(test_suite, model_a, model_b)
);

CREATE TABLE IF NOT EXISTS analytics_regression_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at TEXT NOT NULL,
    model_name TEXT NOT NULL,
    test_suite TEXT,
    test_name TEXT,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    current_value REAL,
    previous_value REAL,
    threshold REAL,
    message TEXT,
    run_id INTEGER,
    acknowledged INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS analytics_performance_fingerprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_name TEXT NOT NULL,
    model_name TEXT NOT NULL,
    hostname TEXT,
    avg_duration REAL,
    p50_duration REAL,
    p95_duration REAL,
    sample_count INTEGER,
    tokens_per_second REAL,
    computed_at TEXT NOT NULL,
    UNIQUE(test_name, model_name, hostname)
);
"""


def _has_column(
    conn: sqlite3.Connection, table: str, column: str
) -> bool:
    """Check whether *table* has a column named *column*."""
    cursor = conn.execute(f"PRAGMA table_info({table})")  # noqa: S608
    return any(row[1] == column for row in cursor.fetchall())


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create analytics tables if they don't exist."""
    conn.executescript(ANALYTICS_SCHEMA)


def _percentile(values: list[float], p: float) -> float:
    """Compute percentile from a sorted list of values."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = f + 1
    if c >= len(sorted_vals):
        return sorted_vals[f]
    return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])


# ── Computation Functions ────────────────────────────────────────────


def compute_model_trends(
    conn: sqlite3.Connection, window_days: int = 7
) -> int:
    """Compute rolling pass-rate and duration trends per model/suite.

    Compares the most recent ``window_days`` against the previous
    ``window_days`` to determine if a model is improving, stable,
    or regressing.

    Returns:
        Number of trend rows written.
    """
    _ensure_schema(conn)
    now = datetime.now().isoformat()

    # Get all model/suite combinations
    combos = conn.execute(
        "SELECT DISTINCT model_name, test_suite FROM test_runs"
    ).fetchall()

    if not combos:
        return 0

    count = 0
    for model_name, test_suite in combos:
        # Recent period
        recent = conn.execute(
            """SELECT COUNT(*), AVG(CAST(passed AS REAL) / NULLIF(total_tests, 0)),
                      AVG(duration_seconds), MIN(timestamp), MAX(timestamp)
               FROM test_runs
               WHERE model_name = ? AND test_suite = ?
               AND timestamp >= datetime('now', ?)""",
            (model_name, test_suite, f"-{window_days} days"),
        ).fetchone()

        # Previous period
        previous = conn.execute(
            """SELECT AVG(CAST(passed AS REAL) / NULLIF(total_tests, 0)),
                      AVG(duration_seconds)
               FROM test_runs
               WHERE model_name = ? AND test_suite = ?
               AND timestamp >= datetime('now', ?)
               AND timestamp < datetime('now', ?)""",
            (model_name, test_suite,
             f"-{window_days * 2} days", f"-{window_days} days"),
        ).fetchone()

        if not recent or recent[0] == 0:
            continue

        run_count = recent[0]
        avg_pass_rate = recent[1] or 0.0
        avg_duration = recent[2] or 0.0
        period_start = recent[3] or now
        period_end = recent[4] or now

        prev_pass_rate = previous[0] if previous else None
        prev_duration = previous[1] if previous else None

        pass_rate_delta = 0.0
        duration_delta = 0.0
        trend = "stable"

        if prev_pass_rate is not None:
            pass_rate_delta = avg_pass_rate - prev_pass_rate
            if pass_rate_delta < -0.05:
                trend = "regressing"
            elif pass_rate_delta > 0.05:
                trend = "improving"

        if prev_duration is not None:
            duration_delta = avg_duration - prev_duration

        conn.execute(
            """INSERT OR REPLACE INTO analytics_model_trends
               (model_name, test_suite, period_start, period_end,
                run_count, avg_pass_rate, pass_rate_delta,
                avg_duration, duration_delta, trend_direction, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (model_name, test_suite, period_start, period_end,
             run_count, avg_pass_rate, pass_rate_delta,
             avg_duration, duration_delta, trend, now),
        )
        count += 1

    conn.commit()
    logger.info("Computed %d model trend(s)", count)
    return count


def compute_test_stability(
    conn: sqlite3.Connection, window_runs: int = 20
) -> int:
    """Classify test stability based on flip frequency.

    For each (test_name, model_name) pair, counts PASS→FAIL and
    FAIL→PASS transitions. Classifies as:
    - stable: all pass, no flips
    - broken: all fail, no flips
    - flaky: 2+ flips (oscillates)
    - new: fewer than 3 runs

    Returns:
        Number of stability rows written.
    """
    _ensure_schema(conn)
    now = datetime.now().isoformat()

    # Get test/model combos with recent results
    combos = conn.execute(
        """SELECT DISTINCT tr.test_name, r.model_name
           FROM test_results tr
           JOIN test_runs r ON tr.run_id = r.id"""
    ).fetchall()

    if not combos:
        return 0

    count = 0
    for test_name, model_name in combos:
        # Get recent statuses in chronological order
        statuses = conn.execute(
            """SELECT tr.test_status
               FROM test_results tr
               JOIN test_runs r ON tr.run_id = r.id
               WHERE tr.test_name = ? AND r.model_name = ?
               ORDER BY r.timestamp DESC
               LIMIT ?""",
            (test_name, model_name, window_runs),
        ).fetchall()

        if not statuses:
            continue

        status_list = [s[0] for s in statuses]
        total = len(status_list)
        pass_count = sum(1 for s in status_list if s == "PASS")
        fail_count = sum(1 for s in status_list if s == "FAIL")

        # Count flips (transitions between PASS and FAIL)
        flip_count = 0
        for i in range(1, len(status_list)):
            if status_list[i] != status_list[i - 1]:
                flip_count += 1

        # Classification
        if total < 3:
            classification = "new"
        elif flip_count == 0 and pass_count == total:
            classification = "stable"
        elif flip_count == 0 and fail_count == total:
            classification = "broken"
        elif flip_count >= 2:
            classification = "flaky"
        elif flip_count == 1 and fail_count > pass_count:
            classification = "broken"
        else:
            classification = "stable"

        stability_score = 1.0 - (flip_count / max(total, 1))

        conn.execute(
            """INSERT OR REPLACE INTO analytics_test_stability
               (test_name, model_name, window_runs, pass_count, fail_count,
                flip_count, stability_score, classification, last_status,
                computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (test_name, model_name, total, pass_count, fail_count,
             flip_count, stability_score, classification,
             status_list[0], now),
        )
        count += 1

    conn.commit()
    logger.info("Computed %d test stability row(s)", count)
    return count


def compute_model_comparison(conn: sqlite3.Connection) -> int:
    """Build pairwise model comparison matrix.

    For each test suite, compares every pair of models by overall
    pass rate and average duration. Determines a winner.

    Returns:
        Number of comparison rows written.
    """
    _ensure_schema(conn)
    now = datetime.now().isoformat()

    # Get model stats per suite
    stats = conn.execute(
        """SELECT model_name, test_suite,
                  AVG(CAST(passed AS REAL) / NULLIF(total_tests, 0)) as pass_rate,
                  AVG(duration_seconds) as avg_dur
           FROM test_runs
           GROUP BY model_name, test_suite"""
    ).fetchall()

    if not stats:
        return 0

    # Group by suite
    by_suite: dict[str, list[tuple[str, float, float]]] = {}
    for model, suite, pr, dur in stats:
        if suite not in by_suite:
            by_suite[suite] = []
        by_suite[suite].append((model, pr or 0.0, dur or 0.0))

    count = 0
    for suite, models in by_suite.items():
        for i, (model_a, pr_a, dur_a) in enumerate(models):
            for model_b, pr_b, dur_b in models[i + 1:]:
                diff = pr_a - pr_b
                speed_ratio = dur_a / dur_b if dur_b > 0 else 0.0

                # Winner: higher pass rate wins; tie broken by speed
                if abs(diff) < 0.01:
                    winner = model_a if dur_a < dur_b else model_b
                else:
                    winner = model_a if diff > 0 else model_b

                conn.execute(
                    """INSERT OR REPLACE INTO analytics_model_comparison
                       (test_suite, model_a, model_b, pass_rate_a, pass_rate_b,
                        pass_rate_diff, duration_a, duration_b, speed_ratio,
                        winner, computed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (suite, model_a, model_b, pr_a, pr_b, diff,
                     dur_a, dur_b, speed_ratio, winner, now),
                )
                count += 1

    conn.commit()
    logger.info("Computed %d model comparison(s)", count)
    return count


def detect_regressions(
    conn: sqlite3.Connection,
    threshold: float = 0.1,
    window_runs: int = 7,
) -> list[dict[str, Any]]:
    """Detect regressions: pass-rate drops and duration spikes.

    Compares the most recent ``window_runs`` against the previous
    ``window_runs`` for each (model, suite) pair.

    Severity levels:
    - info: <10% drop
    - warning: 10-25% drop
    - critical: >25% drop

    Returns:
        List of alert dicts.
    """
    _ensure_schema(conn)
    now = datetime.now().isoformat()
    alerts: list[dict[str, Any]] = []

    combos = conn.execute(
        "SELECT DISTINCT model_name, test_suite FROM test_runs"
    ).fetchall()

    for model_name, test_suite in combos:
        # Get all runs ordered by time
        runs = conn.execute(
            """SELECT passed, total_tests, duration_seconds
               FROM test_runs
               WHERE model_name = ? AND test_suite = ?
               ORDER BY timestamp DESC""",
            (model_name, test_suite),
        ).fetchall()

        if len(runs) < window_runs * 2:
            continue

        recent = runs[:window_runs]
        previous = runs[window_runs: window_runs * 2]

        # Pass rate comparison
        recent_pr = sum(
            r[0] / r[1] for r in recent if r[1] > 0
        ) / len(recent)
        prev_pr = sum(
            r[0] / r[1] for r in previous if r[1] > 0
        ) / len(previous)

        drop = prev_pr - recent_pr
        if drop > threshold:
            if drop > 0.25:
                severity = "critical"
            elif drop > 0.10:
                severity = "warning"
            else:
                severity = "info"

            alert = {
                "detected_at": now,
                "model_name": model_name,
                "test_suite": test_suite,
                "test_name": None,
                "alert_type": "pass_rate_drop",
                "severity": severity,
                "current_value": recent_pr,
                "previous_value": prev_pr,
                "threshold": threshold,
                "message": (
                    f"{model_name}/{test_suite}: pass rate dropped from "
                    f"{prev_pr:.1%} to {recent_pr:.1%} "
                    f"(delta: -{drop:.1%})"
                ),
            }
            alerts.append(alert)

            conn.execute(
                """INSERT INTO analytics_regression_alerts
                   (detected_at, model_name, test_suite, alert_type,
                    severity, current_value, previous_value, threshold,
                    message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, model_name, test_suite, "pass_rate_drop",
                 severity, recent_pr, prev_pr, threshold,
                 alert["message"]),
            )

        # Duration spike comparison
        recent_dur = sum(r[2] for r in recent if r[2]) / len(recent)
        prev_dur = sum(r[2] for r in previous if r[2]) / len(previous)

        if prev_dur > 0 and recent_dur > prev_dur * 2:
            alert = {
                "detected_at": now,
                "model_name": model_name,
                "test_suite": test_suite,
                "test_name": None,
                "alert_type": "duration_spike",
                "severity": "warning",
                "current_value": recent_dur,
                "previous_value": prev_dur,
                "threshold": 2.0,
                "message": (
                    f"{model_name}/{test_suite}: duration spiked from "
                    f"{prev_dur:.1f}s to {recent_dur:.1f}s "
                    f"({recent_dur / prev_dur:.1f}x)"
                ),
            }
            alerts.append(alert)

            conn.execute(
                """INSERT INTO analytics_regression_alerts
                   (detected_at, model_name, test_suite, alert_type,
                    severity, current_value, previous_value, threshold,
                    message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, model_name, test_suite, "duration_spike",
                 "warning", recent_dur, prev_dur, 2.0,
                 alert["message"]),
            )

    conn.commit()
    logger.info("Detected %d regression(s)", len(alerts))
    return alerts


def compute_performance_fingerprints(conn: sqlite3.Connection) -> int:
    """Compute per-test/model/host performance profiles.

    Calculates avg, p50, and p95 duration from test_results
    joined with test_runs. Also pulls tokens/second from
    ollama_metrics if available.

    Returns:
        Number of fingerprint rows written.
    """
    _ensure_schema(conn)
    now = datetime.now().isoformat()

    has_hostname = _has_column(conn, "test_runs", "hostname")

    # Get all test/model/host combos with durations
    if has_hostname:
        combos = conn.execute(
            """SELECT tr.test_name, r.model_name, r.hostname
               FROM test_results tr
               JOIN test_runs r ON tr.run_id = r.id
               GROUP BY tr.test_name, r.model_name, r.hostname
               HAVING COUNT(*) >= 2"""
        ).fetchall()
    else:
        combos = [
            (row[0], row[1], None)
            for row in conn.execute(
                """SELECT tr.test_name, r.model_name
                   FROM test_results tr
                   JOIN test_runs r ON tr.run_id = r.id
                   GROUP BY tr.test_name, r.model_name
                   HAVING COUNT(*) >= 2"""
            ).fetchall()
        ]

    if not combos:
        return 0

    count = 0
    for test_name, model_name, hostname in combos:
        # Get per-run durations for this test
        if has_hostname:
            durations = conn.execute(
                """SELECT r.duration_seconds / NULLIF(r.total_tests, 0)
                   FROM test_results tr
                   JOIN test_runs r ON tr.run_id = r.id
                   WHERE tr.test_name = ? AND r.model_name = ?
                   AND (r.hostname = ? OR (r.hostname IS NULL AND ? IS NULL))""",
                (test_name, model_name, hostname, hostname),
            ).fetchall()
        else:
            durations = conn.execute(
                """SELECT r.duration_seconds / NULLIF(r.total_tests, 0)
                   FROM test_results tr
                   JOIN test_runs r ON tr.run_id = r.id
                   WHERE tr.test_name = ? AND r.model_name = ?""",
                (test_name, model_name),
            ).fetchall()

        dur_values = [d[0] for d in durations if d[0] is not None]
        if not dur_values:
            continue

        avg_dur = sum(dur_values) / len(dur_values)
        p50 = _percentile(dur_values, 0.5)
        p95 = _percentile(dur_values, 0.95)

        # Try to get tokens/sec from ollama_metrics
        tps_row = conn.execute(
            """SELECT AVG(eval_rate)
               FROM ollama_metrics
               WHERE model_name = ?
               AND eval_rate IS NOT NULL""",
            (model_name,),
        ).fetchone()
        tps = tps_row[0] if tps_row and tps_row[0] else None

        conn.execute(
            """INSERT OR REPLACE INTO analytics_performance_fingerprints
               (test_name, model_name, hostname, avg_duration,
                p50_duration, p95_duration, sample_count,
                tokens_per_second, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (test_name, model_name, hostname, avg_dur, p50, p95,
             len(dur_values), tps, now),
        )
        count += 1

    conn.commit()
    logger.info("Computed %d performance fingerprint(s)", count)
    return count


def refresh_all(conn: sqlite3.Connection) -> dict[str, int]:
    """Run all analytics computations.

    Returns:
        Dict mapping computation name to row count.
    """
    return {
        "model_trends": compute_model_trends(conn),
        "test_stability": compute_test_stability(conn),
        "model_comparison": compute_model_comparison(conn),
        "regressions": len(detect_regressions(conn)),
        "performance_fingerprints": compute_performance_fingerprints(conn),
    }


def main() -> None:
    """CLI entry point for analytics computations."""
    import argparse
    import os

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s: %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="Compute analytics from Robot Framework test results"
    )
    parser.add_argument(
        "--refresh-all", action="store_true",
        help="Run all analytics computations",
    )
    parser.add_argument(
        "--detect-regressions", action="store_true",
        help="Detect and print regressions",
    )
    parser.add_argument(
        "--db-path",
        default=os.environ.get("ANALYTICS_DB", "data/test_history.db"),
        help="Path to SQLite database (default: data/test_history.db)",
    )

    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)

    if args.refresh_all:
        print("=== Analytics Refresh ===")
        result = refresh_all(conn)
        for name, cnt in result.items():
            print(f"  {name}: {cnt} row(s)")
        print("=== Done ===")

    elif args.detect_regressions:
        print("=== Regression Detection ===")
        alerts = detect_regressions(conn)
        if not alerts:
            print("  No regressions detected.")
        else:
            for alert in alerts:
                severity = alert["severity"].upper()
                print(f"  [{severity}] {alert['message']}")
        print(f"=== {len(alerts)} alert(s) ===")

    else:
        parser.print_help()

    conn.close()


if __name__ == "__main__":
    main()
