#!/usr/bin/env python3
"""CI guard: every battery scenario meets the RFC-007 quality bar (issue #219).

RFC-007 (section 3) states the single most important quality-bar rule: *a grader
that cannot fail the bad solution is broken* -- a "100% pass" scoreboard column is
indistinguishable from a grader that returns PASS unconditionally. Section 7 turns
that from prose into a mechanical, across-the-board check, a sibling to
``check_rfc_index.py`` / ``check_agent_signoffs.py`` / ``check_submodule_ownership.py``:
every sandbox scenario manifest must earn its slot by proving its grader
discriminates good from bad.

This guard validates every tier:4 sandbox scenario
(``core/robot/40__tier4/agentic_coding/fixtures/sandbox/*/scenario.yaml``) against
four requirements. One is *static* plus manifest well-formedness (read the
manifest); three are *executed* by running the scenario's ``test_command``
host-side (no Docker needed -- the existing scenarios' ``test_command`` is a plain
``python -m unittest`` run):

  1. **Failing-first proof** (executed) -- ``test_command`` FAILS on the seeded
     ``repo/`` as given. A task that is green at t=0 measures nothing.
  2. **Reference variant** (executed) -- applying the declared ``reference_variant``
     agent makes the composite grade PASS: ``test_command`` succeeds *and* no file
     churn outside ``allowed_paths``. Proves the task is solvable and the grader
     can say PASS.
  3. **Negative variant** (executed) -- applying the declared ``negative_variant``
     agent is REJECTED by the composite grade (tests fail *or* unexpected churn).
     This is the keystone: it proves the grader can fail a bad solution.
  4. **Bounded runtime** (static) -- the manifest declares a positive
     ``timeout_seconds`` within the harness wall-clock cap
     (:data:`MAX_TIMEOUT_SECONDS`), so CI cost is bounded and ``latency_ms`` is
     comparable across harnesses.

The grader modelled here is the *composite* one the sandbox harness applies
(``rfc.agent_sandbox``): a variant is accepted only when its tests pass **and** it
leaves no unexpected file churn. This matters -- one existing scenario's negative
variant (``tier4_bug_fix``/``churn``) still passes the tests and is caught purely
by the churn check; a checker that equated "rejected" with "tests fail" would
wrongly report that grader as non-discriminating.

Churn accounting is delegated to :mod:`rfc.churn_manifest` -- the single owned
manifest/exclusion policy shared with the container-side grader
(``rfc.agent_sandbox``) so the two cannot drift on symlinks or bytecode (#248,
#231). That module is stdlib-only, so importing it keeps this guard's "runs in
the monorepo-only ``modules/ops`` tree, no Docker daemon" property; the guard
walks a seeded workspace host-side with
:func:`~rfc.churn_manifest.manifest_from_dir` (the shell rendering only runs
inside the container).

Usage (run under core's environment so ``rfc.churn_manifest`` imports):
  uv run --project core python modules/ops/scripts/check_battery_scenarios.py
  uv run --project core python modules/ops/scripts/check_battery_scenarios.py --static-only
  uv run --project core python modules/ops/scripts/check_battery_scenarios.py --scenario tier4_bug_fix
  uv run --project core python modules/ops/scripts/check_battery_scenarios.py --root path/to/sandbox

Set ``RFC_BATTERY_SKIP_EXEC=1`` to run only the static checks (an escape hatch for
environments that cannot execute the scenario ``test_command``); the guard also
skip-and-logs the executed checks when the ``test_command`` interpreter is absent.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from rfc.churn_manifest import diff_manifests, filter_unexpected, manifest_from_dir

# core/robot/40__tier4/agentic_coding/fixtures/sandbox -- relative to the repo root
# (this file lives at modules/ops/scripts/, so parents[3] is the repo root).
DEFAULT_SANDBOX_ROOT = (
    Path(__file__).resolve().parents[3]
    / "core"
    / "robot"
    / "40__tier4"
    / "agentic_coding"
    / "fixtures"
    / "sandbox"
)

# The sandbox harness (config/local_agents.yaml -> SandboxLimits.wall_clock_seconds)
# enforces a 300s wall-clock cap per run; a declared per-scenario timeout above it
# could never actually be honoured, so that is the RFC bound this guard enforces.
MAX_TIMEOUT_SECONDS = 300
# Independently bound this guard's OWN runtime: no single test_command / agent
# invocation may run longer than this, whatever a manifest declares.
CHECKER_HARD_CAP_SECONDS = 60
# The container path the scenarios' test_command is written against; rewritten to
# the host temp dir when the guard runs a scenario without Docker.
WORKSPACE_TOKEN = "/workspace"

_REQUIRED_SCENARIO_KEYS = ("scenario_id", "task", "test_command")
# Discovery is deliberately one level deep to match the harness, which resolves
# scenarios flat-by-name (``_scenarios_root / scenario_id``, agent_sandbox.py
# 265-273) and never recurses into a seed ``repo/``. A ``scenario.yaml`` nested
# deeper than that flat layout is therefore never graded; :func:`stray_scenarios`
# fails loudly on it (issue #250) so it can neither silently escape the bar
# (#232) nor be silently swept into the graded set (#250 over-reach). A file that
# is genuinely fixture DATA -- a seed ``repo/`` that legitimately ships a
# battery-shaped ``scenario.yaml`` -- is exempted only by adding its root-relative
# POSIX path here, a reviewed, explicit allowlist (never a silent default).
STRAY_YAML_ALLOWLIST: frozenset[str] = frozenset()


@dataclass(frozen=True)
class BatteryScenario:
    """One battery scenario manifest, plus the quality-bar declarations."""

    scenario_id: str
    task: str
    test_command: str
    allowed_paths: tuple[str, ...]
    agents: dict[str, str]
    reference_variant: str | None
    negative_variant: str | None
    timeout_seconds: int | None
    root: Path

    @property
    def repo_dir(self) -> Path:
        return self.root / "repo"

    def agent_script(self, variant: str) -> Path:
        return self.root / self.agents[variant]

    def effective_timeout(self) -> int:
        """The per-command budget the guard actually enforces (bar-independent)."""
        declared = (
            self.timeout_seconds if self.timeout_seconds else CHECKER_HARD_CAP_SECONDS
        )
        return max(1, min(declared, CHECKER_HARD_CAP_SECONDS))


@dataclass(frozen=True)
class GradeOutcome:
    """The composite grade the sandbox harness applies to one variant run."""

    tests_exit_code: int
    unexpected_paths: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return self.tests_exit_code == 0 and not self.unexpected_paths

    @property
    def rejected(self) -> bool:
        return not self.accepted

    def reason(self) -> str:
        parts = []
        if self.tests_exit_code != 0:
            parts.append(f"tests exit={self.tests_exit_code}")
        if self.unexpected_paths:
            parts.append(f"unexpected churn {list(self.unexpected_paths)}")
        return "; ".join(parts) if parts else "tests pass, no churn"


# --- manifest loading (raises only on an unparseable manifest) ---------------


def load_scenario(scenario_dir: Path | str) -> BatteryScenario:
    """Parse and minimally validate a scenario fixture directory.

    Raises ``ValueError`` when the manifest is structurally unusable (missing
    file, missing a required key, no ``repo/``, a dangling agent script). Bar
    violations (missing reference/negative/timeout) are *not* raised here -- they
    are reported by :func:`static_violations` so one call surfaces them all.
    """
    root = Path(scenario_dir)
    yaml_path = root / "scenario.yaml"
    if not yaml_path.is_file():
        raise ValueError(f"scenario missing {yaml_path}")
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"scenario {yaml_path} is not a mapping")

    missing = [k for k in _REQUIRED_SCENARIO_KEYS if not raw.get(k)]
    if missing:
        raise ValueError(f"scenario {yaml_path} missing keys: {missing}")
    if not (root / "repo").is_dir():
        raise ValueError(f"scenario {root.name} has no repo/ directory to seed")

    agents = {str(k): str(v) for k, v in (raw.get("agents") or {}).items()}
    for variant, rel in agents.items():
        if not (root / rel).is_file():
            raise ValueError(
                f"scenario {root.name}: agent variant {variant!r} points at "
                f"missing script {rel!r}"
            )

    timeout = raw.get("timeout_seconds")
    return BatteryScenario(
        scenario_id=str(raw["scenario_id"]),
        task=str(raw["task"]),
        test_command=str(raw["test_command"]),
        allowed_paths=tuple(str(p) for p in raw.get("allowed_paths") or ()),
        agents=agents,
        reference_variant=(
            str(raw["reference_variant"]) if raw.get("reference_variant") else None
        ),
        negative_variant=(
            str(raw["negative_variant"]) if raw.get("negative_variant") else None
        ),
        timeout_seconds=int(timeout) if isinstance(timeout, int) else None,
        root=root,
    )


# --- static checks (rule 4 + manifest well-formedness) -----------------------


def static_violations(scenario: BatteryScenario) -> list[str]:
    """Manifest-only violations: reference/negative declared + bounded runtime."""
    v: list[str] = []
    sid = scenario.scenario_id

    ref = scenario.reference_variant
    if not ref:
        v.append(f"{sid}: no reference_variant declared (rule 2)")
    elif ref not in scenario.agents:
        v.append(
            f"{sid}: reference_variant {ref!r} is not an agent variant "
            f"(have {sorted(scenario.agents)})"
        )

    neg = scenario.negative_variant
    if not neg:
        v.append(f"{sid}: no negative_variant declared (rule 3)")
    elif neg not in scenario.agents:
        v.append(
            f"{sid}: negative_variant {neg!r} is not an agent variant "
            f"(have {sorted(scenario.agents)})"
        )

    if ref and neg and ref == neg:
        v.append(
            f"{sid}: reference_variant and negative_variant are both {ref!r} -- "
            "a scenario cannot grade the same variant as good and bad"
        )

    t = scenario.timeout_seconds
    if t is None:
        v.append(f"{sid}: no bounded timeout_seconds declared (rule 4)")
    elif t <= 0:
        v.append(f"{sid}: timeout_seconds must be positive, got {t} (rule 4)")
    elif t > MAX_TIMEOUT_SECONDS:
        v.append(
            f"{sid}: timeout_seconds {t} exceeds the harness wall-clock cap "
            f"{MAX_TIMEOUT_SECONDS} (rule 4)"
        )

    return v


# --- execution checks (rules 1-3) --------------------------------------------


def interpreter_available(test_command: str) -> bool:
    """Whether the leading token of test_command resolves to a runnable program.

    Lets the guard skip-and-log the executed checks where the scenario's runtime
    is absent (mirroring the harness's Docker-unavailable skip), rather than
    reporting a spurious violation.
    """
    token = test_command.strip().split()
    return bool(token) and shutil.which(token[0]) is not None


def _seed_into(scenario: BatteryScenario, dest: Path) -> None:
    shutil.copytree(scenario.repo_dir, dest, dirs_exist_ok=True)
    for junk in dest.rglob("__pycache__"):
        shutil.rmtree(junk, ignore_errors=True)


def _run_test_command(scenario: BatteryScenario, workdir: Path) -> int:
    """Run the scenario's test_command in workdir; return its exit code.

    A timeout is reported as 124 (the ``timeout(1)`` convention) -- a non-zero
    "did not pass", which is the correct grade for an over-budget run.
    """
    command = scenario.test_command.replace(WORKSPACE_TOKEN, str(workdir))
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=scenario.effective_timeout(),
        )
        return proc.returncode
    except subprocess.TimeoutExpired:
        return 124


def run_seed_tests(scenario: BatteryScenario) -> int:
    """Rule 1: exit code of test_command on the untouched seed (non-zero = red)."""
    tmp = Path(tempfile.mkdtemp(prefix=f"battery-{scenario.scenario_id}-seed-"))
    try:
        _seed_into(scenario, tmp)
        return _run_test_command(scenario, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def grade_variant(scenario: BatteryScenario, variant: str) -> GradeOutcome:
    """Seed, run one agent variant, then apply the composite grade (tests + churn).

    Churn is diffed *before* the tests run (as the harness does), so bytecode a
    test run would emit never counts against the variant.
    """
    tmp = Path(tempfile.mkdtemp(prefix=f"battery-{scenario.scenario_id}-{variant}-"))
    try:
        _seed_into(scenario, tmp)
        before = manifest_from_dir(tmp)
        try:
            subprocess.run(
                ["sh", str(scenario.agent_script(variant))],
                cwd=str(tmp),
                capture_output=True,
                text=True,
                timeout=scenario.effective_timeout(),
            )
        except subprocess.TimeoutExpired:
            # An agent that never returns is a rejected run; force a churn signal
            # so the grade is unambiguously "rejected".
            return GradeOutcome(
                tests_exit_code=124, unexpected_paths=("<agent-timeout>",)
            )
        after = manifest_from_dir(tmp)
        unexpected = filter_unexpected(
            diff_manifests(before, after), scenario.allowed_paths
        )
        tests_exit = _run_test_command(scenario, tmp)
        return GradeOutcome(tests_exit_code=tests_exit, unexpected_paths=unexpected)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def execution_violations(scenario: BatteryScenario) -> list[str]:
    """Rules 1-3, by running test_command host-side. Skip-and-logs if no runtime.

    Assumes the static declarations are present; the caller runs static checks
    first and only reaches here for a manifest that named its variants.
    """
    sid = scenario.scenario_id
    if not interpreter_available(scenario.test_command):
        interp = scenario.test_command.strip().split()[:1]
        print(
            f"  - {sid}: SKIP executed checks (rules 1-3): interpreter "
            f"{interp} not on PATH",
            file=sys.stderr,
        )
        return []

    v: list[str] = []

    # Rule 1 -- failing-first proof.
    seed_exit = run_seed_tests(scenario)
    if seed_exit == 0:
        v.append(
            f"{sid}: no failing-first proof (rule 1) -- test_command passes on the "
            "seeded repo, so a no-op agent would score PASS"
        )

    # Rule 2 -- reference variant must be accepted by the composite grade.
    ref = scenario.reference_variant
    if ref and ref in scenario.agents:
        grade = grade_variant(scenario, ref)
        if not grade.accepted:
            v.append(
                f"{sid}: reference_variant {ref!r} is not accepted by the grader "
                f"(rule 2) -- {grade.reason()}"
            )

    # Rule 3 -- negative variant must be rejected by the composite grade.
    neg = scenario.negative_variant
    if neg and neg in scenario.agents:
        grade = grade_variant(scenario, neg)
        if grade.accepted:
            v.append(
                f"{sid}: negative_variant {neg!r} is ACCEPTED by the grader "
                "(rule 3) -- the grader cannot fail the bad solution, so the "
                "scoreboard column is meaningless"
            )

    return v


# --- orchestration -----------------------------------------------------------


def check_scenario(scenario_dir: Path, *, static_only: bool = False) -> list[str]:
    """All violations for one scenario dir (manifest errors become violations)."""
    try:
        scenario = load_scenario(scenario_dir)
    except ValueError as exc:
        return [f"{Path(scenario_dir).name}: {exc}"]

    violations = static_violations(scenario)
    if static_only or os.environ.get("RFC_BATTERY_SKIP_EXEC") == "1":
        return violations
    # Only run the executed checks when the manifest at least named its variants;
    # otherwise the static output already tells the author what to fix.
    if scenario.reference_variant or scenario.negative_variant:
        violations += execution_violations(scenario)
    return violations


def discover_scenarios(root: Path) -> list[Path]:
    """The graded scenario directories: exactly the flat ``root/*/scenario.yaml``.

    Discovery is one level deep (``glob``, not ``rglob``) so it matches the
    harness, which resolves scenarios flat-by-name (``_scenarios_root /
    scenario_id``, ``rfc.agent_sandbox`` lines 265-273) and never recurses into a
    seed ``repo/``. A ``scenario.yaml`` nested deeper is deliberately NOT graded
    here; :func:`stray_scenarios` flags it loudly (issue #250) so a nested
    manifest can neither silently escape the bar (#232) nor be silently swept into
    the graded set (the #245 phantom regression).
    """
    if not root.is_dir():
        return []
    return sorted(p.parent for p in root.glob("*/scenario.yaml") if p.is_file())


def stray_scenarios(
    root: Path, *, allowlist: frozenset[str] = STRAY_YAML_ALLOWLIST
) -> list[Path]:
    """``scenario.yaml`` files nested below the flat layout, minus the allowlist.

    Any ``scenario.yaml`` whose parent is not a direct child of ``root`` over-
    reaches the harness's flat load surface. Rather than silently grading it (the
    #250 over-reach) or silently dropping it (the #232 escape), the guard fails
    loudly and names each offending path. A file that is genuinely fixture DATA --
    a seed ``repo/`` that legitimately ships a battery-shaped ``scenario.yaml`` --
    is exempted only by its root-relative POSIX path appearing in ``allowlist``
    (default :data:`STRAY_YAML_ALLOWLIST`), a reviewed, explicit escape hatch.
    """
    if not root.is_dir():
        return []
    graded = set(discover_scenarios(root))
    strays: list[Path] = []
    for path in root.rglob("scenario.yaml"):
        if not path.is_file() or path.parent in graded:
            continue
        if path.relative_to(root).as_posix() in allowlist:
            continue
        strays.append(path)
    return sorted(strays)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail (exit 1) on any quality-bar violation. Default behaviour.",
    )
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="Run only the manifest (static) checks; skip executing test_command.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_SANDBOX_ROOT,
        help=f"Sandbox scenarios root (default: {DEFAULT_SANDBOX_ROOT}).",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help="Check only this scenario id (directory name) under --root.",
    )
    args = parser.parse_args(argv)

    root: Path = args.root

    # Discovery integrity (issue #250): a scenario.yaml nested below the flat
    # root/<id>/scenario.yaml layout over-reaches the harness's flat load surface
    # (agent_sandbox.py:265-273). Fail loudly and name each path rather than
    # silently grading fixture data or silently dropping a nested manifest.
    strays = stray_scenarios(root)
    if strays:
        print(
            "Battery scenario discovery: scenario.yaml nested below the flat "
            "root/<id>/scenario.yaml layout (the harness loads scenarios "
            "flat-by-name and never recurses into a seed repo/):",
            file=sys.stderr,
        )
        for stray in strays:
            print(f"  - {stray}", file=sys.stderr)
        print(
            "Relocate each to a top-level scenario directory under the sandbox "
            "root, or -- if it is intentional fixture DATA -- add its root-relative "
            "path to STRAY_YAML_ALLOWLIST in check_battery_scenarios.py.",
            file=sys.stderr,
        )
        return 1

    scenarios = discover_scenarios(root)
    if args.scenario is not None:
        scenarios = [d for d in scenarios if d.name == args.scenario]
        if not scenarios:
            print(
                f"battery quality bar: no scenario {args.scenario!r} under {root}",
                file=sys.stderr,
            )
            return 1
    if not scenarios:
        print(f"battery quality bar: no scenarios found under {root}", file=sys.stderr)
        return 1

    all_violations: list[str] = []
    for scenario_dir in scenarios:
        all_violations += check_scenario(scenario_dir, static_only=args.static_only)

    if all_violations:
        print(
            "Battery scenario quality-bar violations (see RFC-007 section 7):",
            file=sys.stderr,
        )
        for violation in all_violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1

    # Honest mode label: RFC_BATTERY_SKIP_EXEC=1 skips the executed checks in
    # check_scenario exactly as --static-only does, so the summary must name
    # only the checks that actually ran (issue #233), not always claim
    # "static+executed".
    static_only = args.static_only or os.environ.get("RFC_BATTERY_SKIP_EXEC") == "1"
    mode = "static" if static_only else "static+executed"
    print(f"battery quality bar: ok ({len(scenarios)} scenario(s), {mode} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
