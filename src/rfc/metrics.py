"""Metrics extraction and tag parsing helpers for Robot Framework listeners.

Extracted from ``db_listener.py`` to be reusable across listeners and
importable by other Robot Framework projects.
"""

import json
import os
from typing import Any, Dict, Optional

from robot.api import logger  # type: ignore
from robot.libraries.BuiltIn import BuiltIn  # type: ignore

T = Any  # type alias for nvl generic usage


def nvl(value: Any, default: T) -> T:
    """Return *default* when *value* is ``None`` (SQL NVL / COALESCE).

    Unlike ``dict.get(key, default)``, this replaces an explicit ``None``
    value — not just a missing key.
    """
    return default if value is None else value


def parse_tags(tags: list[str]) -> Dict[str, Any]:
    """Parse structured tag prefixes and sort remaining tags.

    Extracts ``severity:<val>``, ``tier:<int>``, and ``verify:<val>`` into
    dedicated fields.  Remaining tags are sorted alphabetically and joined
    with commas.  The structured prefixes are removed from the remaining
    tag string to avoid duplication.

    Args:
        tags: List of tag strings from Robot Framework test attributes.

    Returns:
        Dict with keys ``tag_severity``, ``tag_tier``, ``tag_verify``,
        and ``tags_sorted`` (comma-separated remaining tags or empty string).
    """
    severity: str = ""
    tier: int = -1
    verify: str = ""
    other: list[str] = []
    for tag in sorted(tags):
        if tag.startswith("severity:"):
            severity = tag.split(":", 1)[1]
        elif tag.startswith("tier:"):
            try:
                tier = int(tag.split(":", 1)[1])
            except ValueError:
                other.append(tag)
        elif tag.startswith("verify:"):
            verify = tag.split(":", 1)[1]
        else:
            other.append(tag)
    return {
        "tag_severity": severity,
        "tag_tier": tier,
        "tag_verify": verify,
        "tags_sorted": ",".join(other) if other else "",
    }


def safe_int(value: Optional[str]) -> Optional[int]:
    """Convert a string to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def extract_llm_metrics(metrics_json: Optional[str]) -> Dict[str, Any]:
    """Extract individual metrics from the llm_metrics JSON string.

    Returns a dict with keys matching the Ollama metrics names.
    Missing or unparseable data returns an empty dict.
    """
    if not metrics_json:
        return {}
    try:
        data = json.loads(metrics_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return {
        "eval_count": data.get("eval_count"),
        "eval_duration_ns": data.get("eval_duration_ns"),
        "prompt_eval_count": data.get("prompt_eval_count"),
        "prompt_eval_duration_ns": data.get("prompt_eval_duration_ns"),
        "load_duration_ns": data.get("load_duration_ns"),
        "total_duration_ns": data.get("total_duration_ns"),
        "eval_rate": data.get("eval_rate"),
        "num_ctx": data.get("num_ctx"),
        "num_predict": data.get("num_predict"),
        # OpenAI token detail fields
        "reasoning_tokens": data.get("reasoning_tokens"),
        "cached_tokens": data.get("cached_tokens"),
        "accepted_prediction_tokens": data.get("accepted_prediction_tokens"),
        "rejected_prediction_tokens": data.get("rejected_prediction_tokens"),
    }


def warn_near_miss(text: str) -> None:
    """Warn if *text* looks like a malformed ``RFC_DATA:`` message.

    Called only when *text* did NOT match the real prefix.  Checks for
    common typos: wrong case, missing underscore, space instead of
    underscore.
    """
    normalized = text.lstrip().upper().replace(" ", "_")
    if normalized.startswith("RFC_DATA:") or normalized.startswith("RFCDATA:"):
        logger.warn(
            f"Possible RFC_DATA typo (message ignored): "
            f"{text[:80]!r} — expected prefix 'RFC_DATA:'"
        )


def compute_token_efficiency(
    score: Optional[float], eval_count: Optional[int], pass_threshold: float = 0.5
) -> float:
    """Return tokens-per-correct-answer for a single test result.

    For correct answers (score >= pass_threshold) with token data,
    returns eval_count as the "cost" of that correct answer.
    Returns 0.0 when the answer is incorrect, ungraded, has no token data,
    or when either input is None (missing data).
    """
    if score is None or eval_count is None:
        return 0.0
    if score < pass_threshold or eval_count <= 0:
        return 0.0
    return float(eval_count)


def get_robot_float(var_name: str) -> float:
    """Get a float Robot variable, falling back to env var."""
    try:
        val = BuiltIn().get_variable_value(f"${{{var_name}}}")
        if val is not None:
            return float(val)
    except Exception:
        pass
    env_val = os.getenv(var_name)
    if env_val is not None:
        try:
            return float(env_val)
        except ValueError:
            pass
    return 0.0


def get_robot_int(var_name: str) -> int:
    """Get an int Robot variable, falling back to env var."""
    try:
        val = BuiltIn().get_variable_value(f"${{{var_name}}}")
        if val is not None:
            return int(val)
    except Exception:
        pass
    env_val = os.getenv(var_name)
    if env_val is not None:
        try:
            return int(env_val)
        except ValueError:
            pass
    return 0
