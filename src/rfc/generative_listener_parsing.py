"""Pure parse/render helpers for the generative listener.

Stateless: every function takes robot running-model nodes or plain strings.
Covers LLM-response parsing (flow action, mutation, heal), the mutation
allow-list and argument-safety rails (#501/#516), the suite keyword-shadow
guard (#516/#528), and the externalized mutate-prompt loader. Split out of
generative_listener.py to keep that module under the ~500-line cap
(docs/refactor.md).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Deterministic BuiltIn assertions a mutation may use — anything else is
# recorded (applied=0) but never executed. Excludes ``Should Match Regexp``:
# its model-controlled pattern is a ReDoS vector (#516).
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

# Ships as package data so installed (wheel) deployments resolve it too (#516).
MUTATE_PROMPTS_RESOURCE = (
    Path(__file__).resolve().parent / "resources" / "generative_mutate_prompts.resource"
)

_FLOW_ACTIONS = ("skip", "retry", "fork", "none")

# A "simple" scalar variable ``${plain name}``: identifier-ish, no nesting,
# no item access, no attribute access, no inline expressions.
_SIMPLE_VARIABLE_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_ ]*\}")

# Built-in fallbacks, kept in sync with
# resources/generative_mutate_prompts.resource (the reviewable copy).
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
    """Parse the resource's ``*** Variables ***`` section (via the Robot
    parsing API — never executed); fall back to built-ins. Honours a leading
    ``SEPARATOR=`` and unescapes ``\\${`` to ``${``. Cached per resolved path.
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
    """Action word from the FIRST non-empty response line only, so trailing
    rationale can't steer the run; unknown words map to ``none`` (recorded,
    never applied). The word may carry markdown/punctuation decoration."""
    for line in response.splitlines():
        word = line.strip().strip("*_`'\".,!?:;()[]{}").strip()
        if not word:
            continue
        return word.lower() if word.lower() in _FLOW_ACTIONS else "none"
    return "none"


def _safe_mutation_arg(arg: str) -> bool:
    """True when ``arg`` is plain text plus simple ``${scalar}`` variables only.

    Rejects ``${{...}}`` (inline Python), extended syntax (``${obj.attr}``,
    ``${list[0]}``), and ``%{}``/``@{}``/``&{}`` — any of which could execute
    code through an allow-listed keyword (#501). Literal braces that are not
    Robot variable syntax (e.g. the regex ``\\d{3}``) stay legal.
    """
    stripped = _SIMPLE_VARIABLE_RE.sub("", arg)
    return not any(tok in stripped for tok in ("${", "%{", "@{", "&{"))


def _parse_mutation(response: str) -> Optional[tuple[str, list[str]]]:
    """``(keyword, args)`` from the FIRST non-empty line only (see
    :func:`_parse_action`); ``None`` unless it is one allow-listed assertion
    with safe arguments."""
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
    """``(line_number, keyword, args)`` from the first two non-empty lines: a
    1-based body-line number then one allow-listed, safe-argument assertion
    (same first-lines-only defence as :func:`_parse_action`). ``None``
    otherwise; the number is range-checked against the body at build time."""
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


def _normalize_keyword_name(name: str) -> str:
    """Normalize a keyword name exactly as Robot does (``robot.utils.normalize``,
    underscores ignored) so the shadow guard matches Robot's own resolution,
    including Unicode casefolds ASCII ``lower()`` would miss (#516)."""
    from robot.utils import normalize

    return normalize(name, ignore=["_"])


def _suite_shadows_keyword(data: Any, keyword: str) -> bool:
    """True when a suite keyword would hijack the qualified
    ``BuiltIn.<keyword>`` call the mutation inserts.

    Only a suite keyword resolving to ``BuiltIn.<keyword>`` can shadow the
    qualified call (#516) — a bare ``Should Contain`` user keyword shadows the
    *unqualified* call, not ours, and must not block the mutation. Two shadow
    forms: a literal name that normalizes equal, or an embedded-argument name
    whose Robot-generated pattern matches. Walks the suite parent chain over
    both own keyword tables and imported-resource owners.
    """
    from robot.running.arguments.embedded import EmbeddedArguments

    qualified = f"BuiltIn.{keyword}"
    wanted_literal = {_normalize_keyword_name(qualified)}
    builtin_owner = _normalize_keyword_name("BuiltIn")
    # Raw name (not normalized) for Robot's embedded-arg regex matching.
    embedded_targets = (qualified,)
    node = getattr(data, "parent", None)
    while node is not None:
        resource = getattr(node, "resource", None)
        for kw in getattr(resource, "keywords", None) or []:
            name = getattr(kw, "name", "") or ""
            if _normalize_keyword_name(name) in wanted_literal:
                return True
            embedded = EmbeddedArguments.from_name(name)
            if embedded is not None and any(
                embedded.name.fullmatch(target) for target in embedded_targets
            ):
                return True
        # #528: an imported resource whose owner name is literally ``BuiltIn``
        # collides with the qualified ``BuiltIn.<keyword>`` call ("Multiple
        # keywords ... found") and is blocked conservatively. Only RESOURCE
        # imports collide; the real BuiltIn *library* is a LIBRARY import.
        for imp in getattr(resource, "imports", None) or []:
            if (getattr(imp, "type", "") or "").upper() != "RESOURCE":
                continue
            owner = Path(str(getattr(imp, "name", "") or "")).stem
            if _normalize_keyword_name(owner) == builtin_owner:
                return True
        node = getattr(node, "parent", None)
    return False


def _fill_template(template: str, **values: Any) -> str:
    """Substitute ``{placeholder}`` tokens by plain replacement, not
    ``str.format``: templates may contain literal Robot ``${...}`` that
    ``format`` would misread as a placeholder and raise (#501)."""
    for key, value in values.items():
        template = template.replace("{" + key + "}", str(value))
    return template


def _assertion_like(item: Any) -> bool:
    """True when a body item is an assertion (keyword name contains 'should').
    Heal may only replace assertions: swapping the failing *action* (``Ask
    LLM``, ``Fail``, a setup step) for one would make the experiment trivially
    green — a false healing candidate (#518)."""
    return "should" in (getattr(item, "name", "") or "").lower()


def _render_body(test: Any, numbered: bool = False) -> str:
    """Render a test body as Robot-style lines for the mutate/heal prompts.
    ``numbered`` prefixes each line with its 1-based index (heal names the
    line it wants to replace)."""
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
