#!/usr/bin/env python3
"""Collect repo metrics across git history and generate timeline plots.

Walks sampled commits, counts lines of code and file sizes by type
(.py, .robot, other), and produces a stacked timeline chart saved as PNG.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

FILE_CATEGORIES: dict[str, str] = {
    ".py": "Python (.py)",
    ".robot": "Robot (.robot)",
}

OTHER_LABEL = "Other"

CATEGORY_COLORS: dict[str, str] = {
    "Python (.py)": "#3572A5",
    "Robot (.robot)": "#00b0d7",
    OTHER_LABEL: "#999999",
}

# Extensions counted for lines (skip known binaries)
TEXT_EXTENSIONS: set[str] = {
    ".py",
    ".robot",
    ".yaml",
    ".yml",
    ".md",
    ".txt",
    ".toml",
    ".cfg",
    ".ini",
    ".sh",
    ".bash",
    ".json",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".rst",
    ".lock",
}


def get_commits() -> list[tuple[str, datetime]]:
    """Return (sha, author_date) for every commit, oldest first."""
    result = subprocess.run(
        ["git", "log", "--format=%H %aI", "--reverse"],
        capture_output=True,
        text=True,
        check=True,
    )
    commits = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        sha, iso = line.split(" ", 1)
        dt = datetime.fromisoformat(iso)
        commits.append((sha, dt))
    return commits


def sample_commits(
    commits: list[tuple[str, datetime]],
    max_points: int = 30,
) -> list[tuple[str, datetime]]:
    """Evenly sample commits to keep the plot readable."""
    if len(commits) <= max_points:
        return commits
    step = len(commits) / max_points
    indices = [int(i * step) for i in range(max_points)]
    if indices[-1] != len(commits) - 1:
        indices.append(len(commits) - 1)
    return [commits[i] for i in indices]


def metrics_at_commit(sha: str) -> dict[str, dict[str, int]]:
    """Collect file counts, line counts, and byte sizes at *sha*."""
    result = subprocess.run(
        ["git", "archive", sha],
        capture_output=True,
        check=True,
    )

    stats: dict[str, dict[str, int]] = {}
    for cat in list(FILE_CATEGORIES.values()) + [OTHER_LABEL]:
        stats[cat] = {"files": 0, "bytes": 0, "lines": 0}

    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            ext = Path(member.name).suffix.lower()
            category = FILE_CATEGORIES.get(ext, OTHER_LABEL)
            stats[category]["files"] += 1
            stats[category]["bytes"] += member.size

            if ext in TEXT_EXTENSIONS:
                f = tar.extractfile(member)
                if f:
                    stats[category]["lines"] += f.read().count(b"\n")

    return stats


def collect_timeline(max_points: int = 30) -> list[dict]:
    """Build a list of metric snapshots across the repo history."""
    commits = get_commits()
    sampled = sample_commits(commits, max_points)
    timeline = []
    for i, (sha, dt) in enumerate(sampled, 1):
        short = sha[:7]
        ts = dt.strftime("%H:%M")
        print(
            f"  [{i}/{len(sampled)}] {short} {dt.date()} {ts}",
            file=sys.stderr,
        )
        snapshot = metrics_at_commit(sha)
        timeline.append(
            {
                "sha": sha,
                "short_sha": short,
                "date": dt.isoformat(),
                "metrics": snapshot,
            }
        )
    return timeline


def _compute_deltas(timeline: list[dict]) -> dict[str, dict[str, int]]:
    """Compute metric changes between the first and last snapshot.

    Returns a dict keyed by category with ``delta_files``, ``delta_lines``,
    and ``delta_bytes`` values.
    """
    if len(timeline) < 2:
        return {}
    first = timeline[0]["metrics"]
    last = timeline[-1]["metrics"]
    deltas: dict[str, dict[str, int]] = {}
    for cat in last:
        f0 = first.get(cat, {})
        f1 = last[cat]
        deltas[cat] = {
            "delta_files": f1.get("files", 0) - f0.get("files", 0),
            "delta_lines": f1.get("lines", 0) - f0.get("lines", 0),
            "delta_bytes": f1.get("bytes", 0) - f0.get("bytes", 0),
        }
    return deltas


def generate_plot(timeline: list[dict], output: Path) -> None:
    """Create a two-panel timeline chart (lines & filesize) and save as PNG."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    dates = [datetime.fromisoformat(s["date"]) for s in timeline]
    categories = list(FILE_CATEGORIES.values()) + [OTHER_LABEL]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    fig.suptitle("Repository Metrics Over Time", fontsize=14, fontweight="bold")

    for cat in categories:
        lines_data = [s["metrics"].get(cat, {}).get("lines", 0) for s in timeline]
        sizes_kb = [s["metrics"].get(cat, {}).get("bytes", 0) / 1024 for s in timeline]
        color = CATEGORY_COLORS[cat]

        ax1.fill_between(dates, lines_data, alpha=0.15, color=color)
        ax1.plot(
            dates,
            lines_data,
            marker="o",
            markersize=3,
            label=cat,
            color=color,
            linewidth=2,
        )

        ax2.fill_between(dates, sizes_kb, alpha=0.15, color=color)
        ax2.plot(
            dates,
            sizes_kb,
            marker="o",
            markersize=3,
            label=cat,
            color=color,
            linewidth=2,
        )

    ax1.set_ylabel("Lines of Code")
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)

    ax2.set_ylabel("File Size (KB)")
    ax2.set_xlabel("Date")
    ax2.legend(loc="upper left")
    ax2.grid(True, alpha=0.3)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d %H:%M"))
    ax2.xaxis.set_major_locator(mdates.AutoDateLocator())

    fig.autofmt_xdate()
    fig.tight_layout()

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    print(f"Plot saved to {output}", file=sys.stderr)


