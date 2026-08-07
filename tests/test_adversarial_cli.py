"""Tests for rfc.adversarial_cli (the loop's command surface)."""

from __future__ import annotations

import pytest

from rfc.adversarial_cli import main


def test_coverage_runs_and_prints(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["coverage"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Adversarial coverage" in out


def test_propose_lists_candidates(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["propose", "--limit", "2"])
    out = capsys.readouterr().out
    assert rc == 0
    # Two blocks, each naming a vector.
    assert out.count("vector :") == 2


def test_scaffold_unknown_scenario_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["scaffold", "does_not_exist"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "no scenario" in err


def test_scaffold_non_harness_prints_payload_template(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A known proposed model-under-test scenario.
    rc = main(["scaffold", "unicode_tag_guardrail_bypass"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "add\nthis row" in out or "add " in out
    assert "vector:" in out  # yaml payload row


def test_validate_returns_int_exit_code() -> None:
    rc = main(["validate"])
    assert rc in (0, 1)


def test_no_subcommand_is_an_error() -> None:
    with pytest.raises(SystemExit):
        main([])
