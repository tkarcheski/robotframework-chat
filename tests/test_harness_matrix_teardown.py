"""Robot-layer test for the harness_matrix session teardown (#213).

The live ``harness_matrix`` suite brackets every leg in an ``agentic_harnesses``
session and closes it in a test teardown. Robot teardowns run even when the test
body fails, so the closing ``outcome`` must be *derived* from ``${TEST STATUS}``
— a hardcoded ``success`` would close a crashed or red live leg as a false
success, corrupting the spine that #169/#164 read to judge run outcomes.

The keyword library's own outcome handling is already proven correct
(``test_harness_keywords.py::TestFailureEnvelope``). The gap this file guards is
one layer up: the robot resource keyword ``End Session And Cleanup`` (in
``robot/40__tier4/harness_matrix/harness_matrix.resource``) must pass
``outcome=failed`` when the test failed and ``outcome=success`` when it passed.

That derivation reads Robot's automatic ``${TEST STATUS}`` variable, which only
exists inside a real teardown — so it cannot be unit-tested from Python. Instead
this runs a tiny, hermetic Robot suite in-process (``robot.run``) that imports
the *real* resource keyword: one passing leg, one deliberately-failing leg, and
one leg that skips *after* opening its session bracket, each opening a real
``rfc harness`` session bracket against its own throwaway sqlite spine (no agent,
no models, no tokens — only ``Run Agent Task`` spends anything, and none of the
legs call it). After the run each spine row is inspected: the passing leg must
close ``success``, the failing leg must close ``failed``, and the skipped leg
must close ``partial`` — never a false ``success`` (#254, the SKIP branch of the
#213 outcome-honesty class).
"""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

from robot import run as robot_run

_RESOURCE = (
    Path(__file__).resolve().parent.parent
    / "robot"
    / "40__tier4"
    / "harness_matrix"
    / "harness_matrix.resource"
)

# A hermetic twin of a matrix leg: open a real session bracket (no agent run),
# then let the body pass or fail so the teardown sees the matching TEST STATUS.
# @@TOKENS@@ are substituted with absolute paths before the suite is written.
_SUITE_TEMPLATE = """\
*** Settings ***
Library     rfc.harness_keywords.HarnessKeywords
Resource    @@RESOURCE@@
Library     OperatingSystem

*** Test Cases ***
Passing Leg Closes The Spine As Success
    Open Hermetic Leg    @@PASS_DB@@
    Log    green body: the leg conformed
    [Teardown]    End Session And Cleanup    ${WS}

Failing Leg Closes The Spine As Failed
    Open Hermetic Leg    @@FAIL_DB@@
    Fail    forced red body: a live leg's assertions blew up
    [Teardown]    End Session And Cleanup    ${WS}

Skipping Leg After Session Open Closes The Spine As Partial
    Open Hermetic Leg    @@SKIP_DB@@
    Skip    post-open skip: a mid-body probe bailed after the session bracket opened
    [Teardown]    End Session And Cleanup    ${WS}

*** Keywords ***
Open Hermetic Leg
    [Documentation]    Throwaway git repo + a session bracket on an external
    ...                spine DB that outlives the workspace the teardown deletes.
    [Arguments]    ${db_url}
    ${root}=    Evaluate    tempfile.mkdtemp(prefix="teardown-leg-")    modules=tempfile
    ${ws}=    Create Harness Workspace    ${root}
    Set Test Variable    ${WS}    ${ws}
    Start Harness Session    tool=opencode    workspace=${ws}[path]    database_url=${db_url}
"""


def _spine_row(db_path: Path) -> tuple[str, str]:
    """Return ``(outcome, ended_at)`` for the single harness row in ``db_path``."""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT outcome, ended_at FROM agentic_harnesses"
        ).fetchall()
    assert len(rows) == 1, f"expected exactly one spine row, got {rows!r}"
    return rows[0][0], rows[0][1]


def _run_twin_suite(tmp_path: Path) -> tuple[int, dict[str, Path]]:
    """Write the hermetic twin suite into ``tmp_path``, run it in-process, and
    return ``(failed_count, {leg: spine_db_path})`` for the pass/fail/skip legs.

    ``robot.run`` returns the count of *failed* tests; a skipped leg is neither
    a pass nor a failure, so only the one deliberately-failing leg counts.
    """
    dbs = {
        "pass": tmp_path / "pass_spine.db",
        "fail": tmp_path / "fail_spine.db",
        "skip": tmp_path / "skip_spine.db",
    }
    suite = tmp_path / "harness_matrix_teardown_twin.robot"
    suite.write_text(
        _SUITE_TEMPLATE.replace("@@RESOURCE@@", str(_RESOURCE))
        .replace("@@PASS_DB@@", f"sqlite:///{dbs['pass']}")
        .replace("@@FAIL_DB@@", f"sqlite:///{dbs['fail']}")
        .replace("@@SKIP_DB@@", f"sqlite:///{dbs['skip']}")
    )
    failed = robot_run(
        str(suite),
        outputdir=str(tmp_path),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    return failed, dbs


def test_teardown_records_true_outcome_per_test_status(tmp_path: Path) -> None:
    """A failing leg closes its spine row ``failed``; a passing leg ``success``.

    This is the #213 regression: before the fix the teardown hardcoded
    ``outcome=success``, so the failing leg below would have closed ``success``.
    """
    failed, dbs = _run_twin_suite(tmp_path)
    assert failed == 1, "expected exactly the one deliberately-failing leg to fail"

    pass_outcome, pass_ended = _spine_row(dbs["pass"])
    assert pass_outcome == "success"
    assert pass_ended != ""  # row was actually closed, not left dangling

    fail_outcome, fail_ended = _spine_row(dbs["fail"])
    assert fail_outcome == "failed", (
        "failed leg must close its spine row as 'failed', not a false 'success' (#213)"
    )
    assert fail_ended != ""


def test_teardown_maps_post_open_skip_to_partial_not_success(tmp_path: Path) -> None:
    """A leg skipped *after* opening its session closes ``partial``, not ``success``.

    This pins #254: the binary ``FAIL`` -> ``failed`` / else -> ``success``
    derivation folded ``SKIP`` into ``success``, so a leg that skipped after its
    session bracket opened closed a non-successful run as a false ``success`` —
    the #213 outcome-honesty class via the skip branch. The three-way derivation
    maps ``SKIP`` -> ``partial`` explicitly.
    """
    failed, dbs = _run_twin_suite(tmp_path)
    # The skip is not a failure: robot's failed count stays at the one red leg.
    assert failed == 1, "a post-open skip must not register as a failed test"

    skip_outcome, skip_ended = _spine_row(dbs["skip"])
    assert skip_outcome == "partial", (
        "a leg skipped after its session bracket opened must close 'partial', "
        "not a false 'success' (#254)"
    )
    assert skip_ended != ""  # row was actually closed, not left dangling
