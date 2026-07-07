"""Regression guard: Robot `Test Timeout` must not fight the LLM HTTP budget.

Background (robotframework-chat#620): on slow/local Ollama hardware, suites
reported ~75% `FAILED` because the Robot ``Test Timeout`` (2-5 min) tripped long
before a single ``generate()`` call could finish — the per-request HTTP budget
(``OLLAMA_TIMEOUT``, default 5400s / 90 min) is the real ceiling for one LLM
response. When the test timeout is the *smaller* of the two, Robot aborts a
request the HTTP client is still legitimately awaiting.

Invariant enforced here: every LLM-driven suite's ``Test Timeout`` (and any
per-keyword ``[Timeout]``) is >= the HTTP budget, so Robot never wins that race.

The docker code-execution suites are excluded: their ``Test Timeout`` bounds
container command execution (deterministic, fast), not an LLM call, and a hang
there *should* fail fast. The LLM pre-flight those suites run lives in Suite
Setup, which ``Test Timeout`` does not cover.
"""

from __future__ import annotations

import re
from pathlib import Path

from rfc.constants import DEFAULT_TIMEOUT

ROBOT_ROOT = Path(__file__).parent.parent / "robot"

# Floor = the single-call HTTP budget. Sourced from the same constant the
# Ollama client defaults to, so the two move together.
TIMEOUT_FLOOR_SECONDS = DEFAULT_TIMEOUT  # 5400s / 90 min

# Suites whose Test Timeout bounds container execution, not LLM generation.
EXCLUDED_SUITES = {
    ROBOT_ROOT / "40__tier4" / "docker" / "python" / "__init__.robot",
    ROBOT_ROOT / "40__tier4" / "docker" / "c" / "__init__.robot",
    ROBOT_ROOT / "40__tier4" / "docker" / "bash" / "__init__.robot",
    ROBOT_ROOT / "40__tier4" / "docker" / "rust" / "__init__.robot",
    ROBOT_ROOT / "40__tier4" / "docker" / "shell" / "__init__.robot",
}

_UNIT_SECONDS = {
    "second": 1,
    "seconds": 1,
    "sec": 1,
    "secs": 1,
    "s": 1,
    "minute": 60,
    "minutes": 60,
    "min": 60,
    "mins": 60,
    "m": 60,
    "hour": 3600,
    "hours": 3600,
    "h": 3600,
}

# "Test Timeout" setting or "[Timeout]" keyword setting, value to end of line.
_TIMEOUT_LINE = re.compile(
    r"^(?:Test Timeout|\s*\[Timeout\])\s+(.+?)\s*$",
    re.IGNORECASE,
)


def _to_seconds(value: str) -> float | None:
    """Parse a Robot time string ('2 minutes', '90 seconds', '1h 30m') to seconds.

    Returns None for values that are variables (e.g. ``${X}``) — those are
    resolved at runtime and not statically checkable here.
    """
    value = value.strip()
    if "${" in value or "%{" in value:
        return None
    total = 0.0
    matched = False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([a-zA-Z]+)", value):
        unit_l = unit.lower()
        if unit_l not in _UNIT_SECONDS:
            return None
        total += float(num) * _UNIT_SECONDS[unit_l]
        matched = True
    # Bare number => seconds (Robot's default unit).
    if not matched:
        try:
            return float(value)
        except ValueError:
            return None
    return total


def _collect_timeout_settings() -> list[tuple[Path, int, str, float]]:
    """Return (path, lineno, raw_value, seconds) for every static timeout setting."""
    found: list[tuple[Path, int, str, float]] = []
    for path in sorted(ROBOT_ROOT.rglob("*.robot")):
        if path in EXCLUDED_SUITES:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            m = _TIMEOUT_LINE.match(line)
            if not m:
                continue
            secs = _to_seconds(m.group(1))
            if secs is None:
                continue
            found.append((path, lineno, m.group(1).strip(), secs))
    return found


def test_robot_root_exists() -> None:
    assert ROBOT_ROOT.is_dir(), f"robot/ not found at {ROBOT_ROOT}"


def test_timeout_floor_matches_http_budget() -> None:
    """The floor tracks the Ollama HTTP default so they cannot silently diverge."""
    assert TIMEOUT_FLOOR_SECONDS == 5400


def test_some_llm_suites_declare_a_timeout() -> None:
    """Guard against the regex silently matching nothing (e.g. layout change)."""
    settings = _collect_timeout_settings()
    assert len(settings) >= 50, (
        f"expected many LLM-suite Test Timeout settings, found {len(settings)} "
        "— has the robot/ layout or this parser drifted?"
    )


def test_llm_test_timeouts_at_or_above_http_budget() -> None:
    """No LLM suite may abort a request the HTTP client is still awaiting (#620)."""
    offenders = [
        f"{path.relative_to(ROBOT_ROOT)}:{lineno}: "
        f"timeout {raw!r} = {secs:.0f}s < floor {TIMEOUT_FLOOR_SECONDS}s"
        for path, lineno, raw, secs in _collect_timeout_settings()
        if secs < TIMEOUT_FLOOR_SECONDS
    ]
    assert not offenders, (
        "Robot Test Timeout below the Ollama HTTP budget — these will FAIL on "
        "slow/local hardware before the model can answer (#620):\n  "
        + "\n  ".join(offenders)
    )
