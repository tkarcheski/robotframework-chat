from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'metrics' / 'entrypoint.sh'


def run_bash(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['bash', '-lc', script], capture_output=True, text=True)


def test_relative_path_handles_results_root() -> None:
    proc = run_bash(
        f"export RESULTS_DIR=/tmp/results OUTPUT_DIR=/tmp/out; source '{SCRIPT}'; relative_path /tmp/results /tmp/results"
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == '.'


def test_generate_index_lists_root_and_nested_dashboards(tmp_path: Path) -> None:
    output_dir = tmp_path / 'metrics'
    output_dir.mkdir()
    (output_dir / 'root-dashboard.html').write_text('<html>root</html>')
    (output_dir / 'accounting').mkdir()
    (output_dir / 'accounting' / 'dashboard.html').write_text('<html>nested</html>')

    proc = run_bash(
        f"export OUTPUT_DIR='{output_dir}' RESULTS_DIR=/tmp/results; source '{SCRIPT}'; generate_index; cat '{output_dir / 'index.html'}'"
    )

    assert proc.returncode == 0, proc.stderr
    html = proc.stdout
    assert 'href=\"root-dashboard.html\"' in html
    assert '>root<' in html
    assert 'href=\"accounting/dashboard.html\"' in html
    assert '>accounting<' in html


def test_generate_index_does_not_overwrite_existing_root_dashboard(tmp_path: Path) -> None:
    output_dir = tmp_path / 'metrics'
    output_dir.mkdir()
    root_index = output_dir / 'index.html'
    root_index.write_text('<html>dashboard</html>')
    (output_dir / 'suite-a').mkdir()
    (output_dir / 'suite-a' / 'index.html').write_text('<html>suite</html>')

    proc = run_bash(
        f"export OUTPUT_DIR='{output_dir}' RESULTS_DIR=/tmp/results; source '{SCRIPT}'; generate_index; printf '%s\\n' '---ROOT---'; cat '{root_index}'; printf '%s\\n' '---NAV---'; cat '{output_dir / 'navigation.html'}'"
    )

    assert proc.returncode == 0, proc.stderr
    assert '---ROOT---\n<html>dashboard</html>' in proc.stdout
    assert '---NAV---' in proc.stdout
    assert 'href=\"suite-a/index.html\"' in proc.stdout
