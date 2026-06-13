"""Robot Framework listener: generative observation and flow control.

Phase 3 of the Agentic Stack Tracker.

**Observe mode (#358, read-only).** When a suite is tagged
``generative:observe``, this listener prompts a configured LLM at hook
events (``start_suite``, and ``end_test`` when the test failed) and
records every exchange in the ``agentic_decisions`` table with full
provenance and ``applied=0`` — suggestions only, the execution
behaviour of the suite is never changed.

**Flow mode (#359, active, explicit opt-in).** When a suite is tagged
``generative:flow``, the listener prompts the LLM on each test failure
and may *apply* ``proposed_action in {skip, retry, fork}``:

- ``skip``  — the next test is marked SKIPPED (its body is replaced
  with a single ``Skip`` keyword naming the decision id).
- ``retry`` — the failed test is re-run once (a tagged copy is
  inserted right after it; copies are never retried again).
- ``fork``  — the failed test is re-run once per model in
  ``RFC_GENERATIVE_FORK_MODELS`` (comma-separated). Each fork copy is
  tagged ``generative_fork:true`` (so its ``test_runs`` row is
  identifiable) plus ``generative_fork:model:<model>``, and gets a
  ``Set LLM Model`` keyword prepended.

**Mutate mode (#360, active, explicit opt-in).** When a suite is tagged
``generative:mutate``, the listener prompts the LLM after each opted-in
test PASSES (mutating passing tests is the point: it probes over-lenient
assertions; failed tests are not mutated because Robot stops at the
first failing keyword, so an appended assertion would never execute)
for ONE new assertion. The assertion is appended to a deep copy of the
test which is inserted right after the original, so it executes inline
and gets its own sibling ``test_runs`` row from the regular results
listener. Synthetic test name: ``<original>::mutated::<short_hash>``;
tagged ``mutated:true`` (copies never re-mutate). Safety rails:

- the assertion keyword must come from a small allow-list of
  deterministic BuiltIn assertions (``ALLOWED_MUTATION_KEYWORDS``);
  anything else is recorded with ``applied=0`` and never executed.
- arguments may contain only plain values and simple scalar variables
  (``${name}``): inline Python evaluation ``${{...}}``, extended
  variable syntax, and environment/list/dict variables are rejected,
  because the keyword allow-list alone would not stop code execution
  smuggled through an argument.
- mutation prompts are externalized to
  ``src/rfc/resources/generative_mutate_prompts.resource`` so reviewers
  can read and edit them (built-in fallback if unreadable).
- a parallel grader (the ``Grade Answer`` core, same prompting model)
  scores each applied mutation's quality and writes it to
  ``agentic_metrics`` as ``metric_key='mutation_quality'`` with the
  metric id equal to the decision id (the join key). Grading is
  advisory: a grader failure never blocks the recorded mutation.
  Caveat: the mutation model grades its own output — treat the score
  as a noise filter (e.g. Superset alert on ``mutation_quality < 0.5``),
  never as a pass/fail verdict.

**Heal mode (#361, suggestion-only, explicit opt-in).** When a suite is
tagged ``heal:suggest``, the listener prompts the LLM after each
opted-in test FAILS with the numbered test body and the failure
message, and asks for a proposed fix: the 1-based body line to replace
plus ONE replacement assertion (same allow-list and argument safety
rails as mutate). The fix runs as a *side experiment* — a sibling copy
named ``<original>::healed::<short_hash>`` tagged ``healed:true`` with
exactly that line replaced — and:

- **the original failure remains the official test outcome**; the
  decision row (``proposed_action='heal'``) is recorded with
  ``applied=0`` ALWAYS — CI never silently passes due to LLM
  intervention, and automatic write-back of healed values to
  ``.robot`` files is explicitly out of scope (#361).
- the experiment's outcome is written to ``agentic_metrics`` as
  ``metric_key='heal_passed'`` (1.0/0.0) with metric id
  ``<decision_id>-heal``.
- a parallel grader scores the proposed fix as ``mutation_quality``
  with metric id equal to the decision id (same join key as mutate),
  so the Superset "Healing Candidates This Week" chart can surface
  passing experiments with quality >= 0.7 for human triage.

This is distinct from :mod:`rfc.self_healing_listener`, which passively
records RFC_DATA emitted by the :func:`rfc.self_healing.self_healing`
keyword-retry decorator; heal mode generates *new* fix candidates via
LLM and records them in ``agentic_decisions``.

Every applied action persists a decision row with ``applied=1``;
suggestions that cannot be applied (no next test to skip, no fork
models configured, unparseable LLM output, disallowed mutation
keyword) persist with ``applied=0``. ``generative:observe`` semantics
are unchanged — observe-tagged suites never have their execution
modified, whatever the LLM says. One mode per suite; when a suite
carries several tags the precedence is flow > mutate > heal > observe.
Execution of ``generative:flow``, ``generative:mutate``, and
``heal:suggest`` suites diverges from the static ``.robot`` file; CI
consumers should treat them as exploratory, not gating (for heal the
*official* outcomes are unchanged — the experiment merely appears as an
extra sibling test).

A hard per-suite token budget prevents recursion / runaway cost: once
``RFC_GENERATIVE_BUDGET_TOKENS`` (default 10_000) is consumed, the
listener writes ONE ``budget_exhausted`` decision and goes silent for
the rest of the suite (in flow mode this also stops all flow actions).

All failures are skip-and-log per CLAUDE.md — the test outcome is
never affected by listener errors.

Usage::

    robot --listener rfc.generative_listener.GenerativeListener tests/

Environment:
    RFC_GENERATIVE_MODEL          Prompting model (default: a fast cheap
                                  local model, ``llama3.2:1b``).
    RFC_GENERATIVE_BUDGET_TOKENS  Per-suite token budget (default 10_000).
    RFC_GENERATIVE_FORK_MODELS    Comma-separated model pool for ``fork``
                                  (flow mode; unset = fork never applied).
    RFC_GENERATIVE_MUTATE_PROMPTS Path override for the mutate prompts
                                  resource file.
    GENERATIVE_DATABASE_URL       Preferred DB for decision rows.
    HARNESS_DATABASE_URL          Fallback (shared with the harness tables).
    DATABASE_URL                  Final fallback.
    SESSION_ID                    Session fallback when no sidecar is present.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from .base_listener import BaseListener
from .grader import Grader
from .harness_cli import active_session_id
from .harness_db import HarnessDatabase
from .harness_models import AgenticDecision, AgenticMetric
from .llm_client import LLMProvider, create_provider

logger = logging.getLogger(__name__)

GENERATIVE_OBSERVE_TAG = "generative:observe"
GENERATIVE_FLOW_TAG = "generative:flow"
GENERATIVE_MUTATE_TAG = "generative:mutate"
HEAL_SUGGEST_TAG = "heal:suggest"
RETRY_MARKER_TAG = "generative:retried"
FORK_MARKER_TAG = "generative_fork:true"
FORK_MODEL_TAG_PREFIX = "generative_fork:model:"
MUTATED_MARKER_TAG = "mutated:true"
HEALED_MARKER_TAG = "healed:true"
MUTATION_QUALITY_METRIC = "mutation_quality"
HEAL_PASSED_METRIC = "heal_passed"
# agentic_metrics.id is a PRIMARY KEY and mutation_quality already uses the
# bare decision id, so the heal-outcome metric derives its id from the
# decision id with this suffix (chart join: hp.id = d.id || '-heal').
# Hyphen, not colon: SQLAlchemy ``text()`` would read ``:heal`` inside the
# dataset SQL as a bind parameter.
HEAL_METRIC_ID_SUFFIX = "-heal"
DEFAULT_GENERATIVE_MODEL = "llama3.2:1b"
DEFAULT_BUDGET_TOKENS = 10_000

# Deterministic BuiltIn assertions a mutation may use — anything else is
# recorded (applied=0) but never executed. Deliberately excludes anything
# that runs code, touches the OS, or sets state — and `Should Match Regexp`,
# whose model-controlled pattern is a ReDoS vector (#516).
ALLOWED_MUTATION_KEYWORDS = (
    "Length Should Be",
    "Should Be Equal",
    "Should Be Equal As Numbers",
    "Should Be Equal As Strings",
    "Should Contain",
    "Should Not Be Empty",
    "Should Not Contain",
)
_ALLOWED_MUTATION_LOOKUP = {k.lower(): k for k in ALLOWED_MUTATION_KEYWORDS}

# Ships as package data so installed (wheel) deployments resolve it too,
# not just repo checkouts (#516).
MUTATE_PROMPTS_RESOURCE = (
    Path(__file__).resolve().parent / "resources" / "generative_mutate_prompts.resource"
)

_FLOW_ACTIONS = ("skip", "retry", "fork", "none")
_ACTION_RE = re.compile(r"\b(skip|retry|fork|none)\b", re.IGNORECASE)

_SUITE_PROMPT_TEMPLATE = (
    "You are observing a Robot Framework test run (read-only; your "
    "suggestions are recorded but never applied).\n"
    "Suite '{suite}' is starting with {test_count} test(s).\n"
    "Briefly note anything worth watching for in this suite."
)

_FAILURE_PROMPT_TEMPLATE = (
    "You are observing a Robot Framework test run (read-only; your "
    "suggestions are recorded but never applied).\n"
    "Test '{test}' in suite '{suite}' FAILED with message:\n{message}\n"
    "Captured run data: {rfc_data}\n"
    "Briefly suggest a likely cause and what a follow-up action could be."
)

_FLOW_PROMPT_TEMPLATE = (
    "You control the flow of a Robot Framework test run (suite opted in "
    "via the generative:flow tag).\n"
    "Test '{test}' in suite '{suite}' FAILED with message:\n{message}\n"
    "Captured run data: {rfc_data}\n"
    "Reply with exactly one word on the first line — your chosen action:\n"
    "  skip  — mark the NEXT test in the suite as SKIPPED\n"
    "  retry — re-run this failed test once\n"
    "  fork  — re-run this failed test against alternate models\n"
    "  none  — take no action\n"
    "You may add a one-sentence rationale after the first line."
)


# Built-in fallbacks, kept in sync with
# src/rfc/resources/generative_mutate_prompts.resource (the reviewable copy).
_DEFAULT_MUTATE_PROMPTS = {
    "MUTATION_PROMPT_TEMPLATE": (
        "You are mutating a Robot Framework test (suite opted in via the "
        "generative:mutate tag).\n"
        "Test '{test}' in suite '{suite}' just finished with status {status}.\n"
        "Failure message (if any): {message}\n"
        "Captured run data: {rfc_data}\n"
        "The test body (keywords and arguments, four-space separated) is:\n"
        "{body}\n"
        "Propose ONE new assertion that would make this test stricter or "
        "probe a nearby behavior. It will be appended to a copy of the test "
        "and executed.\n"
        "Reply with EXACTLY one line and nothing else, in Robot Framework "
        "syntax: the keyword, then each argument, separated by four spaces.\n"
        "You may only use one of these keywords: {allowed_keywords}.\n"
        "Arguments may contain only plain values and simple scalar "
        "variables created by the test body, referenced exactly as they "
        "appear there; inline expressions, environment variables, and "
        "list/dict variables are rejected."
    ),
    "MUTATION_GRADER_QUESTION": (
        "A test-mutation agent was asked to strengthen the Robot Framework "
        "test '{test}' (suite '{suite}', finished with status {status}) by "
        "proposing one new assertion. Judge the quality of the proposed "
        "assertion below: is it strict, meaningful, and likely to catch a "
        "real regression — or is it trivial, tautological, or too lenient?\n"
        "Proposed assertion: {assertion}"
    ),
    "MUTATION_GRADER_EXPECTED": (
        "A strict, meaningful assertion that checks real test output and "
        "would fail on a genuine regression; not a tautology, not vacuously "
        "true, not so loose that any output passes."
    ),
    "HEAL_PROMPT_TEMPLATE": (
        "You are proposing a fix for a failed Robot Framework test (suite "
        "opted in via the heal:suggest tag). Your fix runs as a SIDE "
        "EXPERIMENT only; the original failure remains the official "
        "outcome.\n"
        "Test '{test}' in suite '{suite}' FAILED with message:\n{message}\n"
        "Captured run data: {rfc_data}\n"
        "The test body, one numbered line per keyword (number, then the "
        "keyword and its arguments, four-space separated):\n"
        "{body}\n"
        "Propose a fix by replacing ONE body line with ONE corrected "
        "assertion (e.g. an updated expected value).\n"
        "You may only target a line that is itself an assertion (its "
        "keyword name contains 'Should'); never replace the action that "
        "produced the output.\n"
        "Reply with EXACTLY two lines and nothing else:\n"
        "line 1: the number of the body line to replace\n"
        "line 2: the replacement in Robot Framework syntax — the keyword, "
        "then each argument, separated by four spaces.\n"
        "You may only use one of these keywords: {allowed_keywords}.\n"
        "Arguments may contain only plain values and simple scalar "
        "variables created by the test body, referenced exactly as they "
        "appear there; inline expressions, environment variables, and "
        "list/dict variables are rejected."
    ),
    "HEAL_GRADER_QUESTION": (
        "A self-healing agent was asked to fix the failed Robot Framework "
        "test '{test}' (suite '{suite}', failure message: {message}) by "
        "replacing one body line with a corrected assertion. Judge the "
        "quality of the proposed fix below: does it plausibly address the "
        "failure while still checking real behavior — or does it merely "
        "weaken the test until anything passes?\n"
        "Proposed fix: {assertion}"
    ),
    "HEAL_GRADER_EXPECTED": (
        "A plausible, targeted fix that addresses the observed failure and "
        "still asserts something meaningful about real test output; not a "
        "tautology, not an assertion loosened until any output passes."
    ),
}

_mutate_prompts_cache: dict[str, dict[str, str]] = {}  # keyed by resource path


def _load_mutate_prompts() -> dict[str, str]:
    """Parse the externalized prompts resource; fall back to built-ins.

    Reads the ``*** Variables ***`` section of the resource file via the
    Robot parsing API (the file is never *executed*). Multi-line scalars
    honour a leading ``SEPARATOR=`` value; ``\\${`` unescapes to ``${``.
    """
    path = os.getenv("RFC_GENERATIVE_MUTATE_PROMPTS", "") or str(
        MUTATE_PROMPTS_RESOURCE
    )
    cached = _mutate_prompts_cache.get(path)
    if cached is not None:
        return cached
    prompts = dict(_DEFAULT_MUTATE_PROMPTS)
    try:
        from robot.api import get_resource_model

        model = get_resource_model(path)
        for section in model.sections:
            for stmt in getattr(section, "body", None) or []:
                name = (getattr(stmt, "name", "") or "").strip("${}")
                if name not in prompts:
                    continue
                values = list(getattr(stmt, "value", None) or [])
                separator = " "
                if values and values[0].startswith("SEPARATOR="):
                    separator = values[0][len("SEPARATOR=") :].replace("\\n", "\n")
                    values = values[1:]
                if values:
                    prompts[name] = separator.join(values).replace("\\${", "${")
    except Exception as exc:  # skip-and-log: built-in fallbacks remain
        logger.warning(
            "GenerativeListener: could not load mutate prompts from %s "
            "(using built-in defaults): %s",
            path,
            exc,
        )
    _mutate_prompts_cache[path] = prompts
    return prompts


def _utc_now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"


def _suite_has_tag(node: Any, tag: str) -> bool:
    """Recursively check a running suite tree for a test carrying ``tag``."""
    for test in getattr(node, "tests", None) or []:
        if any(str(t).lower() == tag for t in (getattr(test, "tags", None) or [])):
            return True
    return any(
        _suite_has_tag(child, tag) for child in (getattr(node, "suites", None) or [])
    )


def _test_has_tag(test: Any, tag: str) -> bool:
    return any(str(t).lower() == tag for t in (getattr(test, "tags", None) or []))


def _parse_action(response: str) -> str:
    """Parse the declared action from the FIRST non-empty response line.

    The prompt demands exactly one action word on the first line; only
    that line is honoured so rationale text ('Do not retry; choose
    none') can never steer the run. The word may carry markdown/
    punctuation decoration. Anything else maps to ``none`` (recorded,
    never applied).
    """
    for line in response.splitlines():
        word = line.strip().strip("*_`'\".,!?:;()[]{}").strip()
        if not word:
            continue
        return word.lower() if word.lower() in _FLOW_ACTIONS else "none"
    return "none"


# A "simple" scalar variable: ${plain name} — identifier-ish, no nesting,
# no item access, no attribute access, no inline expressions.
_SIMPLE_VARIABLE_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_ ]*\}")


def _safe_mutation_arg(arg: str) -> bool:
    """True when ``arg`` is plain text plus simple scalar variables only.

    Robot evaluates ``${{...}}`` as inline Python (full builtins access),
    extended syntax (``${obj.attr}``, ``${list[0]}``) calls into objects,
    and ``%{ENV}`` / ``@{list}`` / ``&{dict}`` reach beyond plain values —
    so an allow-listed keyword with a hostile argument could still execute
    arbitrary code (Codex P1, PR #501). After removing simple scalar
    variables, any surviving variable opener rejects the argument.
    Literal braces that are not Robot variable syntax (e.g. the regex
    ``\\d{3}``) stay legal.
    """
    stripped = _SIMPLE_VARIABLE_RE.sub("", arg)
    return not any(tok in stripped for tok in ("${", "%{", "@{", "&{"))


def _parse_mutation(response: str) -> Optional[tuple[str, list[str]]]:
    """Parse ``(keyword, args)`` from the FIRST non-empty response line.

    The prompt demands exactly one assertion line; only that line is
    honoured (same rationale as :func:`_parse_action`). The keyword must
    match ``ALLOWED_MUTATION_KEYWORDS`` case-insensitively and carry at
    least one argument, and every argument must pass
    :func:`_safe_mutation_arg`; cells are separated by two-plus spaces or
    tabs, Robot style. Anything else returns ``None`` (recorded, never
    run).
    """
    for line in response.splitlines():
        line = line.strip().strip("`").strip()
        if not line:
            continue
        return _parse_assertion_line(line)
    return None


def _parse_assertion_line(line: str) -> Optional[tuple[str, list[str]]]:
    """Parse one ``keyword    arg    arg`` cell line; None when unsafe."""
    cells = [c.strip() for c in re.split(r"\t+| {2,}", line) if c.strip()]
    if len(cells) < 2:
        return None
    keyword = _ALLOWED_MUTATION_LOOKUP.get(cells[0].lower())
    if keyword is None:
        return None
    args = cells[1:]
    if not all(_safe_mutation_arg(a) for a in args):
        return None
    return keyword, args


def _parse_heal(response: str) -> Optional[tuple[int, str, list[str]]]:
    """Parse ``(line_number, keyword, args)`` from a heal response.

    The prompt demands exactly two lines: a 1-based body line number,
    then one replacement assertion. Only the first two non-empty lines
    are honoured (same trailing-prose defence as :func:`_parse_action`
    / :func:`_parse_mutation`); the assertion obeys the mutate safety
    rails (allow-listed keyword, safe arguments). Anything else returns
    ``None`` (recorded, never run). Range-checking the line number
    against the actual body happens at build time.
    """
    lines = [ln for ln in (raw.strip() for raw in response.splitlines()) if ln]
    if len(lines) < 2:
        return None
    number_word = lines[0].strip("*_`'\".,!?:;()[]{}").strip()
    try:
        line_number = int(number_word)
    except ValueError:
        return None
    if line_number < 1:
        return None
    assertion = _parse_assertion_line(lines[1].strip("`").strip())
    if assertion is None:
        return None
    keyword, args = assertion
    return line_number, keyword, args


def _fill_template(template: str, **values: Any) -> str:
    """Substitute ``{placeholder}`` tokens without ``str.format``.

    Prompt templates are reviewer-editable and may legitimately contain
    literal Robot variables like ``${answer}``; ``str.format`` would read
    that as a ``{answer}`` placeholder and raise ``KeyError`` (Codex P2,
    PR #501). Plain replacement only touches the known placeholders.
    """
    for key, value in values.items():
        template = template.replace("{" + key + "}", str(value))
    return template


def _assertion_like(item: Any) -> bool:
    """True when a body item looks like an assertion (its keyword name
    contains 'should', covering the BuiltIn assertion family and most
    custom verification keywords). Heal experiments may only replace
    assertion lines: swapping out the *action* that caused the failure
    (``Ask LLM``, ``Fail``, a setup step) for an assertion would make the
    experiment trivially green and surface a false healing candidate
    (Codex P2, PR #518)."""
    return "should" in (getattr(item, "name", "") or "").lower()


def _render_body(test: Any, numbered: bool = False) -> str:
    """Render a test body as Robot-style lines for the mutation/heal
    prompts, so the LLM can see the keywords, arguments, and assigned
    variables. ``numbered`` prefixes each line with its 1-based number
    (heal mode asks the LLM to name the line it wants to replace)."""
    lines = []
    for index, kw in enumerate(getattr(test, "body", None) or [], start=1):
        assign = [str(a) for a in (getattr(kw, "assign", None) or [])]
        name = getattr(kw, "name", "") or ""
        args = [str(a) for a in (getattr(kw, "args", None) or [])]
        cells = (["    ".join(assign) + " ="] if assign else []) + [name] + args
        if numbered:
            cells.insert(0, str(index))
        lines.append("    ".join(c for c in cells if c))
    return "\n".join(lines) or "(empty)"


def _add_tag(test: Any, tag: str) -> None:
    """Add a tag on either a robot.running ``Tags`` or a plain list."""
    tags = getattr(test, "tags", None)
    if tags is None:
        return
    if hasattr(tags, "add"):
        tags.add(tag)
    else:
        tags.append(tag)


def _copy_test(test: Any) -> Any:
    """Deep-copy a running-model test (robot objects expose ``deepcopy``)."""
    if hasattr(test, "deepcopy"):
        return test.deepcopy()
    import copy as _copy

    return _copy.deepcopy(test)


def _test_failed(result: Any) -> bool:
    """True only for a genuine FAIL — SKIP must not look like a failure."""
    status = getattr(result, "status", None)
    if status is not None:
        return str(status).upper() == "FAIL"
    return not getattr(result, "passed", True)


class GenerativeListener(BaseListener):
    """Record LLM observations into ``agentic_decisions``; in flow mode
    (``generative:flow``) additionally apply skip / retry / fork; in
    mutate mode (``generative:mutate``) generate, run, and grade
    LLM-suggested test mutations."""

    def __init__(
        self,
        database_url: Optional[str] = None,
        provider: Optional[LLMProvider] = None,
    ) -> None:
        super().__init__()
        self._database_url = (
            database_url
            or os.getenv("GENERATIVE_DATABASE_URL")
            or os.getenv("HARNESS_DATABASE_URL")
            or os.getenv("DATABASE_URL")
        )
        self._provider = provider  # injectable for tests; lazy otherwise
        self._db: Optional[HarnessDatabase] = None
        self._session_id = ""
        self._suite_name = ""
        self._mode = ""  # "" | "observe" | "flow" | "mutate"
        self._budget_tokens = DEFAULT_BUDGET_TOKENS
        self._tokens_used = 0
        self._budget_exhausted = False
        self._persisted_count = 0
        self._pending_skip_id = ""  # decision id to stamp on the next test
        self._retried_test_ids: set[int] = set()  # id(data): names may repeat
        self._suppressed_test_ids: set[int] = set()  # id(data) of skip targets
        self._heal_experiment_ids: dict[int, str] = {}  # id(copy) -> decision id

    @property
    def persisted_count(self) -> int:
        return self._persisted_count

    @property
    def budget_tokens(self) -> int:
        return self._budget_tokens

    @property
    def _observing(self) -> bool:
        return self._mode != ""

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    def on_suite_start(self, data: Any, result: Any) -> None:
        self._suite_name = getattr(data, "name", "") or ""
        self._tokens_used = 0
        self._budget_exhausted = False
        self._budget_tokens = self._read_budget()
        self._pending_skip_id = ""
        self._retried_test_ids = set()
        self._suppressed_test_ids = set()
        self._heal_experiment_ids = {}
        if _suite_has_tag(data, GENERATIVE_FLOW_TAG):
            self._mode = "flow"  # one mode per suite: flow > mutate > heal > observe
        elif _suite_has_tag(data, GENERATIVE_MUTATE_TAG):
            self._mode = "mutate"
        elif _suite_has_tag(data, HEAL_SUGGEST_TAG):
            self._mode = "heal"
        elif _suite_has_tag(data, GENERATIVE_OBSERVE_TAG):
            self._mode = "observe"
        else:
            self._mode = ""
            return
        mode_tag = {
            "flow": GENERATIVE_FLOW_TAG,
            "mutate": GENERATIVE_MUTATE_TAG,
            "heal": HEAL_SUGGEST_TAG,
            "observe": GENERATIVE_OBSERVE_TAG,
        }[self._mode]
        self._session_id = active_session_id() or os.getenv("SESSION_ID", "")
        if not self._session_id:
            logger.warning(
                "GenerativeListener: suite %r is tagged %s but no harness "
                "session is active (sidecar or SESSION_ID); observations "
                "will not be captured.",
                self._suite_name,
                mode_tag,
            )
            self._mode = ""
            return
        if not self._session_has_harness_row():
            self._mode = ""
            return
        if self._mode != "observe":
            return
        prompt = _SUITE_PROMPT_TEMPLATE.format(
            suite=self._suite_name,
            test_count=len(getattr(data, "tests", None) or []),
        )
        self._observe("start_suite", "", prompt)

    def on_test_start(self, data: Any, result: Any) -> None:
        if self._mode != "flow" or not self._pending_skip_id:
            return
        decision_id, self._pending_skip_id = self._pending_skip_id, ""
        self._suppressed_test_ids.add(id(data))
        message = f"Skipped by generative listener (decision {decision_id})"
        try:
            body = data.body
            body.clear()
            body.create_keyword(name="Skip", args=[message])
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning(
                "GenerativeListener: could not apply skip to test %r: %s",
                getattr(data, "name", ""),
                exc,
            )

    def on_test_end(self, data: Any, result: Any) -> None:
        if self._mode == "observe":
            if getattr(result, "passed", True):
                return
            test_name = getattr(data, "name", "") or ""
            prompt = _FAILURE_PROMPT_TEMPLATE.format(
                test=test_name,
                suite=self._suite_name,
                message=getattr(result, "message", "") or "",
                rfc_data=dict(self._current_test_data) or "none",
            )
            self._observe("end_test", test_name, prompt)
            return
        if self._mode == "mutate":
            self._handle_mutation(data, result)
            return
        if self._mode == "heal":
            self._handle_heal(data, result)
            return
        if self._mode != "flow":
            return
        if not _test_failed(result):
            return
        if id(data) in self._suppressed_test_ids:
            return  # a test we ourselves marked skipped
        if _test_has_tag(data, RETRY_MARKER_TAG) or _test_has_tag(
            data, FORK_MARKER_TAG
        ):
            return  # copies we inserted never trigger further actions
        if not _test_has_tag(data, GENERATIVE_FLOW_TAG):
            return  # flow is per-test opt-in: untagged siblings stay static
        self._handle_flow_failure(data, result)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _read_budget(self) -> int:
        raw = os.getenv("RFC_GENERATIVE_BUDGET_TOKENS", "")
        if not raw:
            return DEFAULT_BUDGET_TOKENS
        try:
            return int(raw)
        except ValueError:
            logger.warning(
                "GenerativeListener: invalid RFC_GENERATIVE_BUDGET_TOKENS=%r; "
                "using default %d.",
                raw,
                DEFAULT_BUDGET_TOKENS,
            )
            return DEFAULT_BUDGET_TOKENS

    def _get_db(self) -> Optional[HarnessDatabase]:
        if self._db is not None:
            return self._db
        if not self._database_url:
            logger.warning(
                "GenerativeListener: no GENERATIVE_DATABASE_URL/"
                "HARNESS_DATABASE_URL/DATABASE_URL configured; observations "
                "will not be captured."
            )
            return None
        try:
            self._db = HarnessDatabase(database_url=self._database_url)
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning("GenerativeListener: HarnessDatabase init failed: %s", exc)
            return None
        return self._db

    def _session_has_harness_row(self) -> bool:
        """The FK requires an ``agentic_harnesses`` row; warn and disable
        when the session was never started with ``rfc harness start`` (#419)."""
        db = self._get_db()
        if db is None:
            return False
        try:
            if db.get_harness(self._session_id) is not None:
                return True
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning("GenerativeListener: harness lookup failed: %s", exc)
            return False
        logger.warning(
            "GenerativeListener: session %s has no agentic_harnesses row "
            "(run started without `rfc harness start`?); observations "
            "will not be captured.",
            self._session_id,
        )
        return False

    def _get_provider(self) -> Optional[LLMProvider]:
        if self._provider is not None:
            return self._provider
        model = os.getenv("RFC_GENERATIVE_MODEL", DEFAULT_GENERATIVE_MODEL)
        try:
            self._provider = create_provider(model=model)
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning("GenerativeListener: provider init failed: %s", exc)
            return None
        return self._provider

    def _prompt_llm(self, hook_event: str, test_name: str, prompt: str) -> str:
        """Prompt the LLM honouring the budget; '' means no response
        (budget exhausted, provider missing, or call failed)."""
        if self._budget_exhausted:
            return ""
        if self._tokens_used >= self._budget_tokens:
            self._write_budget_exhausted(hook_event, test_name)
            return ""
        provider = self._get_provider()
        if provider is None:
            return ""
        try:
            response = provider.generate(prompt)
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning("GenerativeListener: LLM call failed: %s", exc)
            return ""
        self._tokens_used += self._tokens_consumed(provider, prompt, response)
        return response

    def _observe(self, hook_event: str, test_name: str, prompt: str) -> None:
        """Prompt the LLM and persist a read-only observation row."""
        response = self._prompt_llm(hook_event, test_name, prompt)
        if not response:
            return
        self._persist(
            AgenticDecision(
                session_id=self._session_id,
                hook_event=hook_event,
                prompt_model=getattr(self._provider, "model", "") or "",
                prompt_text=prompt,
                recorded_at=_utc_now(),
                test_name=test_name,
                response_text=response,
                proposed_action="observe",
                applied=0,
                tokens_used=self._tokens_used,
            )
        )

    # ------------------------------------------------------------------
    # Flow mode (#359)
    # ------------------------------------------------------------------

    def _handle_flow_failure(self, data: Any, result: Any) -> None:
        """Ask the LLM for a flow action on a failed test and apply it."""
        test_name = getattr(data, "name", "") or ""
        prompt = _FLOW_PROMPT_TEMPLATE.format(
            test=test_name,
            suite=self._suite_name,
            message=getattr(result, "message", "") or "",
            rfc_data=dict(self._current_test_data) or "none",
        )
        response = self._prompt_llm("end_test", test_name, prompt)
        if not response:
            return
        action = _parse_action(response)
        decision_id = uuid4().hex  # pre-generated so skip can stamp it
        # Audit guarantee: the decision row is persisted BEFORE the run is
        # mutated. Applicability is pre-checked so `applied` is recorded
        # truthfully; if persistence fails the mutation is withheld —
        # active flow control must never be unauditable.
        applied = 1 if self._action_applicable(action, data) else 0
        persisted = self._persist(
            AgenticDecision(
                session_id=self._session_id,
                hook_event="end_test",
                prompt_model=getattr(self._provider, "model", "") or "",
                prompt_text=prompt,
                recorded_at=_utc_now(),
                test_name=test_name,
                response_text=response,
                proposed_action=action,
                applied=applied,
                tokens_used=self._tokens_used,
                id=decision_id,
            )
        )
        if not persisted:
            if applied:
                logger.warning(
                    "GenerativeListener: NOT applying %r for test %r — the "
                    "decision row could not be persisted and active flow "
                    "control must stay auditable.",
                    action,
                    test_name,
                )
            return
        if not applied:
            return
        if action == "skip":
            result_applied = self._apply_skip(data, decision_id)
        elif action == "retry":
            result_applied = self._apply_retry(data, test_name)
        else:
            result_applied = self._apply_fork(data, test_name)
        if not result_applied:
            logger.warning(
                "GenerativeListener: decision %s recorded applied=1 but "
                "applying %r to test %r failed after persistence.",
                decision_id,
                action,
                test_name,
            )

    def _action_applicable(self, action: str, data: Any) -> bool:
        """Pre-check whether *action* can be applied, without mutating."""
        if action == "skip":
            tests, index = self._suite_position(data)
            if tests is None or index + 1 >= len(tests):
                return False
            # Flow is per-test opt-in: never rewrite a next test that does
            # not itself carry the flow tag (tags are per test in RF).
            if not _test_has_tag(tests[index + 1], GENERATIVE_FLOW_TAG):
                logger.warning(
                    "GenerativeListener: skip proposed after test %r but the "
                    "next test did not opt in to %s; not applied.",
                    getattr(data, "name", ""),
                    GENERATIVE_FLOW_TAG,
                )
                return False
            return True
        if action == "retry":
            if id(data) in self._retried_test_ids:
                return False
            tests, _ = self._suite_position(data)
            return tests is not None
        if action == "fork":
            if not self._fork_models():
                logger.warning(
                    "GenerativeListener: fork proposed for %r but "
                    "RFC_GENERATIVE_FORK_MODELS is not configured; not applied.",
                    getattr(data, "name", ""),
                )
                return False
            tests, _ = self._suite_position(data)
            return tests is not None
        return False

    @staticmethod
    def _fork_models() -> list[str]:
        return [
            m.strip()
            for m in os.getenv("RFC_GENERATIVE_FORK_MODELS", "").split(",")
            if m.strip()
        ]

    def _suite_position(self, data: Any) -> tuple[Any, int]:
        """Return ``(tests, index)`` for a running test, or ``(None, -1)``."""
        tests = getattr(getattr(data, "parent", None), "tests", None)
        if tests is None:
            return None, -1
        try:
            return tests, tests.index(data)
        except ValueError:
            return None, -1

    def _apply_skip(self, data: Any, decision_id: str) -> int:
        """Arm a skip for the next test; 1 if there is an opted-in next test."""
        tests, index = self._suite_position(data)
        if tests is None or index + 1 >= len(tests):
            logger.warning(
                "GenerativeListener: skip proposed after test %r but there "
                "is no next test in suite %r; not applied.",
                getattr(data, "name", ""),
                self._suite_name,
            )
            return 0
        if not _test_has_tag(tests[index + 1], GENERATIVE_FLOW_TAG):
            return 0  # per-test opt-in; pre-checked in _action_applicable
        self._pending_skip_id = decision_id
        return 1

    def _apply_retry(self, data: Any, test_name: str) -> int:
        """Insert one tagged copy of the failed test right after it."""
        if id(data) in self._retried_test_ids:
            return 0  # at most one retry per original test (by identity)
        tests, index = self._suite_position(data)
        if tests is None:
            return 0
        try:
            copy = _copy_test(data)
            copy.name = f"{test_name} (generative retry)"
            _add_tag(copy, RETRY_MARKER_TAG)
            tests.insert(index + 1, copy)
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning(
                "GenerativeListener: could not apply retry for %r: %s",
                test_name,
                exc,
            )
            return 0
        self._retried_test_ids.add(id(data))
        return 1

    def _apply_fork(self, data: Any, test_name: str) -> int:
        """Insert one tagged copy per configured fork model, bracketed by
        ``Save LLM Model`` / ``Restore LLM Model`` so later original tests
        keep running against the suite's pre-fork model."""
        models = self._fork_models()
        if not models:
            logger.warning(
                "GenerativeListener: fork proposed for %r but "
                "RFC_GENERATIVE_FORK_MODELS is not configured; not applied.",
                test_name,
            )
            return 0
        tests, index = self._suite_position(data)
        if tests is None:
            return 0
        inserted = 0
        for offset, model in enumerate(models, start=1):
            try:
                copy = _copy_test(data)
                copy.name = f"{test_name} (generative fork: {model})"
                _add_tag(copy, FORK_MARKER_TAG)
                _add_tag(copy, f"{FORK_MODEL_TAG_PREFIX}{model}")
                # Point the copy at the alternate model before anything else.
                copy.body.create_keyword(name="Set LLM Model", args=[model])
                copy.body.insert(0, copy.body.pop())
                if inserted == 0:
                    # Capture the pre-fork model before the first switch.
                    copy.body.create_keyword(name="Save LLM Model", args=[])
                    copy.body.insert(0, copy.body.pop())
                tests.insert(index + offset, copy)
                inserted += 1
            except Exception as exc:  # skip-and-log: never fail the run
                logger.warning(
                    "GenerativeListener: could not fork %r onto model %r: %s",
                    test_name,
                    model,
                    exc,
                )
        if inserted:
            try:
                restore = _copy_test(data)
                restore.name = f"{test_name} (generative fork: model restore)"
                _add_tag(restore, FORK_MARKER_TAG)
                restore.body.clear()
                restore.body.create_keyword(name="Restore LLM Model", args=[])
                # The restore must be unconditional: a copied setup that
                # fails would prevent Restore LLM Model from running (model
                # leak into later tests) and a copied teardown would run an
                # extra time with an empty body.
                restore.setup = None
                restore.teardown = None
                tests.insert(index + inserted + 1, restore)
            except Exception as exc:  # skip-and-log: never fail the run
                logger.warning(
                    "GenerativeListener: could not insert model-restore test "
                    "after forking %r: %s",
                    test_name,
                    exc,
                )
        return 1 if inserted else 0

    # ------------------------------------------------------------------
    # Mutate mode (#360)
    # ------------------------------------------------------------------

    def _handle_mutation(self, data: Any, result: Any) -> None:
        """Ask the LLM for one new assertion, run it as a sibling test,
        and grade the mutation's quality in parallel."""
        status = str(getattr(result, "status", "") or "").upper()
        if status != "PASS":
            # Failed tests are not mutated: Robot stops at the first failing
            # keyword, so an assertion appended after the failing body would
            # never execute — recording it as applied would be untrue.
            # Skipped / not-run tests have no output to mutate against.
            return
        if (
            _test_has_tag(data, MUTATED_MARKER_TAG)
            or _test_has_tag(data, RETRY_MARKER_TAG)
            or _test_has_tag(data, FORK_MARKER_TAG)
        ):
            return  # copies we inserted never trigger further mutations
        if not _test_has_tag(data, GENERATIVE_MUTATE_TAG):
            return  # mutate is per-test opt-in: untagged siblings stay static
        test_name = getattr(data, "name", "") or ""
        prompts = _load_mutate_prompts()
        prompt = _fill_template(
            prompts["MUTATION_PROMPT_TEMPLATE"],
            test=test_name,
            suite=self._suite_name,
            status=status,
            message=getattr(result, "message", "") or "none",
            rfc_data=dict(self._current_test_data) or "none",
            body=_render_body(data),
            allowed_keywords=", ".join(ALLOWED_MUTATION_KEYWORDS),
        )
        response = self._prompt_llm("end_test", test_name, prompt)
        if not response:
            return
        mutation = _parse_mutation(response)
        decision_id = uuid4().hex
        # Audit guarantee (same as flow mode): the decision row is
        # persisted BEFORE the run is mutated; if persistence fails the
        # mutation is withheld — generated tests must never be unauditable.
        # The failable construction (deepcopy/create_keyword) happens here,
        # pre-persist, so `applied` is truthful (#501): only the plain
        # list insert remains after the row is written.
        staged = None
        if mutation is not None and self._suite_position(data)[0] is not None:
            keyword, args = mutation
            staged = self._build_mutation_copy(data, test_name, keyword, args)
        applied = 1 if staged is not None else 0
        persisted = self._persist(
            AgenticDecision(
                session_id=self._session_id,
                hook_event="end_test",
                prompt_model=getattr(self._provider, "model", "") or "",
                prompt_text=prompt,
                recorded_at=_utc_now(),
                test_name=test_name,
                response_text=response,
                proposed_action="mutate",
                applied=applied,
                tokens_used=self._tokens_used,
                id=decision_id,
            )
        )
        if not persisted:
            if applied:
                logger.warning(
                    "GenerativeListener: NOT applying mutation for test %r — "
                    "the decision row could not be persisted and generated "
                    "tests must stay auditable.",
                    test_name,
                )
            return
        if not applied:
            if mutation is None:
                logger.warning(
                    "GenerativeListener: mutation response for %r was not a "
                    "single allow-listed assertion; recorded, not applied.",
                    test_name,
                )
            return
        keyword, args = mutation  # type: ignore[misc]
        if not self._insert_mutation_copy(data, staged):
            logger.warning(
                "GenerativeListener: decision %s recorded applied=1 but "
                "inserting the mutated copy of %r failed after persistence.",
                decision_id,
                test_name,
            )
            return
        self._grade_mutation(decision_id, test_name, status, keyword, args)

    def _build_mutation_copy(
        self, data: Any, test_name: str, keyword: str, args: list[str]
    ) -> Any | None:
        """Construct the ``<original>::mutated::<short_hash>`` sibling copy.

        All failable work (deepcopy, tagging, keyword creation) happens
        here so callers can persist a truthful ``applied`` before the
        trivial list insert (#501)."""
        assertion_line = "    ".join([keyword, *args])
        short_hash = hashlib.sha1(assertion_line.encode("utf-8")).hexdigest()[:8]
        try:
            copy = _copy_test(data)
            copy.name = f"{test_name}::mutated::{short_hash}"
            _add_tag(copy, MUTATED_MARKER_TAG)
            # Explicit BuiltIn. qualification: a user keyword named e.g.
            # "Should Be Equal" would shadow the BuiltIn at resolution
            # time, so the allow-listed name alone cannot guarantee which
            # code runs (#516).
            copy.body.create_keyword(name=f"BuiltIn.{keyword}", args=list(args))
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning(
                "GenerativeListener: could not build mutated copy of %r: %s",
                test_name,
                exc,
            )
            return None
        return copy

    def _insert_mutation_copy(self, data: Any, copy: Any) -> int:
        """Insert a pre-built mutated copy right after its original; it runs
        inline and gets its own ``test_runs`` row from the results listener."""
        tests, index = self._suite_position(data)
        if tests is None:
            return 0
        try:
            tests.insert(index + 1, copy)
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning(
                "GenerativeListener: could not insert mutated copy of %r: %s",
                getattr(data, "name", ""),
                exc,
            )
            return 0
        return 1

    def _grade_mutation(
        self,
        decision_id: str,
        test_name: str,
        status: str,
        keyword: str,
        args: list[str],
    ) -> None:
        """Score the mutation's quality with the ``Grade Answer`` core and
        write ``metric_key='mutation_quality'`` to ``agentic_metrics``,
        reusing the decision id as the metric id (the join key). Advisory
        only: failures are logged and never block the recorded mutation."""
        prompts = _load_mutate_prompts()
        assertion_line = "    ".join([keyword, *args])
        question = _fill_template(
            prompts["MUTATION_GRADER_QUESTION"],
            test=test_name,
            suite=self._suite_name,
            status=status,
            assertion=assertion_line,
        )
        self._grade_assertion(
            decision_id,
            test_name,
            question,
            prompts["MUTATION_GRADER_EXPECTED"],
            assertion_line,
        )

    def _grade_assertion(
        self,
        decision_id: str,
        test_name: str,
        question: str,
        expected: str,
        assertion_line: str,
    ) -> None:
        """Shared grading core for mutate and heal: score one proposed
        assertion and write ``mutation_quality`` keyed by the decision id."""
        if self._budget_exhausted:
            return
        if self._tokens_used >= self._budget_tokens:
            self._write_budget_exhausted("end_test", test_name)
            return
        provider = self._get_provider()
        if provider is None:
            return
        grade = None
        try:
            grade = Grader(provider).grade(question, expected, assertion_line)
        except Exception as exc:  # skip-and-log: grading is advisory
            logger.warning(
                "GenerativeListener: mutation_quality grading failed for "
                "decision %s: %s",
                decision_id,
                exc,
            )
        self._tokens_used += self._tokens_consumed(
            provider,
            question + expected + assertion_line,
            grade.reason if grade else "",
        )
        if grade is None:
            return
        db = self._get_db()
        if db is None:
            return
        try:
            db.save_metric(
                AgenticMetric(
                    session_id=self._session_id,
                    metric_key=MUTATION_QUALITY_METRIC,
                    metric_value=grade.score,
                    recorded_at=_utc_now(),
                    id=decision_id,
                )
            )
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning(
                "GenerativeListener: could not persist mutation_quality for "
                "decision %s: %s",
                decision_id,
                exc,
            )

    # ------------------------------------------------------------------
    # Heal mode (#361)
    # ------------------------------------------------------------------

    def _handle_heal(self, data: Any, result: Any) -> None:
        """On an opted-in failure, record an LLM-proposed fix (applied=0
        ALWAYS — the original failure stays the official outcome) and run
        it as a side-experiment sibling test."""
        experiment_decision_id = self._heal_experiment_ids.pop(id(data), "")
        if experiment_decision_id:
            self._record_heal_outcome(experiment_decision_id, data, result)
            return
        if not _test_failed(result):
            return
        if (
            _test_has_tag(data, HEALED_MARKER_TAG)
            or _test_has_tag(data, MUTATED_MARKER_TAG)
            or _test_has_tag(data, RETRY_MARKER_TAG)
            or _test_has_tag(data, FORK_MARKER_TAG)
        ):
            return  # copies we (or other modes) inserted never re-heal
        if not _test_has_tag(data, HEAL_SUGGEST_TAG):
            return  # heal is per-test opt-in: untagged siblings stay static
        test_name = getattr(data, "name", "") or ""
        prompts = _load_mutate_prompts()
        prompt = _fill_template(
            prompts["HEAL_PROMPT_TEMPLATE"],
            test=test_name,
            suite=self._suite_name,
            message=getattr(result, "message", "") or "none",
            rfc_data=dict(self._current_test_data) or "none",
            body=_render_body(data, numbered=True),
            allowed_keywords=", ".join(ALLOWED_MUTATION_KEYWORDS),
        )
        response = self._prompt_llm("end_test", test_name, prompt)
        if not response:
            return
        heal = _parse_heal(response)
        decision_id = uuid4().hex
        # Audit guarantee (same as flow/mutate): the decision row is
        # persisted BEFORE the experiment is inserted; if persistence
        # fails the experiment is withheld. The failable construction
        # happens pre-persist; only the plain list insert remains after
        # the row is written. `applied` stays 0 either way: a heal never
        # changes the official outcome — heal_passed (written when the
        # experiment finishes) is the signal that the experiment ran.
        staged = None
        body = list(getattr(data, "body", None) or [])
        body_len = len(body)
        if heal is not None and self._suite_position(data)[0] is not None:
            line_number, keyword, args = heal
            if not 1 <= line_number <= body_len:
                logger.warning(
                    "GenerativeListener: heal for %r targeted body line %d "
                    "of %d; recorded, not run.",
                    test_name,
                    line_number,
                    body_len,
                )
            elif not _assertion_like(body[line_number - 1]):
                # Replacing the ACTION that caused the failure (Ask LLM,
                # Fail, a setup step) with an assertion would make the
                # experiment trivially green and surface a false healing
                # candidate (Codex P2, PR #518). Only assertion lines are
                # eligible targets.
                logger.warning(
                    "GenerativeListener: heal for %r targeted body line %d "
                    "(%r), which is not an assertion; recorded, not run.",
                    test_name,
                    line_number,
                    getattr(body[line_number - 1], "name", ""),
                )
            else:
                staged = self._build_heal_copy(
                    data, test_name, line_number, keyword, args
                )
        persisted = self._persist(
            AgenticDecision(
                session_id=self._session_id,
                hook_event="end_test",
                prompt_model=getattr(self._provider, "model", "") or "",
                prompt_text=prompt,
                recorded_at=_utc_now(),
                test_name=test_name,
                response_text=response,
                proposed_action="heal",
                applied=0,  # ALWAYS: suggestion-only, no silent green-washing
                tokens_used=self._tokens_used,
                id=decision_id,
            )
        )
        if not persisted:
            if staged is not None:
                logger.warning(
                    "GenerativeListener: NOT running heal experiment for "
                    "test %r — the decision row could not be persisted and "
                    "heal experiments must stay auditable.",
                    test_name,
                )
            return
        if staged is None:
            if heal is None:
                logger.warning(
                    "GenerativeListener: heal response for %r was not a line "
                    "number plus one allow-listed assertion; recorded, not run.",
                    test_name,
                )
            return
        if not self._insert_mutation_copy(data, staged):
            return
        self._heal_experiment_ids[id(staged)] = decision_id
        line_number, keyword, args = heal  # type: ignore[misc]
        question = _fill_template(
            prompts["HEAL_GRADER_QUESTION"],
            test=test_name,
            suite=self._suite_name,
            message=getattr(result, "message", "") or "none",
            assertion="    ".join([keyword, *args]),
        )
        self._grade_assertion(
            decision_id,
            test_name,
            question,
            prompts["HEAL_GRADER_EXPECTED"],
            "    ".join([keyword, *args]),
        )

    def _build_heal_copy(
        self,
        data: Any,
        test_name: str,
        line_number: int,
        keyword: str,
        args: list[str],
    ) -> Any | None:
        """Construct the ``<original>::healed::<short_hash>`` side
        experiment: a deep copy with body line ``line_number`` (1-based)
        replaced by the proposed assertion."""
        assertion_line = "    ".join([keyword, *args])
        short_hash = hashlib.sha1(
            f"{line_number}:{assertion_line}".encode()
        ).hexdigest()[:8]
        try:
            copy = _copy_test(data)
            copy.name = f"{test_name}::healed::{short_hash}"
            _add_tag(copy, HEALED_MARKER_TAG)
            copy.body.create_keyword(name=keyword, args=list(args))
            replacement = copy.body.pop()
            copy.body[line_number - 1] = replacement
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning(
                "GenerativeListener: could not build heal experiment for %r: %s",
                test_name,
                exc,
            )
            return None
        return copy

    def _record_heal_outcome(self, decision_id: str, data: Any, result: Any) -> None:
        """Write the side experiment's outcome to ``agentic_metrics`` as
        ``heal_passed`` (1.0/0.0) with id ``<decision_id>-heal`` — the
        Superset healing-candidates chart joins it back to the decision."""
        status = str(getattr(result, "status", "") or "").upper()
        passed = status == "PASS" if status else bool(getattr(result, "passed", False))
        db = self._get_db()
        if db is None:
            return
        try:
            db.save_metric(
                AgenticMetric(
                    session_id=self._session_id,
                    metric_key=HEAL_PASSED_METRIC,
                    metric_value=1.0 if passed else 0.0,
                    recorded_at=_utc_now(),
                    id=f"{decision_id}{HEAL_METRIC_ID_SUFFIX}",
                )
            )
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning(
                "GenerativeListener: could not persist heal_passed for decision %s: %s",
                decision_id,
                exc,
            )

    def _write_budget_exhausted(self, hook_event: str, test_name: str) -> None:
        """Record ONE budget_exhausted marker, then go silent for the suite."""
        self._budget_exhausted = True
        logger.warning(
            "GenerativeListener: token budget (%d) exhausted for suite %r "
            "after %d tokens; going silent.",
            self._budget_tokens,
            self._suite_name,
            self._tokens_used,
        )
        self._persist(
            AgenticDecision(
                session_id=self._session_id,
                hook_event=hook_event,
                prompt_model=os.getenv("RFC_GENERATIVE_MODEL", DEFAULT_GENERATIVE_MODEL)
                if self._provider is None
                else (getattr(self._provider, "model", "") or ""),
                prompt_text="(suppressed: token budget exhausted)",
                recorded_at=_utc_now(),
                test_name=test_name,
                proposed_action="budget_exhausted",
                applied=0,
                tokens_used=self._tokens_used,
            )
        )

    @staticmethod
    def _tokens_consumed(provider: LLMProvider, prompt: str, response: str) -> int:
        """Tokens used by the last call: provider metrics, else a rough
        4-chars-per-token estimate so the budget always drains."""
        metrics = getattr(provider, "last_metrics", None) or {}
        prompt_tokens = metrics.get("prompt_eval_count")
        completion_tokens = metrics.get("eval_count")
        if prompt_tokens is not None or completion_tokens is not None:
            return int(prompt_tokens or 0) + int(completion_tokens or 0)
        return max(1, (len(prompt) + len(response)) // 4)

    def _persist(self, decision: AgenticDecision) -> bool:
        """Save a decision row; True on success (flow mutations gate on it)."""
        db = self._get_db()
        if db is None:
            return False
        try:
            db.save_decision(decision)
            self._persisted_count += 1
            return True
        except Exception as exc:  # skip-and-log: never fail the run
            logger.warning("GenerativeListener: decision persist failed: %s", exc)
            return False