def generate_summary(timeline: list[dict]) -> str:
    """Generate a detailed Markdown metrics report."""
    latest = timeline[-1]["metrics"]
    latest_entry = timeline[-1]
    dt = datetime.fromisoformat(latest_entry["date"])

    parts: list[str] = []

    # -- Header --
    parts.append("## Repository Metrics Report\n")
    parts.append(f"**Commit:** `{latest_entry['short_sha']}`  ")
    parts.append(f"**Date:** {dt.strftime('%Y-%m-%d %H:%M')}  ")
    parts.append(f"**Sampled commits:** {len(timeline)}\n")

    # -- Section 1: Current snapshot --
    parts.append("### Current Snapshot\n")
    parts.append("| Category | Files | Lines | Size (KB) |")
    parts.append("|----------|------:|------:|----------:|")

    total_files = total_lines = total_bytes = 0
    for cat, data in latest.items():
        parts.append(
            f"| {cat} | {data['files']} | {data['lines']:,} | "
            f"{data['bytes'] / 1024:.1f} |"
        )
        total_files += data["files"]
        total_lines += data["lines"]
        total_bytes += data["bytes"]

    parts.append(
        f"| **Total** | **{total_files}** | **{total_lines:,}** | "
        f"**{total_bytes / 1024:.1f}** |\n"
    )

    # -- Section 2: Growth deltas --
    deltas = _compute_deltas(timeline)
    if deltas:
        first_dt = datetime.fromisoformat(timeline[0]["date"])
        parts.append("### Growth Since First Sampled Commit\n")
        parts.append(
            f"_From `{timeline[0]['short_sha']}` "
            f"({first_dt.strftime('%Y-%m-%d %H:%M')}) "
            f"to `{latest_entry['short_sha']}` "
            f"({dt.strftime('%Y-%m-%d %H:%M')})_\n"
        )
        parts.append("| Category | Files | Lines | Size (KB) |")
        parts.append("|----------|------:|------:|----------:|")
        td_files = td_lines = td_bytes = 0
        for cat, d in deltas.items():
            parts.append(
                f"| {cat} | {d['delta_files']:+d} | {d['delta_lines']:+,} | "
                f"{d['delta_bytes'] / 1024:+.1f} |"
            )
            td_files += d["delta_files"]
            td_lines += d["delta_lines"]
            td_bytes += d["delta_bytes"]
        parts.append(
            f"| **Total** | **{td_files:+d}** | **{td_lines:+,}** | "
            f"**{td_bytes / 1024:+.1f}** |\n"
        )

    # -- Section 3: Category breakdown percentages --
    parts.append("### Composition\n")
    if total_lines > 0:
        for cat, data in latest.items():
            pct = data["lines"] / total_lines * 100
            bar = "#" * int(pct / 2)
            parts.append(f"- **{cat}**: {pct:.1f}% `{bar}`")
    parts.append("")

    # -- Section 4: Timeline summary --
    parts.append("### Timeline Highlights\n")
    if len(timeline) >= 2:
        # Find peak lines commit
        peak_idx = max(
            range(len(timeline)),
            key=lambda i: sum(
                v.get("lines", 0) for v in timeline[i]["metrics"].values()
            ),
        )
        peak = timeline[peak_idx]
        peak_dt = datetime.fromisoformat(peak["date"])
        peak_lines = sum(v.get("lines", 0) for v in peak["metrics"].values())
        parts.append(
            f"- **Peak lines:** {peak_lines:,} at "
            f"`{peak['short_sha']}` ({peak_dt.strftime('%Y-%m-%d %H:%M')})"
        )

        # Largest single-commit jump in total lines
        max_jump = 0
        jump_idx = 0
        for i in range(1, len(timeline)):
            prev_total = sum(
                v.get("lines", 0) for v in timeline[i - 1]["metrics"].values()
            )
            cur_total = sum(v.get("lines", 0) for v in timeline[i]["metrics"].values())
            diff = cur_total - prev_total
            if abs(diff) > abs(max_jump):
                max_jump = diff
                jump_idx = i
        if max_jump != 0:
            j = timeline[jump_idx]
            j_dt = datetime.fromisoformat(j["date"])
            parts.append(
                f"- **Largest change:** {max_jump:+,} lines at "
                f"`{j['short_sha']}` ({j_dt.strftime('%Y-%m-%d %H:%M')})"
            )
    parts.append("")

    # -- Section 5: Per-category line counts over time --
    parts.append("### Lines of Code Over Time\n")
    parts.append("| Commit | Date | Python | Robot | Other | Total |")
    parts.append("|--------|------|-------:|------:|------:|------:|")
    # Show at most 10 evenly spaced rows
    indices = _thin_indices(len(timeline), 10)
    for i in indices:
        s = timeline[i]
        s_dt = datetime.fromisoformat(s["date"])
        py = s["metrics"].get("Python (.py)", {}).get("lines", 0)
        rb = s["metrics"].get("Robot (.robot)", {}).get("lines", 0)
        ot = s["metrics"].get(OTHER_LABEL, {}).get("lines", 0)
        parts.append(
            f"| `{s['short_sha']}` | {s_dt.strftime('%Y-%m-%d %H:%M')} "
            f"| {py:,} | {rb:,} | {ot:,} | {py + rb + ot:,} |"
        )
    parts.append("")

    parts.append("_Timeline plot available in job artifacts._")
    return "\n".join(parts)


def _thin_indices(total: int, max_rows: int) -> list[int]:
    """Return at most *max_rows* evenly spaced indices from 0..total-1."""
    if total <= max_rows:
        return list(range(total))
    step = total / max_rows
    out = [int(i * step) for i in range(max_rows)]
    if out[-1] != total - 1:
        out.append(total - 1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Repo metrics timeline")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="metrics",
        help="Output directory (default: metrics)",
    )
    parser.add_argument(
        "-n",
        "--max-points",
        type=int,
        default=30,
        help="Max commits to sample (default: 30)",
    )
    args = parser.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print("Collecting metrics across git history...", file=sys.stderr)
    timeline = collect_timeline(args.max_points)

    # Save raw data
    data_path = out / "repo_metrics.json"
    data_path.write_text(json.dumps(timeline, indent=2))
    print(f"Data saved to {data_path}", file=sys.stderr)

    # Generate plot
    generate_plot(timeline, out / "repo_timeline.png")

    # Generate summary
    summary = generate_summary(timeline)
    (out / "summary.md").write_text(summary)
    print(summary)


if __name__ == "__main__":
    main()
