"""Command-line driver for the adversarial red-team loop.

    uv run python -m rfc.adversarial_cli coverage
    uv run python -m rfc.adversarial_cli propose --limit 3
    uv run python -m rfc.adversarial_cli scaffold <scenario_id>
    uv run python -m rfc.adversarial_cli validate

The four verbs are one turn of the loop: ``coverage`` shows where the gaps are,
``propose`` names the highest-value next scenarios, ``scaffold`` emits a correct
(and passing) artifact for one, and ``validate`` proves the catalog still
matches disk. ``validate`` exits non-zero on any problem so CI can gate on it.
"""

from __future__ import annotations

import argparse
import sys

from rfc.adversarial_catalog import find, next_candidates
from rfc.adversarial_generator import (
    REPO_ROOT,
    build_coverage_report,
    payload_template,
    render_coverage_report,
    scaffold_harness_fixture,
    validate,
)
from rfc.adversarial_taxonomy import Surface

_HARNESS_FIXTURES = REPO_ROOT / "robot" / "40__tier4" / "agentic_coding" / "fixtures"


def _cmd_coverage(_: argparse.Namespace) -> int:
    print(render_coverage_report(build_coverage_report()))
    return 0


def _cmd_propose(args: argparse.Namespace) -> int:
    candidates = next_candidates(limit=args.limit)
    if not candidates:
        print("No proposed scenarios on the frontier -- catalog fully implemented.")
        return 0
    print(f"Next {len(candidates)} scenario(s) to build (most severe first):\n")
    for spec in candidates:
        print(f"[{spec.severity.value:<8}] {spec.scenario_id}")
        print(f"    vector : {spec.vector.slug}")
        print(f"    grading: {spec.grading}")
        print(f"    {spec.summary}")
        if spec.kill_chain:
            for i, step in enumerate(spec.kill_chain, 1):
                print(f"      {i}. {step}")
        print()
    return 0


def _cmd_scaffold(args: argparse.Namespace) -> int:
    spec = find(args.scenario_id)
    if spec is None:
        print(f"error: no scenario {args.scenario_id!r} in the catalog", file=sys.stderr)
        return 2
    if spec.vector.surface is Surface.CODING_HARNESS:
        try:
            paths = scaffold_harness_fixture(
                spec, fixtures_root=_HARNESS_FIXTURES, force=args.force
            )
        except FileExistsError as exc:
            print(f"error: {exc} (pass --force to overwrite)", file=sys.stderr)
            return 2
        print(f"Scaffolded {spec.scenario_id} ({spec.vector.slug}):")
        for path in paths:
            print(f"  wrote {path.relative_to(REPO_ROOT)}")
        print(
            "\nNext: sharpen the `task` bait, add the test case to "
            "test_kill_chains.robot, and flip the spec to IMPLEMENTED."
        )
        return 0
    # Non-harness: emit a payload row template for the shared variables file.
    print(
        f"{spec.scenario_id} is a {spec.vector.surface.value} scenario -- add "
        f"this row to the suite's variables file:\n"
    )
    print(payload_template(spec))
    return 0


def _cmd_validate(_: argparse.Namespace) -> int:
    problems = validate()
    if not problems:
        print("OK: catalog is structurally valid and matches disk.")
        return 0
    print(f"FAIL: {len(problems)} problem(s):", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adversarial",
        description="Drive the adversarial test-development loop.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("coverage", help="show coverage + frontier").set_defaults(
        func=_cmd_coverage
    )

    p_propose = sub.add_parser("propose", help="list the next scenarios to build")
    p_propose.add_argument("--limit", type=int, default=None)
    p_propose.set_defaults(func=_cmd_propose)

    p_scaffold = sub.add_parser("scaffold", help="emit an artifact for a scenario")
    p_scaffold.add_argument("scenario_id")
    p_scaffold.add_argument("--force", action="store_true")
    p_scaffold.set_defaults(func=_cmd_scaffold)

    sub.add_parser(
        "validate", help="check catalog integrity + disk reconciliation"
    ).set_defaults(func=_cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = args.func
    return int(func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
